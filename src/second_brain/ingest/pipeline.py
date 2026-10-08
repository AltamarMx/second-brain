"""``sb ingest``: PDFs → records in ``library/`` and files in ``pdfs/``.

Each step is idempotent. Writing order is full text → record → move PDF, so a
crash at any point is repaired by running the ingestion again (the PDF is then
recognised by its hash and re-linked).
"""

from __future__ import annotations

import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from rapidfuzz import fuzz

from ..citekey import make_citekey
from ..config import LibraryConfig
from ..fetch.download import FetchedPdf, Fetcher, FetchFailure
from ..library import Library
from ..models import FullText, Paper, PdfInfo, PdfSource, Provenance
from ..projects import ProjectError, require_project
from ..textutil import normalize_for_match
from .dedupe import LibraryIndex
from .doi import doi_variants, find_arxiv, find_dois, normalize_doi
from .extract import Extraction, ExtractionError, extract, extractor_id, fulltext_body, sha256_file
from .metadata import (
    MetadataClient,
    NetworkError,
    crossref_fields,
    crossref_relations,
    datacite_fields,
    flags_from_updates,
)

Outcome = Literal[
    "ingested", "review", "attached", "relinked", "awaiting", "duplicate", "error", "offline"
]  # fmt: skip
TITLE_ON_PAGE = 90
YEAR_RE = re.compile(r"(?<!\d)(19|20)\d{2}(?!\d)")
MAX_DOI_CANDIDATES = 8
ERRORS_DIR = "_errores"
DUPLICATES_DIR = "_duplicados"


class IngestError(RuntimeError):
    pass


class LockedError(RuntimeError):
    pass


@dataclass
class IngestResult:
    source: str
    outcome: Outcome
    citekey: str | None = None
    doi: str | None = None
    status: str | None = None
    flags: list[str] = field(default_factory=list)
    message: str = ""


@dataclass
class IngestOptions:
    dry_run: bool = False
    forced_doi: str | None = None
    project: str | None = None
    today: dt.date = field(default_factory=dt.date.today)


@dataclass
class Resolved:
    fields: dict[str, Any]
    source: str
    validated: bool
    flags: list[str] = field(default_factory=list)
    relations: list[str] = field(default_factory=list)
    note: str = ""


def first_year(text: str, today: dt.date | None = None) -> int | None:
    """First plausible publication year in the text (for records without DOI)."""
    last = (today or dt.date.today()).year + 1
    for match in YEAR_RE.finditer(text):
        if 1900 <= int(match.group(0)) <= last:
            return int(match.group(0))
    return None


def title_on_page(title: str, page_text: str) -> bool:
    norm_title = normalize_for_match(title)
    if len(norm_title) < 8:
        return norm_title in page_text
    return fuzz.partial_ratio(norm_title, page_text) >= TITLE_ON_PAGE


@contextmanager
def ingest_lock(lib: Library) -> Iterator[None]:
    lib.cache_dir.mkdir(parents=True, exist_ok=True)
    with (lib.cache_dir / "ingest.lock").open("w") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise LockedError("ya hay otra ingesta en curso en esta biblioteca") from exc
        yield


def _move_verified(src: Path, dest: Path, sha256: str, keep_source: bool = False) -> None:
    """Copy, verify the hash, then delete the original (unless ``keep_source``). Never loses the PDF."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        if sha256_file(dest) != sha256:
            raise IngestError(f"{dest.name} ya existe con otro contenido")
    else:
        tmp = dest.with_name(f".{dest.name}.tmp")
        shutil.copy2(src, tmp)
        if sha256_file(tmp) != sha256:
            tmp.unlink()
            raise IngestError("la copia del PDF no coincide con el original")
        os.replace(tmp, dest)
    if not keep_source:
        src.unlink()


def store_pdf(lib: Library, src: Path, dest: Path, sha256: str) -> None:
    """Put a PDF in ``pdfs/``: moved if it came from ``inbox/``, copied from anywhere else, so
    files that belong to other programs (a Zotero attachment…) are never deleted."""
    from_inbox = src.resolve().is_relative_to(lib.inbox_dir.resolve())
    _move_verified(src, dest, sha256, keep_source=not from_inbox)


def _unique_destination(directory: Path, name: str) -> Path:
    candidate = directory / name
    stem, suffix = Path(name).stem, Path(name).suffix
    counter = 2
    while candidate.exists():
        candidate = directory / f"{stem}-{counter}{suffix}"
        counter += 1
    return candidate


class Ingestor:
    def __init__(
        self,
        lib: Library,
        config: LibraryConfig,
        client: MetadataClient,
        options: IngestOptions | None = None,
        fetcher: Fetcher | None = None,
    ):
        self.lib = lib
        self.config = config
        self.client = client
        self.options = options or IngestOptions()
        self.fetcher = fetcher
        self.index = LibraryIndex.build(lib)

    # --- entry point ----------------------------------------------------------

    def run(self, paths: list[Path], dois: list[str] | None = None) -> list[IngestResult]:
        project = self.options.project
        if project:
            try:
                require_project(self.lib, project)
            except ProjectError as exc:
                raise IngestError(str(exc)) from exc
        if self.options.forced_doi and (len(paths) != 1 or dois):
            raise IngestError("--doi solo se puede usar con un único PDF")
        with ingest_lock(self.lib):
            results = [self.ingest_one(path) for path in paths]
            results += [self.ingest_doi(doi) for doi in dois or []]
            return results

    def pending_dois(self, only_awaiting: bool = True) -> list[str]:
        """DOIs whose PDF is missing: awaiting ones, or also those absent from this machine."""
        dois = []
        for citekey, paper in sorted(self.index.papers.items()):
            if not paper.doi:
                continue
            missing_here = not (self.lib.pdfs_dir / f"{citekey}.pdf").exists()
            if paper.status == "awaiting_pdf" or (not only_awaiting and missing_here):
                dois.append(paper.doi)
        return dois

    def ingest_one(
        self, path: Path, expected_doi: str | None = None, source: PdfSource = "inbox"
    ) -> IngestResult:
        result = IngestResult(source=path.name, outcome="error")
        try:
            return self._ingest(path, result, expected_doi, source)
        except NetworkError as exc:
            result.outcome = "offline"
            result.message = f"{exc}. El PDF se queda en su lugar; reintenta con conexión."
        except (IngestError, ExtractionError) as exc:
            result.message = str(exc)
            self._set_aside(path, ERRORS_DIR, result.message)
        except Exception as exc:  # unexpected: keep the PDF safe and report
            result.message = f"error inesperado: {type(exc).__name__}: {exc}"
            self._set_aside(path, ERRORS_DIR, result.message)
        return result

    # --- steps ------------------------------------------------------------------

    def _ingest(
        self, path: Path, result: IngestResult, expected_doi: str | None, source: PdfSource
    ) -> IngestResult:
        sha = sha256_file(path)
        existing = self.index.find_by_sha(sha)
        if existing:
            return self._known_file(path, existing, result)
        if sha in self.index.by_supplement_sha:
            citekey, supplement_id = self.index.by_supplement_sha[sha]
            result.citekey = citekey
            local = self.lib.supplement_pdf(citekey, supplement_id)
            if local.exists():
                result.outcome, result.message = (
                    "duplicate",
                    f"es el suplemento {supplement_id} de {citekey}",
                )
                self._set_aside(path, DUPLICATES_DIR)
            else:
                result.outcome, result.message = (
                    "relinked",
                    f"suplemento {supplement_id} de {citekey} re-vinculado",
                )
                if not self.options.dry_run:
                    store_pdf(self.lib, path, local, sha)
            return result

        extraction = extract(path, ocr_languages=self.config.extract.ocr_languages)
        resolved = self._resolve(extraction, expected_doi)
        doi = resolved.fields.get("doi")
        result.doi = doi

        if doi and (match := self.index.find_by_doi(doi)):
            return self._known_doi(path, match, sha, extraction, result, source)

        family = (resolved.fields.get("authors") or [{}])[0].get("family")
        similar = self._similar(resolved, family)
        if similar and self.index.papers[similar].pdf is None:
            # a record without PDF (from sb import bib or a DOI) with the same title: attach to it
            return self._known_doi(path, similar, sha, extraction, result, source)

        flags = list(resolved.flags) + flags_from_updates(resolved.fields.get("updates", []))
        if extraction.ocr:
            flags.append("ocr")
        if similar:
            flags.append("possible_duplicate")
        citekey = make_citekey(
            family,
            resolved.fields.get("year"),
            resolved.fields.get("title"),
            set(self.index.papers),
        )

        body = fulltext_body(extraction.pages)
        status = "needs_processing" if resolved.validated else "needs_review"
        paper = Paper.model_validate(
            {
                **resolved.fields,
                "citekey": citekey,
                "ids": {
                    **resolved.fields.get("ids", {}),
                    "arxiv": find_arxiv(extraction.front_text),
                },
                "projects": self._membership(),
                "pdf": self._pdf_info(path, sha, extraction, source),
                "status": status,
                "flags": sorted(set(flags)),
                "added": self.options.today,
                "provenance": Provenance(
                    metadata_source=resolved.source,
                    extractor=extractor_id(),
                    fulltext_sha256=hashlib.sha256(body.encode()).hexdigest(),
                ),
            }
        )
        fulltext = FullText(
            citekey=citekey,
            source_pdf_sha256=sha,
            extractor=extractor_id(),
            extracted=self.options.today,
            pages=extraction.page_count,
            ocr=extraction.ocr,
        )
        if not self.options.dry_run:
            self.lib.write_fulltext(fulltext, body)
            self.lib.write_paper(paper)
            store_pdf(self.lib, path, self.lib.pdfs_dir / f"{citekey}.pdf", sha)
        self.index.add(paper)

        result.outcome = "ingested" if status == "needs_processing" else "review"
        result.citekey, result.status, result.flags = citekey, status, paper.flags
        notes = [resolved.note] if resolved.note else []
        if similar:
            notes.append(f"parecido a {similar}")
        result.message = "; ".join(notes)
        return result

    def _lookup(self, doi: str) -> tuple[dict[str, Any], str, list[str]] | None:
        message = self.client.crossref_work(doi)
        if message:
            return crossref_fields(message), "crossref", crossref_relations(message)
        attributes = self.client.datacite_work(doi)
        if attributes:
            return datacite_fields(attributes), "datacite", []
        return None

    def _resolve(self, extraction: Extraction, expected_doi: str | None = None) -> Resolved:
        page_text = normalize_for_match(extraction.front_text)[:8000]

        forced = self.options.forced_doi or expected_doi
        if forced:
            found = self._lookup(normalize_doi(forced))
            if not found:
                raise IngestError(f"el DOI {forced} no existe en Crossref ni DataCite")
            fields, source, relations = found
            ok = title_on_page(fields["title"], page_text)
            if not self.options.forced_doi:  # a downloaded PDF must show its title
                return Resolved(
                    fields, source, validated=ok, relations=relations,
                    flags=[] if ok else ["metadata_mismatch"],
                    note="" if ok else "el PDF descargado no muestra el título del DOI; revísalo",
                )  # fmt: skip
            return Resolved(
                fields, source, validated=True, relations=relations,
                flags=[] if ok else ["metadata_mismatch"],
                note="" if ok else "DOI indicado a mano; el título no aparece en la página 1",
            )  # fmt: skip

        candidates = find_dois(extraction.metadata_text) + find_dois(extraction.front_text)
        arxiv = find_arxiv(extraction.front_text)
        if arxiv:
            candidates.append(f"10.48550/arXiv.{arxiv}")
        unvalidated: tuple[dict[str, Any], str, list[str]] | None = None
        tried: set[str] = set()
        for raw in candidates:
            if len(tried) >= MAX_DOI_CANDIDATES:
                break
            for doi in doi_variants(raw):
                if doi in tried:
                    continue
                tried.add(doi)
                found = self._lookup(doi)
                if not found:
                    continue
                if title_on_page(found[0]["title"], page_text):
                    return Resolved(found[0], found[1], validated=True, relations=found[2])
                unvalidated = unvalidated or found
                break  # this candidate resolved; shorter variants would be another work

        if unvalidated:
            return Resolved(
                unvalidated[0], unvalidated[1], validated=False, relations=unvalidated[2],
                flags=["doi_uncertain"],
                note="el título del DOI encontrado no aparece en la página 1",
            )  # fmt: skip

        guess = extraction.title_guess
        if guess:
            for item in self.client.crossref_search(guess):
                fields = crossref_fields(item)
                close = fuzz.token_set_ratio(
                    normalize_for_match(fields["title"]), normalize_for_match(guess)
                )
                if close >= TITLE_ON_PAGE and title_on_page(fields["title"], page_text):
                    return Resolved(
                        fields, "crossref", validated=False, relations=crossref_relations(item),
                        flags=["doi_uncertain"], note="DOI encontrado buscando el título; confírmalo",
                    )  # fmt: skip

        return Resolved(
            {"title": guess or "(sin título)", "year": first_year(extraction.front_text)},
            "pdf",
            validated=False,
            note="sin DOI: título y año aproximados tomados del PDF",
        )

    def _similar(self, resolved: Resolved, family: str | None) -> str | None:
        for doi in resolved.relations:
            if match := self.index.find_by_doi(doi):
                return match
        return self.index.find_similar(
            resolved.fields.get("title", ""), resolved.fields.get("year"), family
        )

    def _membership(self) -> dict[str, dict[str, Any]]:
        if not self.options.project:
            return {}
        return {self.options.project: {"added": self.options.today}}

    def _pdf_info(
        self, path: Path, sha: str, extraction: Extraction, source: PdfSource = "inbox"
    ) -> PdfInfo:
        return PdfInfo(
            sha256=sha,
            pages=extraction.page_count,
            size_bytes=path.stat().st_size,
            source=source,
            original_filename=path.name,
        )

    # --- files already known ---------------------------------------------------

    def _known_file(self, path: Path, citekey: str, result: IngestResult) -> IngestResult:
        """The exact PDF of a record: a duplicate, or the original coming back to ``pdfs/``."""
        paper = self.index.papers[citekey]
        sha = paper.pdf.sha256
        result.citekey, result.doi = citekey, paper.doi
        local = self.lib.pdfs_dir / f"{citekey}.pdf"
        if local.exists() and sha256_file(local) == sha:
            result.outcome = "duplicate"
            result.message = f"es el mismo archivo que {citekey}"
            self._set_aside(path, DUPLICATES_DIR)
            return result
        result.outcome = "relinked"
        result.message = f"PDF de {citekey} re-vinculado"
        aside = None
        if local.exists():  # another version stood in for it (pdf_version_mismatch)
            aside = _unique_destination(
                self.lib.inbox_dir / DUPLICATES_DIR, f"{citekey}-otra-version.pdf"
            )
            result.message = (
                f"el original de {citekey} reemplaza a la otra versión, que queda en "
                f"{aside.relative_to(self.lib.home)}"
            )
        updated = paper.model_copy(
            update={"flags": [f for f in paper.flags if f != "pdf_version_mismatch"]}
        )
        if not self.options.dry_run:
            if aside:
                aside.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(local, aside)
            store_pdf(self.lib, path, local, sha)
            if updated.flags != paper.flags:
                self.lib.write_paper(updated, self.lib.read_paper(citekey).body)
        self.index.add(updated)
        return result

    def _known_doi(
        self,
        path: Path,
        citekey: str,
        sha: str,
        extraction: Extraction,
        result: IngestResult,
        source: PdfSource = "inbox",
    ) -> IngestResult:
        paper = self.index.papers[citekey]
        result.citekey = citekey
        local = self.lib.pdfs_dir / f"{citekey}.pdf"
        if paper.pdf is None:
            body = fulltext_body(extraction.pages)
            updated = paper.model_copy(
                update={
                    "pdf": self._pdf_info(path, sha, extraction, source),
                    "status": "needs_processing"
                    if paper.status == "awaiting_pdf"
                    else paper.status,
                    "provenance": paper.provenance.model_copy(
                        update={
                            "extractor": extractor_id(),
                            "fulltext_sha256": hashlib.sha256(body.encode()).hexdigest(),
                        }
                    ),
                }
            )
            if not self.options.dry_run:
                self.lib.write_fulltext(
                    FullText(
                        citekey=citekey, source_pdf_sha256=sha, extractor=extractor_id(),
                        extracted=self.options.today, pages=extraction.page_count, ocr=extraction.ocr,
                    ),
                    body,
                )  # fmt: skip
                self.lib.write_paper(updated, self.lib.read_paper(citekey).body)
                store_pdf(self.lib, path, local, sha)
            self.index.add(updated)
            result.outcome, result.message = "attached", f"PDF añadido a {citekey}"
        elif not local.exists():
            flags = sorted({*paper.flags, "pdf_version_mismatch"})
            updated = paper.model_copy(update={"flags": flags})
            if not self.options.dry_run:
                self.lib.write_paper(updated, self.lib.read_paper(citekey).body)
                store_pdf(self.lib, path, local, sha)
            self.index.add(updated)
            result.outcome = "relinked"
            result.message = (
                f"otra versión del PDF de {citekey}; las páginas citadas son las del original"
            )
        else:
            result.outcome = "duplicate"
            result.message = f"mismo DOI que {citekey}"
            self._set_aside(path, DUPLICATES_DIR)
        return result

    def _set_aside(self, path: Path, folder: str, reason: str | None = None) -> None:
        """Move a duplicate or failed PDF out of the way (only if it came from inbox/)."""
        if self.options.dry_run or not path.exists() or path.parent != self.lib.inbox_dir:
            return
        target = _unique_destination(self.lib.inbox_dir / folder, path.name)
        target.parent.mkdir(parents=True, exist_ok=True)
        path.rename(target)
        if reason:
            target.with_suffix(".motivo.txt").write_text(reason + "\n", encoding="utf-8")

    # --- by DOI -------------------------------------------------------------------

    def ingest_doi(self, raw: str) -> IngestResult:
        doi = normalize_doi(raw)
        result = IngestResult(source=doi, outcome="error", doi=doi)
        try:
            existing = self.index.find_by_doi(doi)
            if existing:
                result.citekey = existing
                paper = self.index.papers[existing]
                if paper.pdf is not None and (self.lib.pdfs_dir / f"{existing}.pdf").exists():
                    result.outcome = "duplicate"
                    result.message = f"ya está en la biblioteca como {existing}"
                    return result
                return self._download_into(
                    doi, self.client.crossref_work(doi), paper.ids.arxiv, result
                )
            found = self._lookup(doi)
            if not found:
                raise IngestError(f"el DOI {doi} no existe en Crossref ni DataCite")
            fields, source, relations = found
            outcome = self._download_into(doi, self.client.crossref_work(doi), None, result)
            if outcome.outcome == "awaiting":
                self._register_awaiting(fields, source, relations, outcome)
            return outcome
        except NetworkError as exc:
            result.outcome = "offline"
            result.message = f"{exc}. Reintenta con conexión."
        except IngestError as exc:
            result.message = str(exc)
        return result

    def _download_into(
        self, doi: str, crossref: dict[str, Any] | None, arxiv: str | None, result: IngestResult
    ) -> IngestResult:
        if self.fetcher is None:
            raise IngestError("la descarga de PDFs no está disponible")
        if self.options.dry_run:
            result.outcome, result.status = "awaiting", "awaiting_pdf"
            result.message = "(simulación) se intentaría descargar el PDF"
            return result
        dest = self.lib.inbox_dir / f"doi-{re.sub(r'[^a-z0-9.-]+', '_', doi)}.pdf"
        try:
            fetched: FetchedPdf = self.fetcher.fetch(doi, dest, crossref=crossref, arxiv=arxiv)
        except FetchFailure as failure:
            if failure.reason == "offline":
                raise NetworkError(str(failure)) from failure
            self._log_fetch(doi, failure.reason, str(failure))
            result.outcome, result.status = "awaiting", "awaiting_pdf"
            result.message = f"sin PDF: {failure}"
            return result
        self._log_fetch(doi, None, None)
        ingested = self.ingest_one(fetched.path, expected_doi=doi, source=fetched.source)
        ingested.source = doi
        via = {"openaccess": "acceso abierto", "institutional": "acceso institucional"}[
            fetched.source
        ]
        ingested.message = "; ".join(
            m for m in (f"PDF por {via} ({fetched.via})", ingested.message) if m
        )
        return ingested

    def _register_awaiting(
        self, fields: dict[str, Any], source: str, relations: list[str], result: IngestResult
    ) -> None:
        family = (fields.get("authors") or [{}])[0].get("family")
        resolved = Resolved(fields, source, validated=True, relations=relations)
        similar = self._similar(resolved, family)
        citekey = make_citekey(
            family, fields.get("year"), fields.get("title"), set(self.index.papers)
        )
        paper = Paper.model_validate(
            {
                **fields,
                "citekey": citekey,
                "projects": self._membership(),
                "status": "awaiting_pdf",
                "flags": (["possible_duplicate"] if similar else [])
                + flags_from_updates(fields.get("updates", [])),
                "added": self.options.today,
                "provenance": Provenance(metadata_source=source),
            }
        )
        if not self.options.dry_run:
            self.lib.write_paper(paper)
        self.index.add(paper)
        result.citekey = citekey
        if similar:
            result.message += f"; parecido a {similar}"

    def _log_fetch(self, doi: str, reason: str | None, message: str | None) -> None:
        """Last failed download per DOI, in ``.cache/fetch.json`` (local, for ``sb pdf status``)."""
        path = self.lib.cache_dir / "fetch.json"
        log = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        if reason is None:
            log.pop(doi, None)
        else:
            log[doi] = {
                "date": self.options.today.isoformat(),
                "reason": reason,
                "message": message,
            }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
