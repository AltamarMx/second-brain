"""``sb edit``: fix a paper's metadata by hand (or from a DOI), and optionally its citekey.

Only the record changes: full text, summary, figures, projects and reading status
stay. Editing is a review, so a ``needs_review`` paper leaves that state.

``--rekey`` renames every file of the paper (record, full text, figures, supplements,
notes and local PDFs) and keeps the old citekey as an alias: ``sb bib`` still exports
it, so ``.tex`` documents that cite the old key keep working.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .bibtex import BIBLATEX_TYPES
from .citekey import make_citekey
from .ingest.doi import normalize_doi
from .ingest.metadata import (
    MetadataClient,
    crossref_fields,
    datacite_fields,
    fill,
    flags_from_updates,
)
from .library import InvalidDocument, Library
from .models import CITEKEY_PATTERN, Paper

REVIEW_FLAGS = {"doi_uncertain", "metadata_mismatch"}
EDITABLE = (
    "title", "authors", "year", "type", "container_title", "publisher", "volume", "issue",
    "pages", "doi",
)  # fmt: skip
FROM_DOI = (*EDITABLE, "ids", "abstract", "language", "license", "updates")


class EditError(ValueError):
    pass


@dataclass
class EditResult:
    citekey: str
    changed: list[str] = field(default_factory=list)
    reviewed: bool = False
    old_citekey: str | None = None
    renamed: list[tuple[str, str]] = field(default_factory=list)


def parse_author(text: str) -> dict[str, str | None]:
    """``"García, Ana"`` → family and given name; without a comma the whole text is the
    family name (an organization: ``"IPCC"``)."""
    family, _, given = (part.strip() for part in text.partition(","))
    if not family:
        raise EditError(f"autor inválido: {text!r} (usa 'Apellido, Nombre')")
    return {"family": family, "given": given or None}


def lookup_doi(client: MetadataClient, doi: str) -> tuple[dict[str, Any], str]:
    """Metadata of a DOI from Crossref, or DataCite."""
    if message := client.crossref_work(doi):
        return crossref_fields(message), "crossref"
    if attributes := client.datacite_work(doi):
        return datacite_fields(attributes), "datacite"
    raise EditError(f"el DOI {doi} no existe en Crossref ni DataCite")


def edit_paper(
    lib: Library,
    citekey: str,
    changes: dict[str, Any],
    *,
    doi_fields: dict[str, Any] | None = None,
    source: str = "manual",
    rekey: bool = False,
    new_key: str | None = None,
    accept: bool = False,
    dry_run: bool = False,
) -> EditResult:
    """Apply ``doi_fields`` and, with ``accept``, the suggestion of ``sb process`` (only their
    non-empty values), then ``changes``. A reviewed record loses its suggestion."""
    doc = lib.read_paper(citekey)
    paper = doc.meta
    others = [d.meta for d in lib.iter_papers() if not isinstance(d, InvalidDocument)]
    others = [p for p in others if p.citekey != citekey]
    if changes.get("type") is not None and changes["type"] not in BIBLATEX_TYPES:
        raise EditError(
            f"tipo desconocido: {changes['type']!r} (usa {', '.join(sorted(BIBLATEX_TYPES))})"
        )
    data = paper.model_dump()
    if doi_fields:
        data = fill(data, {k: v for k, v in doi_fields.items() if k in FROM_DOI})
    if accept:
        if paper.suggested is None:
            raise EditError(
                f"{citekey} no tiene metadatos sugeridos (sb process los propone para los "
                "registros sacados de un PDF sin DOI)"
            )
        suggestion = paper.suggested.model_dump()
        isbn = suggestion.pop("isbn")
        data = fill(data, {**suggestion, "ids": {"isbn": isbn}})
        source = "llm" if not changes and source == "manual" else source
    data.update(changes)
    if data.get("doi"):
        data["doi"] = normalize_doi(data["doi"])
        owner = [p.citekey for p in others if p.doi and normalize_doi(p.doi) == data["doi"]]
        if owner:
            raise EditError(f"el DOI {data['doi']} ya es de {owner[0]}")
    else:
        data["doi"] = None
    updated = Paper.model_validate(data)
    result = EditResult(citekey=citekey)
    result.changed = [k for k in EDITABLE if getattr(updated, k) != getattr(paper, k)]
    update: dict[str, Any] = {}
    if result.changed:
        update["provenance"] = paper.provenance.model_copy(update={"metadata_source": source})
    flags = set(paper.flags) | set(flags_from_updates(updated.updates))
    if paper.status == "needs_review":
        result.reviewed = True
        update["status"] = "processed" if paper.provenance.process else "needs_processing"
        flags -= REVIEW_FLAGS
    if result.reviewed or accept:
        update["suggested"] = None
    update["flags"] = sorted(flags)
    updated = updated.model_copy(update=update)

    target = citekey
    if new_key or rekey:
        taken = {p.citekey for p in others} | {a for p in others for a in p.aliases}
        if new_key:
            if not re.fullmatch(CITEKEY_PATTERN, new_key):
                raise EditError(f"citekey inválido: {new_key!r} (minúsculas, números y guiones)")
            if new_key in taken:
                raise EditError(f"el citekey {new_key} ya lo usa otro artículo")
            target = new_key
        else:
            family = updated.authors[0].family if updated.authors else None
            target = make_citekey(family, updated.year, updated.title, taken)
    if target != citekey:
        aliases = [a for a in (*updated.aliases, citekey) if a != target]
        updated = updated.model_copy(
            update={"citekey": target, "aliases": list(dict.fromkeys(aliases))}
        )
        result.old_citekey, result.citekey = citekey, target
        result.renamed = _rename_files(lib, citekey, target, updated, dry_run)
    if not dry_run and updated != paper:
        lib.write_paper(updated, doc.body)
        if target != citekey:
            doc.path.unlink()
    return result


def _rename_files(
    lib: Library, old: str, new: str, paper: Paper, dry_run: bool
) -> list[tuple[str, str]]:
    """Move every companion file of ``old`` to ``new`` (the record itself is written by the caller)."""
    moves: list[tuple[Path, Path]] = [(lib.paper_path(old), lib.paper_path(new))]
    if lib.fulltext_path(old).exists():
        moves.append((lib.fulltext_path(old), lib.fulltext_path(new)))
    if lib.figures_path(old).exists():
        moves.append((lib.figures_path(old), lib.figures_path(new)))
    for supplement in paper.supplements:
        if lib.supplement_path(old, supplement.id).exists():
            moves.append(
                (lib.supplement_path(old, supplement.id), lib.supplement_path(new, supplement.id))
            )
        if lib.supplement_pdf(old, supplement.id).exists():
            moves.append(
                (lib.supplement_pdf(old, supplement.id), lib.supplement_pdf(new, supplement.id))
            )
    for directory, suffix in ((lib.notes_dir, ".md"), (lib.pdfs_dir, ".pdf")):
        if (directory / f"{old}{suffix}").exists():
            moves.append((directory / f"{old}{suffix}", directory / f"{new}{suffix}"))
    for _, dest in moves[1:]:
        if dest.exists():
            raise EditError(f"ya existe {dest.relative_to(lib.home)}; no renombro nada")
    if not dry_run:
        for src, dest in moves[1:]:
            if src.parent == lib.fulltext_dir:
                fulltext = lib.read_fulltext(old)
                lib.write_fulltext(fulltext.meta.model_copy(update={"citekey": new}), fulltext.body)
                src.unlink()
            elif src.parent == lib.figures_dir:
                figures = lib.read_figure_set(old)
                lib.write_figure_set(figures.meta.model_copy(update={"citekey": new}), figures.body)
                src.unlink()
            elif src.parent == lib.supplements_dir:
                supplement_id = src.stem.rsplit("--", 1)[1]
                text = lib.read_supplement(old, supplement_id)
                lib.write_supplement(text.meta.model_copy(update={"citekey": new}), text.body)
                src.unlink()
            else:  # notes and local PDFs: plain files
                src.rename(dest)
    return [(str(s.relative_to(lib.home)), str(d.relative_to(lib.home))) for s, d in moves]
