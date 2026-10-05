"""``sb check``: validate the library against the data contract."""

from __future__ import annotations

import os
import re
import subprocess
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from .config import CONFIG_FILENAME, LibraryConfig, load_config
from .ingest.doi import normalize_doi
from .library import InvalidDocument, Library
from .machines import MACHINES_DIRNAME, MachineProfile
from .models import ALIAS_PATTERN

Level = Literal["error", "warning"]
SKIP_SIZE_DIRS = {".git", ".venv", ".cache", "inbox", "pdfs", "logs"}


@dataclass(frozen=True)
class Issue:
    level: Level
    path: str
    message: str


@dataclass
class CheckReport:
    issues: list[Issue] = field(default_factory=list)
    papers: int = 0
    projects: int = 0

    def add(self, level: Level, path: Path | str, message: str, home: Path) -> None:
        shown = Path(path)
        if shown.is_absolute() and shown.is_relative_to(home):
            shown = shown.relative_to(home)
        self.issues.append(Issue(level, str(shown), message))

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "error"]

    @property
    def ok(self) -> bool:
        return not self.errors


def run_checks(home: Path, *, fast: bool = False) -> CheckReport:
    report = CheckReport()
    lib = Library(home)

    try:
        config = load_config(home)
    except (tomllib.TOMLDecodeError, ValidationError) as exc:
        report.add("error", CONFIG_FILENAME, f"configuración inválida: {exc}", home)
        config = LibraryConfig()

    _check_layout(lib, report)
    _check_machines(home, report)
    projects = _check_projects(lib, config, report)
    _check_bib_outputs(home, projects, report)
    citekeys = _check_papers(lib, config, projects, report)
    if not fast:
        _check_companions(lib, citekeys, report)
    _check_sizes(home, config.checks.max_file_mb, report)
    _check_no_pdfs_in_git(home, report)
    return report


def _check_layout(lib: Library, report: CheckReport) -> None:
    for directory in (lib.inbox_dir, lib.pdfs_dir):
        if not (directory / ".gitkeep").is_file():
            report.add(
                "error", directory, "falta .gitkeep (la carpeta debe existir en git)", lib.home
            )
    for directory in (lib.papers_dir, lib.fulltext_dir, lib.figures_dir, lib.projects_dir):
        if not directory.is_dir():
            report.add("error", directory, "falta la carpeta", lib.home)


def _check_machines(home: Path, report: CheckReport) -> None:
    for path in sorted((home / MACHINES_DIRNAME).glob("*.toml")):
        try:
            with path.open("rb") as handle:
                MachineProfile.model_validate(tomllib.load(handle))
        except (tomllib.TOMLDecodeError, ValidationError) as exc:
            report.add("error", path, f"perfil de máquina inválido: {exc}", home)


def _check_bib_outputs(home: Path, projects: set[str], report: CheckReport) -> None:
    for path in sorted((home / MACHINES_DIRNAME).glob("*.toml")):
        try:
            with path.open("rb") as handle:
                outputs = tomllib.load(handle).get("bib_outputs", {})
        except tomllib.TOMLDecodeError:
            continue  # already reported by _check_machines
        for slug in outputs:
            if slug not in projects:
                report.add(
                    "warning",
                    path,
                    f"[bib_outputs] menciona el proyecto '{slug}', que no existe",
                    home,
                )


def _invalid(doc: InvalidDocument, report: CheckReport, home: Path) -> None:
    report.add("error", doc.path, doc.error, home)


def _check_projects(lib: Library, config: LibraryConfig, report: CheckReport) -> set[str]:
    slugs: set[str] = set()
    for doc in lib.iter_projects():
        if isinstance(doc, InvalidDocument):
            _invalid(doc, report, lib.home)
            continue
        report.projects += 1
        project = doc.meta
        slugs.add(project.slug)
        if doc.path.stem != project.slug:
            report.add(
                "error",
                doc.path,
                f"el nombre del archivo no coincide con slug '{project.slug}'",
                lib.home,
            )
        if project.kind is not None and project.kind not in config.vocab.project_kind:
            report.add(
                "error",
                doc.path,
                f"kind '{project.kind}' no está en [vocab].project_kind de config.toml",
                lib.home,
            )
    return slugs


def _check_papers(
    lib: Library, config: LibraryConfig, projects: set[str], report: CheckReport
) -> set[str]:
    citekeys: set[str] = set()
    dois: dict[str, Path] = {}
    aliases: dict[str, str] = {}
    for doc in lib.iter_papers():
        if isinstance(doc, InvalidDocument):
            _invalid(doc, report, lib.home)
            continue
        report.papers += 1
        paper = doc.meta
        citekeys.add(paper.citekey)
        if doc.path.stem != paper.citekey:
            report.add(
                "error",
                doc.path,
                f"el nombre del archivo no coincide con citekey '{paper.citekey}'",
                lib.home,
            )
        if paper.doi:
            key = normalize_doi(paper.doi)
            if key in dois:
                report.add(
                    "error", doc.path, f"DOI repetido con {dois[key].name}: {paper.doi}", lib.home
                )
            else:
                dois[key] = doc.path
        study = paper.classification.study_type
        if study is not None and study not in config.vocab.study_type:
            report.add(
                "error", doc.path, f"study_type '{study}' no está en [vocab].study_type", lib.home
            )
        for alias in paper.aliases:
            if not re.fullmatch(ALIAS_PATTERN, alias):
                report.add("error", doc.path, f"alias inválido: {alias!r}", lib.home)
            elif alias in aliases:
                report.add(
                    "error",
                    doc.path,
                    f"el alias '{alias}' también es de {aliases[alias]}",
                    lib.home,
                )
            aliases[alias] = paper.citekey
        for slug in paper.projects:
            if slug not in projects:
                report.add("error", doc.path, f"el proyecto '{slug}' no existe", lib.home)
    for alias, owner in aliases.items():
        if alias in citekeys:
            report.add(
                "error",
                lib.paper_path(owner),
                f"el alias '{alias}' es el citekey de otro artículo",
                lib.home,
            )
    return citekeys


def _check_companions(lib: Library, citekeys: set[str], report: CheckReport) -> None:
    for kind, docs in (
        ("texto completo", lib.iter_fulltexts()),
        ("figuras", lib.iter_figure_sets()),
    ):
        for doc in docs:
            if isinstance(doc, InvalidDocument):
                _invalid(doc, report, lib.home)
                continue
            if doc.meta.citekey not in citekeys:
                report.add("warning", doc.path, f"{kind} sin artículo en papers/", lib.home)


def _check_sizes(home: Path, max_mb: float, report: CheckReport) -> None:
    limit = max_mb * 1024 * 1024
    for root, dirs, filenames in os.walk(home):
        if Path(root) == home:
            dirs[:] = [d for d in dirs if d not in SKIP_SIZE_DIRS]
        for filename in filenames:
            path = Path(root) / filename
            size = path.stat().st_size
            if size > limit:
                mb = size / 1024 / 1024
                report.add("error", path, f"pesa {mb:.1f} MB (máximo {max_mb:g} MB)", home)


def _check_no_pdfs_in_git(home: Path, report: CheckReport) -> None:
    if not (home / ".git").exists():
        return
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--", "*.pdf", "*.PDF"],
        cwd=home,
        capture_output=True,
        text=True,
    )
    for line in result.stdout.splitlines():
        report.add("error", line, "hay un PDF en git: sácalo con git rm --cached", home)
