"""Pydantic schemas for every file in ``library/``.

These models are the code side of the data contract documented in
``docs/formato-datos.md``. Field order here is the serialization order.
"""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = 1

CITEKEY_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"
SLUG_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"

PaperStatus = Literal["awaiting_pdf", "needs_review", "needs_processing", "processed"]
PaperFlag = Literal[
    "doi_uncertain",
    "metadata_mismatch",
    "ocr",
    "possible_duplicate",
    "pdf_version_mismatch",
    "retracted",
]
PdfSource = Literal["inbox", "openaccess", "institutional"]
ProjectStatus = Literal["active", "paused", "archived"]


class Model(BaseModel):
    """Base: reject unknown fields so typos in hand-edited YAML are caught."""

    model_config = ConfigDict(extra="forbid")


class Author(Model):
    family: str
    given: str | None = None
    orcid: str | None = None


class Ids(Model):
    arxiv: str | None = None
    isbn: str | None = None
    openalex: str | None = None


class Location(Model):
    country: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    region: str | None = None
    locality: str | None = None
    page: int | None = None


class Classification(Model):
    study_type: str | None = None
    locations: list[Location] = []
    reviewed: bool = False


class Membership(Model):
    added: dt.date
    note: str | None = None


class PdfInfo(Model):
    sha256: str
    pages: int
    size_bytes: int
    source: PdfSource
    original_filename: str | None = None


class LlmProvenance(Model):
    backend: str
    model: str
    prompt: str
    machine: str | None = None
    date: dt.date
    sha256: str | None = None


class Provenance(Model):
    metadata_source: str | None = None
    extractor: str | None = None
    fulltext_sha256: str | None = None
    process: LlmProvenance | None = None
    figures: LlmProvenance | None = None


class Paper(Model):
    """Frontmatter of ``library/papers/{citekey}.md``; the body holds the summary."""

    schema_version: int = SCHEMA_VERSION
    citekey: str = Field(pattern=CITEKEY_PATTERN)
    type: str = "article-journal"
    doi: str | None = None
    ids: Ids = Ids()
    title: str
    authors: list[Author] = []
    year: int | None = None
    container_title: str | None = None
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None
    publisher: str | None = None
    language: str | None = None
    license: str | None = None
    abstract: str | None = None
    keywords: list[str] = []
    tags: list[str] = []
    classification: Classification = Classification()
    projects: dict[str, Membership] = {}
    pdf: PdfInfo | None = None
    figures: int = 0
    status: PaperStatus = "needs_processing"
    flags: list[PaperFlag] = []
    added: dt.date
    provenance: Provenance = Provenance()


class Project(Model):
    """Frontmatter of ``library/projects/{slug}.md``; the body is its description."""

    schema_version: int = SCHEMA_VERSION
    slug: str = Field(pattern=SLUG_PATTERN)
    name: str
    kind: str | None = None
    status: ProjectStatus = "active"
    created: dt.date


class FullText(Model):
    """Frontmatter of ``library/fulltext/{citekey}.md``; the body is the extracted text."""

    citekey: str = Field(pattern=CITEKEY_PATTERN)
    source_pdf_sha256: str
    extractor: str
    extracted: dt.date
    pages: int
    ocr: bool = False


class FigureRef(Model):
    id: str
    page: int
    kind: str | None = None


class FigureSet(Model):
    """Frontmatter of ``library/figures/{citekey}.md``; the body holds the descriptions."""

    citekey: str = Field(pattern=CITEKEY_PATTERN)
    figures: list[FigureRef] = []
    provenance: LlmProvenance | None = None
