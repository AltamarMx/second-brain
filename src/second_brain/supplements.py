"""``sb attach``: supplementary material (extra PDFs) for a paper.

The text goes to ``library/supplements/{citekey}--sN.md`` (in git, searchable);
the PDF to ``pdfs/{citekey}--sN.pdf`` (local, like the paper's PDF).
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from .config import LibraryConfig
from .ingest.extract import extract, extractor_id, fulltext_body, sha256_file
from .ingest.pipeline import _move_verified
from .library import Library
from .models import Supplement, SupplementText


class SupplementError(ValueError):
    pass


def attach(
    lib: Library,
    config: LibraryConfig,
    citekey: str,
    pdf: Path,
    label: str | None = None,
    today: dt.date | None = None,
) -> Supplement:
    if not lib.paper_path(citekey).is_file():
        raise SupplementError(f"no existe el artículo {citekey}")
    doc = lib.read_paper(citekey)
    paper = doc.meta
    sha = sha256_file(pdf)
    if paper.pdf and paper.pdf.sha256 == sha:
        raise SupplementError("ese PDF es el artículo mismo, no un suplemento")
    for existing in paper.supplements:
        if existing.sha256 == sha:
            raise SupplementError(f"ese PDF ya es el suplemento {existing.id} de {citekey}")
    extraction = extract(pdf, ocr_languages=config.extract.ocr_languages)
    number = max((int(s.id[1:]) for s in paper.supplements), default=0) + 1
    supplement = Supplement(
        id=f"s{number}",
        label=label,
        sha256=sha,
        pages=extraction.page_count,
        size_bytes=pdf.stat().st_size,
        original_filename=pdf.name,
    )
    text = SupplementText(
        citekey=citekey,
        id=supplement.id,
        label=label,
        source_pdf_sha256=sha,
        extractor=extractor_id(),
        extracted=today or dt.date.today(),
        pages=extraction.page_count,
        ocr=extraction.ocr,
    )
    lib.write_supplement(text, fulltext_body(extraction.pages))
    lib.write_paper(
        paper.model_copy(update={"supplements": [*paper.supplements, supplement]}), doc.body
    )
    _move_verified(pdf, lib.supplement_pdf(citekey, supplement.id), sha)
    return supplement
