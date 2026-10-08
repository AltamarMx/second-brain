"""Find and normalize DOIs and arXiv identifiers."""

from __future__ import annotations

import re

# Pattern recommended by Crossref for modern DOIs.
DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)
ARXIV_RE = re.compile(r"arxiv[:\s]*(\d{4}\.\d{4,5})(?:v\d+)?", re.IGNORECASE)
# SSRN papers carry "ssrn.com/abstract=4856145" (or "abstract_id="); their DOI is 10.2139/ssrn.N
SSRN_RE = re.compile(
    r"ssrn\.com/(?:abstract|sol3/papers\.cfm\?abstract_id)=(\d{5,9})", re.IGNORECASE
)
_DOI_CONTEXT_RE = re.compile(r"(doi|doi\.org)\W{0,6}$", re.IGNORECASE)
# A DOI wrapped at the end of a line: "10.1016/j.buildenv.\n2018.12.011"
_WRAPPED_RE = re.compile(r"(10\.\d{4,9}/\S*[./_-])\s*\n\s*(?=[A-Za-z0-9])")
# Text glued to a DOI by the PDF: "…2021.110987Received" → cut before "Received"
_GLUED_RE = re.compile(r"(?<=[0-9a-z)])(?=[A-Z][a-z]{2,})")
_TRAILING = ".,;:"


def normalize_doi(doi: str) -> str:
    doi = doi.strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "doi:"):
        doi = doi.removeprefix(prefix)
    return doi.replace("%2f", "/").strip()


def _clean(raw: str) -> str:
    doi = raw.rstrip(_TRAILING)
    # drop unbalanced closing parentheses picked up from the sentence: "(doi:10.1/x)"
    while doi.endswith(")") and doi.count("(") < doi.count(")"):
        doi = doi[:-1].rstrip(_TRAILING)
    return doi


def doi_variants(raw: str) -> list[str]:
    """The DOI as found, plus a version cut where extra text seems glued to it."""
    variants = [_clean(raw)]
    parts = _GLUED_RE.split(raw, maxsplit=1)
    if len(parts) == 2 and parts[0].count("/") >= 1:
        variants.append(_clean(parts[0]))
    seen: list[str] = []
    for variant in variants:
        normalized = normalize_doi(variant)
        if DOI_RE.fullmatch(normalized) and normalized not in seen:
            seen.append(normalized)
    return seen


def find_dois(text: str) -> list[str]:
    """Raw DOI candidates in order of appearance; those preceded by "doi" come first."""
    text = _WRAPPED_RE.sub(r"\1", text)
    labelled: list[str] = []
    bare: list[str] = []
    for match in DOI_RE.finditer(text):
        target = (
            labelled
            if _DOI_CONTEXT_RE.search(text[max(0, match.start() - 12) : match.start()])
            else bare
        )
        target.append(match.group(0))
    unique: list[str] = []
    for raw in labelled + bare:
        if normalize_doi(_clean(raw)) not in {normalize_doi(_clean(u)) for u in unique}:
            unique.append(raw)
    return unique


def find_arxiv(text: str) -> str | None:
    match = ARXIV_RE.search(text)
    return match.group(1) if match else None


def find_ssrn_doi(text: str) -> str | None:
    match = SSRN_RE.search(text)
    return f"10.2139/ssrn.{match.group(1)}" if match else None
