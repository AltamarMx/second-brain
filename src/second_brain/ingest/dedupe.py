"""In-memory index of the library used to detect duplicates during ingestion."""

from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import fuzz

from ..library import InvalidDocument, Library
from ..models import Paper
from ..textutil import normalize_for_match
from .doi import normalize_doi

SIMILAR_TITLE = 93


@dataclass(frozen=True)
class Entry:
    citekey: str
    title: str
    year: int | None
    family: str


def _family(paper: Paper) -> str:
    return normalize_for_match(paper.authors[0].family) if paper.authors else ""


class LibraryIndex:
    def __init__(self) -> None:
        self.papers: dict[str, Paper] = {}
        self.by_sha: dict[str, str] = {}
        self.by_doi: dict[str, str] = {}
        self.entries: list[Entry] = []

    @classmethod
    def build(cls, lib: Library) -> LibraryIndex:
        index = cls()
        for doc in lib.iter_papers():
            if not isinstance(doc, InvalidDocument):
                index.add(doc.meta)
        return index

    def add(self, paper: Paper) -> None:
        self.papers[paper.citekey] = paper
        if paper.pdf:
            self.by_sha[paper.pdf.sha256] = paper.citekey
        if paper.doi:
            self.by_doi[normalize_doi(paper.doi)] = paper.citekey
        self.entries = [e for e in self.entries if e.citekey != paper.citekey]
        self.entries.append(
            Entry(paper.citekey, normalize_for_match(paper.title), paper.year, _family(paper))
        )

    def find_by_sha(self, sha256: str) -> str | None:
        return self.by_sha.get(sha256)

    def find_by_doi(self, doi: str) -> str | None:
        return self.by_doi.get(normalize_doi(doi))

    def find_similar(self, title: str, year: int | None, family: str | None) -> str | None:
        """Same work under another DOI (preprint vs. published) or without DOI."""
        norm_title = normalize_for_match(title)
        norm_family = normalize_for_match(family or "")
        for entry in self.entries:
            if year and entry.year and abs(year - entry.year) > 1:
                continue
            if norm_family and entry.family and norm_family != entry.family:
                continue
            if fuzz.ratio(norm_title, entry.title) >= SIMILAR_TITLE:
                return entry.citekey
        return None
