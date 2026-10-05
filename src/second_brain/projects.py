"""Projects: creation, membership and listing.

Membership lives in each paper (``projects:``), so adding a paper to a
project rewrites one small file and never a growing list.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

from rapidfuzz import process

from .config import LibraryConfig
from .library import Document, InvalidDocument, Library
from .models import CITEKEY_PATTERN, SLUG_PATTERN, Membership, Paper, Project


class ProjectError(ValueError):
    pass


@dataclass(frozen=True)
class ProjectSummary:
    project: Project
    description: str
    members: list[str]


def existing_slugs(lib: Library) -> list[str]:
    return sorted(p.stem for p in lib.projects_dir.glob("*.md"))


def suggest(lib: Library, slug: str) -> str | None:
    match = process.extractOne(slug, existing_slugs(lib), score_cutoff=70)
    return match[0] if match else None


def require_project(lib: Library, slug: str) -> Document[Project]:
    if not lib.project_path(slug).is_file():
        hint = suggest(lib, slug)
        extra = f" ¿Quisiste decir '{hint}'?" if hint else ""
        raise ProjectError(
            f"el proyecto '{slug}' no existe.{extra} Créalo con: sb project create {slug}"
        )
    return lib.read_project(slug)


def create_project(
    lib: Library,
    config: LibraryConfig,
    slug: str,
    name: str,
    kind: str | None = None,
    description: str = "",
    today: dt.date | None = None,
) -> Project:
    if not re.fullmatch(SLUG_PATTERN, slug):
        raise ProjectError(
            f"slug inválido '{slug}': usa minúsculas, dígitos y guiones (p. ej., tesis-doctoral)"
        )
    if lib.project_path(slug).exists():
        raise ProjectError(f"el proyecto '{slug}' ya existe")
    if kind is not None and kind not in config.vocab.project_kind:
        allowed = ", ".join(config.vocab.project_kind)
        raise ProjectError(
            f"tipo '{kind}' no permitido; usa uno de: {allowed} (o añádelo en config.toml)"
        )
    project = Project(slug=slug, name=name, kind=kind, created=today or dt.date.today())
    lib.write_project(project, description)
    return project


def _papers(lib: Library, citekeys: list[str]) -> list[Document[Paper]]:
    missing = [
        k
        for k in citekeys
        if not re.fullmatch(CITEKEY_PATTERN, k) or not lib.paper_path(k).is_file()
    ]
    if missing:
        raise ProjectError("no existen estos artículos: " + ", ".join(missing))
    return [lib.read_paper(k) for k in citekeys]


def add_papers(
    lib: Library,
    slug: str,
    citekeys: list[str],
    note: str | None = None,
    today: dt.date | None = None,
) -> tuple[list[str], list[str]]:
    """Returns (added, already members). An existing membership only gets its note updated."""
    require_project(lib, slug)
    added, present = [], []
    for doc in _papers(lib, citekeys):
        projects = dict(doc.meta.projects)
        if slug in projects:
            present.append(doc.meta.citekey)
            if note is None:
                continue
            projects[slug] = projects[slug].model_copy(update={"note": note})
        else:
            projects[slug] = Membership(added=today or dt.date.today(), note=note)
            added.append(doc.meta.citekey)
        lib.write_paper(doc.meta.model_copy(update={"projects": projects}), doc.body)
    return added, present


def remove_papers(lib: Library, slug: str, citekeys: list[str]) -> tuple[list[str], list[str]]:
    """Returns (removed, not members)."""
    require_project(lib, slug)
    removed, absent = [], []
    for doc in _papers(lib, citekeys):
        if slug not in doc.meta.projects:
            absent.append(doc.meta.citekey)
            continue
        projects = {k: v for k, v in doc.meta.projects.items() if k != slug}
        lib.write_paper(doc.meta.model_copy(update={"projects": projects}), doc.body)
        removed.append(doc.meta.citekey)
    return removed, absent


def members(lib: Library, slug: str) -> list[Paper]:
    return [
        doc.meta
        for doc in lib.iter_papers()
        if not isinstance(doc, InvalidDocument) and slug in doc.meta.projects
    ]


def summaries(lib: Library) -> list[ProjectSummary]:
    counts: dict[str, list[str]] = {}
    for doc in lib.iter_papers():
        if isinstance(doc, InvalidDocument):
            continue
        for slug in doc.meta.projects:
            counts.setdefault(slug, []).append(doc.meta.citekey)
    return [
        ProjectSummary(doc.meta, doc.body, sorted(counts.get(doc.meta.slug, [])))
        for doc in lib.iter_projects()
        if not isinstance(doc, InvalidDocument)
    ]


def set_status(lib: Library, slug: str, status: str) -> Project:
    doc = require_project(lib, slug)
    project = doc.meta.model_copy(update={"status": status})
    lib.write_project(project, doc.body)
    return project
