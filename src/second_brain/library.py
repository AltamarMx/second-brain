"""The only layer that reads and writes files inside ``library/``.

Files are Markdown with a YAML frontmatter block. Writing is deterministic
(field order from the models, fixed YAML style) and atomic (temp file +
rename), so diffs stay minimal and a crash never leaves half a file.
"""

from __future__ import annotations

import io
import os
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError
from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import LiteralScalarString

from .models import SCHEMA_VERSION, FigureSet, FullText, Paper, Project

FRONTMATTER_DELIMITER = "---"


class FrontmatterError(ValueError):
    """The file does not start with a valid YAML frontmatter block."""


class NewerSchemaError(RuntimeError):
    """The data was written by a newer version of the code."""


def _yaml() -> YAML:
    yaml = YAML(typ="rt")
    yaml.default_flow_style = False
    yaml.allow_unicode = True
    yaml.width = 4096  # never wrap long titles or abstracts
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.representer.ignore_aliases = lambda *_: True  # no &id001 anchors for repeated values
    yaml.representer.add_representer(
        type(None), lambda r, _: r.represent_scalar("tag:yaml.org,2002:null", "null")
    )
    return yaml


def _literal_multiline(value: Any) -> Any:
    """Use YAML block style (``|``) for multi-line strings such as abstracts."""
    if isinstance(value, dict):
        return {k: _literal_multiline(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_literal_multiline(v) for v in value]
    if isinstance(value, str) and "\n" in value:
        return LiteralScalarString(value)
    return value


def dump_frontmatter(meta: BaseModel, body: str = "") -> str:
    data = _literal_multiline(meta.model_dump(mode="python"))
    buffer = io.StringIO()
    _yaml().dump(data, buffer)
    body = body.strip("\n")
    text = f"{FRONTMATTER_DELIMITER}\n{buffer.getvalue()}{FRONTMATTER_DELIMITER}\n"
    return text + (f"\n{body}\n" if body else "")


def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    lines = text.split("\n")
    if not lines or lines[0].strip() != FRONTMATTER_DELIMITER:
        raise FrontmatterError("el archivo no empieza con '---'")
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == FRONTMATTER_DELIMITER:
            data = YAML(typ="safe").load("\n".join(lines[1:i])) or {}
            if not isinstance(data, dict):
                raise FrontmatterError("el frontmatter no es un mapa YAML")
            return data, "\n".join(lines[i + 1 :]).strip("\n")
    raise FrontmatterError("falta el '---' de cierre del frontmatter")


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


@dataclass(frozen=True)
class Document[M: BaseModel]:
    path: Path
    meta: M
    body: str


@dataclass(frozen=True)
class InvalidDocument:
    path: Path
    error: str


class Library:
    """A data repository: ``library/``, ``inbox/``, ``pdfs/`` and configuration."""

    def __init__(self, home: Path):
        self.home = home
        self.library_dir = home / "library"
        self.papers_dir = self.library_dir / "papers"
        self.fulltext_dir = self.library_dir / "fulltext"
        self.figures_dir = self.library_dir / "figures"
        self.notes_dir = self.library_dir / "notes"
        self.projects_dir = self.library_dir / "projects"
        self.inbox_dir = home / "inbox"
        self.pdfs_dir = home / "pdfs"
        self.cache_dir = home / ".cache"

    # --- generic -----------------------------------------------------------

    def _read[M: BaseModel](self, path: Path, model: type[M]) -> Document[M]:
        data, body = split_frontmatter(path.read_text(encoding="utf-8"))
        version = data.get("schema_version", SCHEMA_VERSION)
        if isinstance(version, int) and version > SCHEMA_VERSION:
            raise NewerSchemaError(
                f"{path.name} usa schema_version {version}; este código entiende hasta "
                f"{SCHEMA_VERSION}. Actualiza con: git pull && uv sync"
            )
        return Document(path=path, meta=model.model_validate(data), body=body)

    def _iter[M: BaseModel](
        self, directory: Path, model: type[M]
    ) -> Iterator[Document[M] | InvalidDocument]:
        for path in sorted(directory.glob("*.md")):
            try:
                yield self._read(path, model)
            except (FrontmatterError, ValidationError, NewerSchemaError) as exc:
                yield InvalidDocument(path=path, error=str(exc))
            except Exception as exc:  # malformed YAML and similar
                yield InvalidDocument(path=path, error=f"{type(exc).__name__}: {exc}")

    # --- papers ------------------------------------------------------------

    def paper_path(self, citekey: str) -> Path:
        return self.papers_dir / f"{citekey}.md"

    def read_paper(self, citekey: str) -> Document[Paper]:
        return self._read(self.paper_path(citekey), Paper)

    def write_paper(self, paper: Paper, body: str = "") -> Path:
        paper = paper.model_copy(update={"schema_version": SCHEMA_VERSION})
        path = self.paper_path(paper.citekey)
        atomic_write(path, dump_frontmatter(paper, body))
        return path

    def iter_papers(self) -> Iterator[Document[Paper] | InvalidDocument]:
        return self._iter(self.papers_dir, Paper)

    # --- projects ----------------------------------------------------------

    def project_path(self, slug: str) -> Path:
        return self.projects_dir / f"{slug}.md"

    def read_project(self, slug: str) -> Document[Project]:
        return self._read(self.project_path(slug), Project)

    def write_project(self, project: Project, body: str = "") -> Path:
        project = project.model_copy(update={"schema_version": SCHEMA_VERSION})
        path = self.project_path(project.slug)
        atomic_write(path, dump_frontmatter(project, body))
        return path

    def iter_projects(self) -> Iterator[Document[Project] | InvalidDocument]:
        return self._iter(self.projects_dir, Project)

    # --- full text and figures ----------------------------------------------

    def fulltext_path(self, citekey: str) -> Path:
        return self.fulltext_dir / f"{citekey}.md"

    def read_fulltext(self, citekey: str) -> Document[FullText]:
        return self._read(self.fulltext_path(citekey), FullText)

    def write_fulltext(self, fulltext: FullText, body: str) -> Path:
        path = self.fulltext_path(fulltext.citekey)
        atomic_write(path, dump_frontmatter(fulltext, body))
        return path

    def iter_fulltexts(self) -> Iterator[Document[FullText] | InvalidDocument]:
        return self._iter(self.fulltext_dir, FullText)

    def figures_path(self, citekey: str) -> Path:
        return self.figures_dir / f"{citekey}.md"

    def read_figure_set(self, citekey: str) -> Document[FigureSet]:
        return self._read(self.figures_path(citekey), FigureSet)

    def write_figure_set(self, figure_set: FigureSet, body: str) -> Path:
        path = self.figures_path(figure_set.citekey)
        atomic_write(path, dump_frontmatter(figure_set, body))
        return path

    def iter_figure_sets(self) -> Iterator[Document[FigureSet] | InvalidDocument]:
        return self._iter(self.figures_dir, FigureSet)

    def migrate(self) -> int:
        """Rewrite every paper and project with the current schema version; return how many changed."""
        changed = 0
        for docs, write in (
            (self.iter_papers(), self.write_paper),
            (self.iter_projects(), self.write_project),
        ):
            for doc in docs:
                if isinstance(doc, InvalidDocument) or doc.meta.schema_version == SCHEMA_VERSION:
                    continue
                write(doc.meta, doc.body)
                changed += 1
        return changed

    def remove_paper(self, citekey: str) -> list[Path]:
        """Delete the record, its full text and figures. Notes and the PDF are left alone."""
        removed = []
        for path in (
            self.paper_path(citekey),
            self.fulltext_path(citekey),
            self.figures_dir / f"{citekey}.md",
        ):
            if path.exists():
                path.unlink()
                removed.append(path)
        return removed

    # --- local files -------------------------------------------------------

    def inbox_pdfs(self) -> list[Path]:
        """PDFs waiting in ``inbox/`` (not in its ``_errores``/``_duplicados`` subfolders)."""
        if not self.inbox_dir.is_dir():
            return []
        return sorted(
            p for p in self.inbox_dir.iterdir() if p.is_file() and p.suffix.lower() == ".pdf"
        )

    def local_pdfs(self) -> list[Path]:
        if not self.pdfs_dir.is_dir():
            return []
        return sorted(p for p in self.pdfs_dir.glob("*.pdf") if p.is_file())
