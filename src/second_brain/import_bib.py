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
from .ingest.metadata import (
    MetadataClient,
    NetworkError,
    crossref_fields,
    datacite_fields,
    fill,
    flags_from_updates,
)
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
    pdf: str | None = None  # from the entry's ``file`` field (Zotero, Better BibTeX, JabRef)
    pdf_outcome: str | None = None  # what attaching it did: attached, relinked, duplicate, error


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


def entry_pdfs(entry: Any, base: Path) -> list[Path]:
    """Existing PDFs of the entry's ``file`` field: ``desc:path:type`` items (Zotero, JabRef)
    or bare paths (Better BibTeX), separated by ``;``; relative paths are from the .bib."""
    field = next((f for k, f in entry.fields_dict.items() if k.lower() == "file"), None)
    if field is None or not field.value:
        return []
    found = []
    for item in re.split(r"(?<!\\);", field.value):
        parts = re.split(r"(?<!\\):", item)
        raw = parts[1] if len(parts) == 3 else item  # a Windows drive ("C\:") is escaped
        raw = raw.replace("\\:", ":").replace("\\;", ";").replace("\\\\", "\\").strip()
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = base / candidate
        if candidate.suffix.lower() == ".pdf" and candidate.is_file() and candidate not in found:
            found.append(candidate)
    return found


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
    prefer_bib: bool = False,
    dry_run: bool = False,
    today: dt.date | None = None,
) -> list[ImportResult]:
    """Register the entries of ``path``. With a DOI, Crossref/DataCite fill the record (only
    with values they have); with ``prefer_bib`` the .bib's own fields win and Crossref only
    fills the gaps."""
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
            pdfs = entry_pdfs(entry, path.parent)
            result.pdf = str(pdfs[0]) if pdfs else None
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
                    found, service = (
                        (crossref_fields(message), "crossref") if message else (None, "")
                    )
                    if found is None and (attributes := client.datacite_work(doi)):
                        found, service = datacite_fields(attributes), "datacite"
                    if found is not None:
                        merged = fill(found, fields) if prefer_bib else fill(fields, found)
                        fields = {**merged, "tags": fields["tags"]}
                        source = f"bib+{service}" if prefer_bib else service
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
                    "flags": (["possible_duplicate"] if similar else [])
                    + flags_from_updates(fields.get("updates", [])),
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
    if not dry_run:
        attach_pdfs(lib, client, results)
    return results


def attach_pdfs(lib: Library, client: MetadataClient, results: list[ImportResult]) -> None:
    """Copy each entry's PDF into its record. A PDF whose first pages do not show the record's
    title is not attached: Zotero sometimes hangs a file on the wrong item."""
    from .config import load_config
    from .ingest.pipeline import IngestError, IngestOptions, Ingestor

    pending = [
        r
        for r in results
        if r.pdf and r.citekey and r.outcome != "error" and r.outcome != "conflict"
    ]
    if not pending:
        return
    ingestor = Ingestor(lib, load_config(lib.home), client, IngestOptions(strict_key=True))
    for result in pending:
        ingestor.options.key = result.citekey
        try:
            [done] = ingestor.run([Path(result.pdf)])
        except IngestError as exc:
            result.pdf_outcome, message = "error", str(exc)
        else:
            result.pdf_outcome, message = done.outcome, done.message
        result.message = "; ".join(m for m in (result.message, message) if m)
