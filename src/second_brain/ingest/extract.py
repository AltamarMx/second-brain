"""PDF → per-page Markdown with PyMuPDF/pymupdf4llm, with OCR for scanned PDFs."""

from __future__ import annotations

import contextlib
import hashlib
import io
import subprocess
import unicodedata
from dataclasses import dataclass, field
from functools import cache
from importlib.metadata import version
from pathlib import Path

import pymupdf

with contextlib.redirect_stdout(io.StringIO()):  # it prints an advertisement on import
    import pymupdf4llm

pymupdf.TOOLS.mupdf_display_errors(False)

# A page with less text than this (and an image) is treated as scanned.
MIN_CHARS_PER_PAGE = 200
FRONT_PAGES = 2


class ExtractionError(RuntimeError):
    pass


@dataclass
class Extraction:
    pages: list[str]  # Markdown per page
    front_text: str  # plain text of the first pages, for DOI and title detection
    title_guess: str | None
    metadata_text: str  # PDF Info + XMP, where some publishers put the DOI
    ocr: bool
    warnings: list[str] = field(default_factory=list)

    @property
    def page_count(self) -> int:
        return len(self.pages)


def extractor_id() -> str:
    return f"pymupdf4llm {version('pymupdf4llm')} (PyMuPDF {version('pymupdf')})"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


@cache
def installed_ocr_languages() -> frozenset[str]:
    try:
        result = subprocess.run(
            ["tesseract", "--list-langs"], capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.SubprocessError):
        return frozenset()
    return frozenset(line.strip() for line in result.stdout.splitlines()[1:] if line.strip())


def _title_guess(page: pymupdf.Page, metadata_title: str | None) -> str | None:
    """Largest text in the top half of page 1; falls back to the PDF's title metadata."""
    spans = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                text = span["text"].strip()
                if len(text) > 2 and span["bbox"][1] < page.rect.height * 0.6:
                    spans.append((round(span["size"], 1), text))
    if spans:
        largest = max(size for size, _ in spans)
        title = unicodedata.normalize(
            "NFKC", " ".join(text for size, text in spans if size >= largest - 0.5)
        )
        if len(title) >= 15:
            return title[:400]
    if (
        metadata_title
        and len(metadata_title) >= 15
        and "microsoft word" not in metadata_title.lower()
    ):
        return metadata_title
    return None


def _ocr_pages(doc: pymupdf.Document, languages: list[str]) -> list[str]:
    available = installed_ocr_languages()
    usable = [lang for lang in languages if lang in available] or ["eng"]
    pages = []
    for page in doc:
        textpage = page.get_textpage_ocr(language="+".join(usable), dpi=300, full=True)
        pages.append(page.get_text(textpage=textpage))
    return pages


def extract(path: Path, ocr_languages: list[str] | None = None) -> Extraction:
    try:
        doc = pymupdf.open(path)
    except Exception as exc:
        raise ExtractionError(f"no se pudo abrir el PDF: {exc}") from exc
    with doc:
        if doc.needs_pass:
            raise ExtractionError("el PDF está protegido con contraseña")
        if doc.page_count == 0:
            raise ExtractionError("el PDF no tiene páginas")

        info = doc.metadata or {}
        metadata_text = (
            " ".join(str(v) for v in info.values() if v) + " " + (doc.get_xml_metadata() or "")
        )
        plain = [page.get_text() for page in doc]
        has_images = any(page.get_images() for page in doc)
        chars = sum(len(t.strip()) for t in plain)
        scanned = has_images and chars < MIN_CHARS_PER_PAGE * doc.page_count

        warnings: list[str] = []
        if scanned:
            if not installed_ocr_languages():
                raise ExtractionError("el PDF parece escaneado y Tesseract no está instalado")
            pages = _ocr_pages(doc, ocr_languages or ["eng"])
            plain = pages
        else:
            chunks = pymupdf4llm.to_markdown(doc, page_chunks=True, show_progress=False)
            pages = [chunk["text"] for chunk in chunks]
            if len(pages) != doc.page_count:
                raise ExtractionError(
                    f"el extractor devolvió {len(pages)} páginas de {doc.page_count}"
                )

        return Extraction(
            pages=pages,
            front_text="\n".join(plain[:FRONT_PAGES]),
            title_guess=_title_guess(doc[0], info.get("title")),
            metadata_text=metadata_text,
            ocr=scanned,
            warnings=warnings,
        )


def fulltext_body(pages: list[str]) -> str:
    return "\n\n".join(
        f"<!-- page {number} -->\n{text.strip()}" for number, text in enumerate(pages, start=1)
    )
