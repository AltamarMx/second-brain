"""``sb import bib``: register the entries of an existing ``.bib`` file.

Works with any ``.bib`` (Zotero, Mendeley, JabRef, hand-written). Each entry
becomes a record in ``awaiting_pdf`` that keeps its citekey, so existing
``.tex`` documents still compile. With a DOI, metadata comes from Crossref
(or DataCite); without one, from the ``.bib``. Dropping the PDFs into
``inbox/`` afterwards attaches each one to its record.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import bibtexparser
from pylatexenc.latex2text import LatexNodes2Text

from .citekey import make_citekey
from .ingest.dedupe import LibraryIndex
from .ingest.doi import DOI_RE, normalize_doi
from .ingest.metadata import MetadataClient, NetworkError, crossref_fields, datacite_fields
from .library import Library
from .models import ALIAS_PATTERN, CITEKEY_PATTERN, Paper, Provenance
from .textutil import normalize_for_match

Outcome = Literal["imported", "alias", "duplicate", "conflict", "error"]

BIB_TYPES = {
    "article": "article-journal",
    "inproceedings": "paper-conference",
    "conference": "paper-conference",
    "incollection": "chapter",
    "inbook": "chapter",
    "book": "book",
    "phdthesis": "thesis",
    "mastersthesis": "thesis",
    "thesis": "thesis",
    "techreport": "report",
    "report": "report",
    "standard": "standard",
    "dataset": "dataset",
}
_latex = LatexNodes2Text(math_mode="text")


@dataclass
class ImportResult:
    key: str
    outcome: Outcome
    citekey: str | None = None
    doi: str | None = None
    message: str = ""


def decode(value: str | None) -> str | None:
    if value is None:
        return None
    text = " ".join(_latex.latex_to_text(value).split())
    return text or None


def _split_top_level(text: str, separator: re.Pattern[str]) -> list[str]:
    """Split ``text`` at ``separator`` only outside braces."""
    parts, depth, start = [], 0, 0
    position = 0
    while position < len(text):
        char = text[position]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        elif depth == 0 and (match := separator.match(text, position)):
            parts.append(text[start:position])
            position = start = match.end()
            continue
        position += 1
    parts.append(text[start:])
    return [p.strip() for p in parts if p.strip()]


def parse_authors(raw: str | None) -> list[dict[str, str | None]]:
    """BibTeX names: ``Last, First``, ``First von Last`` and ``{Organization}``."""
    authors = []
    for name in _split_top_level(raw or "", re.compile(r"\s+and\s+", re.IGNORECASE)):
        if name.startswith("{") and name.endswith("}") and name.count("{") == 1:
            authors.append({"family": decode(name[1:-1]), "given": None})
            continue
        parts = _split_top_level(name, re.compile(r","))
        if len(parts) >= 2:
            family, given = parts[0], parts[-1]
        else:
            tokens = _split_top_level(name, re.compile(r"\s+"))
            if len(tokens) == 1:
                family, given = tokens[0], ""
            else:
                last = len(tokens) - 1
                start = last
                while start > 1 and tokens[start - 1][:1].islower():  # "de la" Cruz
                    start -= 1
                family, given = " ".join(tokens[start:]), " ".join(tokens[:start])
        authors.append({"family": decode(family) or family, "given": decode(given)})
    return [a for a in authors if a["family"]]


def bib_fields(entry: Any) -> dict[str, Any]:
    fields = {k.lower(): f.value for k, f in entry.fields_dict.items()}
    kind = BIB_TYPES.get(entry.entry_type.lower(), "article")
    year = fields.get("year") or (fields.get("date") or "")[:4]
    container = fields.get("journal") or fields.get("journaltitle") or fields.get("booktitle")
    publisher = fields.get("publisher") or fields.get("school") or fields.get("institution")
    keywords = re.split(r"[;,]", decode(fields.get("keywords")) or "")
    return {
        "type": kind,
        "doi": doi_from_fields(fields),
        "ids": {"isbn": decode(fields.get("isbn"))},
        "title": decode(fields.get("title")) or "(sin título)",
        "authors": parse_authors(fields.get("author") or fields.get("editor")),
        "year": int(year) if str(year).isdigit() else None,
        "container_title": decode(container),
        "volume": decode(fields.get("volume")),
        "issue": decode(fields.get("number") or fields.get("issue")),
        "pages": decode(re.sub(r"-+|–|—", "-", fields.get("pages") or "")) or None,
        "publisher": decode(publisher),
        "language": decode(fields.get("language") or fields.get("langid")),
        "abstract": decode(fields.get("abstract")),
        "tags": [k.strip() for k in keywords if k.strip()],
    }


def doi_from_fields(fields: dict[str, str]) -> str | None:
    for value in (fields.get("doi"), fields.get("url"), fields.get("note")):
        if value and (match := DOI_RE.search(value)):
            return normalize_doi(match.group(0).rstrip(".,;"))
    return None


def sanitize_key(key: str) -> str:
    """A valid citekey derived from any BibTeX key: ``Lopez:2019_x`` → ``lopez-2019-x``."""
    from .textutil import ascii_fold

    slug = re.sub(r"[^a-z0-9]+", "-", ascii_fold(key).lower()).strip("-")
    return slug or "entrada"


def import_bib(
    lib: Library,
    client: MetadataClient,
    path: Path,
    *,
    project: str | None = None,
    dry_run: bool = False,
    today: dt.date | None = None,
) -> list[ImportResult]:
    today = today or dt.date.today()
    index = LibraryIndex.build(lib)
    aliases = {a: p.citekey for p in index.papers.values() for a in p.aliases}
    library = bibtexparser.parse_file(str(path))
    results = []
    for entry in library.entries:
        key = entry.key.strip()
        result = ImportResult(key=key, outcome="error")
        results.append(result)
        try:
            fields = bib_fields(entry)
            doi = fields["doi"]
            result.doi = doi
            existing = index.find_by_doi(doi) if doi else None
            if existing is None and (key in index.papers or key in aliases):
                existing_key = key if key in index.papers else aliases[key]
                result.citekey = existing_key
                other = index.papers[existing_key]
                same = normalize_for_match(other.title) == normalize_for_match(fields["title"]) or (
                    index.find_similar(fields["title"], fields.get("year"), None) == existing_key
                )
                if same:  # the same work without DOI, imported before
                    result.outcome, result.message = (
                        "duplicate",
                        f"ya está en la biblioteca como {existing_key}",
                    )
                    continue
                result.outcome = "conflict"
                result.message = (
                    f"el citekey '{key}' ya lo usa {existing_key}, que es otro artículo"
                )
                continue
            if existing:
                paper = index.papers[existing]
                result.citekey = existing
                if key == existing or key in paper.aliases:
                    result.outcome, result.message = (
                        "duplicate",
                        f"ya está en la biblioteca como {existing}",
                    )
                    continue
                updated = paper.model_copy(update={"aliases": [*paper.aliases, key]})
                if not dry_run:
                    lib.write_paper(updated, lib.read_paper(existing).body)
                index.add(updated)
                result.outcome = "alias"
                result.message = (
                    f"ya existía como {existing}; '{key}' queda como alias para tus .tex"
                )
                continue

            source = "bib"
            if doi:
                try:
                    message = client.crossref_work(doi)
                    if message:
                        fields, source = (
                            {**fields, **crossref_fields(message), "tags": fields["tags"]},
                            "crossref",
                        )
                    elif attributes := client.datacite_work(doi):
                        fields, source = (
                            {**fields, **datacite_fields(attributes), "tags": fields["tags"]},
                            "datacite",
                        )
                except NetworkError:
                    result.message = "sin conexión: se usaron los datos del .bib"

            valid = re.fullmatch(CITEKEY_PATTERN, key) is not None
            if valid:
                citekey, alias = key, []
            else:
                if not re.fullmatch(ALIAS_PATTERN, key):
                    raise ValueError(f"citekey inválido en el .bib: {key!r}")
                base = sanitize_key(key)
                citekey = (
                    base
                    if base not in index.papers
                    else make_citekey(
                        (fields["authors"] or [{}])[0].get("family"),
                        fields.get("year"),
                        fields["title"],
                        set(index.papers),
                    )
                )
                alias = [key]
            family = (fields["authors"] or [{}])[0].get("family")
            similar = index.find_similar(fields["title"], fields.get("year"), family)
            paper = Paper.model_validate(
                {
                    **fields,
                    "citekey": citekey,
                    "aliases": alias,
                    "projects": {project: {"added": today}} if project else {},
                    "status": "awaiting_pdf",
                    "flags": ["possible_duplicate"] if similar else [],
                    "added": today,
                    "provenance": Provenance(metadata_source=source),
                }
            )
            if not dry_run:
                lib.write_paper(paper)
            index.add(paper)
            result.outcome, result.citekey = "imported", citekey
            notes = [result.message] if result.message else []
            if alias:
                notes.append(f"citekey de la biblioteca: {citekey} (alias {key})")
            if similar:
                notes.append(f"parecido a {similar}")
            result.message = "; ".join(notes)
        except Exception as exc:  # one bad entry must not stop the import
            result.outcome, result.message = "error", f"{type(exc).__name__}: {exc}"
    return results
