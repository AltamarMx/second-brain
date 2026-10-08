"""PDF → per-page Markdown with PyMuPDF/pymupdf4llm, with OCR for scanned PDFs."""

from __future__ import annotations

import contextlib
import hashlib
import io
import re
import subprocess
import unicodedata
from dataclasses import dataclass, field
from functools import cache
from importlib.metadata import version
from pathlib import Path

import pymupdf
from rapidfuzz import fuzz

from ..textutil import normalize_for_match

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


# Text on a cover that is never the title.
NOTICE_RE = re.compile(
    r"preprint|peer[- ]?review|manuscript|pre-?proof|article in press|electronic copy|"
    r"downloaded from|contents lists available|available online|all rights reserved|"
    r"creative commons|open access|research article|original (?:article|paper)|"
    r"artículo (?:original|de investigación)|\bissn\b|\bisbn\b",
    re.IGNORECASE,
)
INSTITUTION_RE = re.compile(
    r"^(?:universidad|university|instituto|institute|facultad|faculty|escuela|school|college|"
    r"departamento|department|centro|center|centre|posgrado|programa|colegio|secretar[ií]a|"
    r"ministry|ministerio|consejo)\b",
    re.IGNORECASE,
)
# Where a thesis cover stops being the title.
THESIS_CUT_RE = re.compile(
    r"\s+(?:a dissertation|a thesis|dissertation (?:presented|submitted)|"
    r"thesis (?:presented|submitted)|tesis que|tesis para|que para obtener|para obtener el|"
    r"presented by|submitted by|presentad[ao] por|elaborad[ao] por)\b.*$",
    re.IGNORECASE,
)
# "… by DIANA ANDREA BRITO": "by"/"por" followed only by a name (not "by night ventilation").
BYLINE_RE = re.compile(r"\s+(?:by|por)\s+((?:[A-ZÁÉÍÓÚÑ][\w.'-]*\s*){1,6})$")
FILENAME_RE = re.compile(
    r"\.(?:docx?|pdf|tex|indd|rtf|odt)$|microsoft word|^untitled|^document\d*$", re.I
)
TITLE_PAGES = 3


def _lines(page: pymupdf.Page) -> list[tuple[float, str]]:
    """``(font size, text)`` of each line in the top three quarters of a page, in reading
    order. Spans of one line are joined, so a subscript stays with its word."""
    lines = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            spans = [s for s in line["spans"] if s["text"].strip()]
            if not spans or line["bbox"][1] > page.rect.height * 0.75:
                continue
            text = " ".join("".join(s["text"] for s in spans).split())
            lines.append((round(max(s["size"] for s in spans), 1), text))
    return lines


def _is_institution(text: str) -> bool:
    """ "UNIVERSIDAD AUTÓNOMA…", "Universidad Autónoma de…", "Centro de Investigación…", but not
    a title that starts with one of those words ("Centro histórico de Mérida…")."""
    match = INSTITUTION_RE.match(text)
    if not match:
        return False
    rest = text[match.end() :].split()
    if text.isupper() or (rest and rest[0][:1].isupper()):
        return True
    return len(rest) > 1 and rest[0].lower() in ("de", "del", "of", "for") and rest[1][:1].isupper()


def _clean_title(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = THESIS_CUT_RE.sub("", text)
    return BYLINE_RE.sub("", text).strip(" .,:;-")


def _layout_title(page: pymupdf.Page) -> str | None:
    """The first block of lines in the largest type, skipping notices and institution names."""
    lines = [
        (size, text)
        for size, text in _lines(page)
        if len(text) > 2 and not NOTICE_RE.search(text) and not _is_institution(text)
    ]
    if not lines:
        return None
    largest = max(size for size, _ in lines)
    group: list[str] = []
    for size, text in lines:
        if size >= largest - 0.5:
            group.append(text)
        elif group:
            break
    title = _clean_title(" ".join(group))
    return title[:400] if len(title) >= 8 and len(title.split()) >= 2 else None


def _title_guess(doc: pymupdf.Document, metadata_title: str | None, front_text: str) -> str | None:
    """Title of a PDF without DOI: the PDF's title metadata when it is a real title that
    the first pages show, else the largest type of the first pages, else the metadata."""
    metadata_title = " ".join((metadata_title or "").split())
    reasonable = len(metadata_title.split()) >= 3 and not FILENAME_RE.search(metadata_title)
    if reasonable:
        shown = fuzz.partial_ratio(
            normalize_for_match(metadata_title), normalize_for_match(front_text)
        )
        if shown >= 90:
            return metadata_title[:400]
    for page in list(doc)[:TITLE_PAGES]:
        if title := _layout_title(page):
            return title
    return metadata_title[:400] if reasonable else None


BFCHAR_RE = re.compile(rb"<([0-9A-Fa-f]+)>(\s*)<([0-9A-Fa-f]+)>")
MATH_ALNUM_RE = re.compile("[\U0001d400-\U0001d7ff]")


def _math_alphabet(cp: int) -> range | None:
    """The alphabet (A–Z, a–z or 0–9 of one style) of a mathematical alphanumeric symbol."""
    if 0x1D400 <= cp <= 0x1D6A3:  # 13 styles × (26 capitals + 26 small letters)
        start = cp - (cp - 0x1D400) % 26
        return range(start, start + 26)
    if 0x1D7CE <= cp <= 0x1D7FF:  # 5 styles × 10 digits
        start = cp - (cp - 0x1D7CE) % 10
        return range(start, start + 10)
    return None


def _first_use(doc: pymupdf.Document, font: str) -> dict[int, int]:
    """Glyph id → order of its first appearance in the document, for one font."""
    order: dict[int, int] = {}
    for page in doc:
        for span in page.get_texttrace():
            if span["font"] == font:
                for char in span["chars"]:
                    order.setdefault(char[1], len(order))
    return order


def repair_math_tounicode(doc: pymupdf.Document) -> int:
    """Word writes equations (CO₂ typed as math) with a broken ToUnicode map: every glyph
    maps to its character twice, and the glyphs of a run share one character (C and O →
    "𝑪𝑪𝑪𝑪"). Fix the map in memory: undouble it and, where glyphs collide, infer each one's
    character from its glyph-id distance to the glyph that is mapped right (the first one
    used), since math alphabets are contiguous in the font. Returns the fonts repaired."""
    repaired, seen = 0, set()
    for page in doc:
        for xref, _ext, kind, basefont, *_ in page.get_fonts(full=True):
            if xref in seen or kind != "Type0":
                continue
            seen.add(xref)
            match = re.search(r"/ToUnicode (\d+) 0 R", doc.xref_object(xref))
            if not match:
                continue
            cmap_xref = int(match.group(1))
            cmap = doc.xref_stream(cmap_xref) or b""
            mapped: dict[int, str] = {}
            for gid, _, value in BFCHAR_RE.findall(cmap):
                mapped[int(gid, 16)] = bytes.fromhex(value.decode()).decode("utf-16-be", "ignore")
            fixed: dict[int, str] = {}
            for gid, text in mapped.items():
                if len(text) == 2 and text[0] == text[1] and _math_alphabet(ord(text[0])):
                    fixed[gid] = text[0]
            groups: dict[str, list[int]] = {}
            for gid in fixed:
                groups.setdefault(fixed[gid], []).append(gid)
            order: dict[int, int] | None = None
            for char, gids in groups.items():
                if len(gids) < 2:
                    continue
                alphabet = _math_alphabet(ord(char))
                valid = [r for r in gids if all(ord(char) + g - r in alphabet for g in gids)]
                if len(valid) > 1:
                    if order is None:
                        order = _first_use(doc, basefont.split("+")[-1])
                    valid = sorted(valid, key=lambda g: order.get(g, len(order)))[:1]
                if len(valid) == 1:
                    for gid in gids:
                        fixed[gid] = chr(ord(char) + gid - valid[0])
            if not fixed:
                continue

            def rewrite(m: re.Match[bytes], fixed: dict[int, str] = fixed) -> bytes:
                text = fixed.get(int(m.group(1), 16))
                if text is None:
                    return m.group(0)
                return b"<%s>%s<%s>" % (
                    m.group(1),
                    m.group(2),
                    text.encode("utf-16-be").hex().upper().encode(),
                )

            doc.update_stream(cmap_xref, BFCHAR_RE.sub(rewrite, cmap))
            repaired += 1
    return repaired


def plain_math(text: str) -> str:
    """Mathematical letters and digits (𝑪𝑶𝟐) as plain ones (CO2), for search and titles."""
    return MATH_ALNUM_RE.sub(lambda m: unicodedata.normalize("NFKC", m.group(0)), text)


def _ocr_pages(doc: pymupdf.Document, languages: list[str]) -> list[str]:
    available = installed_ocr_languages()
    usable = [lang for lang in languages if lang in available] or ["eng"]
    pages = []
    for page in doc:
        textpage = page.get_textpage_ocr(language="+".join(usable), dpi=300, full=True)
        pages.append(page.get_text(textpage=textpage))
    return pages


def _open(path: Path) -> pymupdf.Document:
    try:
        doc = pymupdf.open(path)
    except Exception as exc:
        raise ExtractionError(f"no se pudo abrir el PDF: {exc}") from exc
    if doc.needs_pass or not doc.page_count:
        return doc
    try:
        repaired = repair_math_tounicode(doc)
    except Exception:  # an odd font table must never stop the extraction
        repaired = 0
    if not repaired:
        return doc
    fixed = pymupdf.open(stream=doc.tobytes(), filetype="pdf")  # MuPDF caches the old map
    doc.close()
    return fixed


def extract(path: Path, ocr_languages: list[str] | None = None) -> Extraction:
    doc = _open(path)
    with doc:
        if doc.needs_pass:
            raise ExtractionError("el PDF está protegido con contraseña")
        if doc.page_count == 0:
            raise ExtractionError("el PDF no tiene páginas")

        info = doc.metadata or {}
        metadata_text = (
            " ".join(str(v) for v in info.values() if v) + " " + (doc.get_xml_metadata() or "")
        )
        plain = [plain_math(page.get_text()) for page in doc]
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
            pages = [plain_math(chunk["text"]) for chunk in chunks]
            if len(pages) != doc.page_count:
                raise ExtractionError(
                    f"el extractor devolvió {len(pages)} páginas de {doc.page_count}"
                )

        return Extraction(
            pages=pages,
            front_text="\n".join(plain[:FRONT_PAGES]),
            title_guess=_title_guess(doc, info.get("title"), "\n".join(plain[:TITLE_PAGES])),
            metadata_text=metadata_text,
            ocr=scanned,
            warnings=warnings,
        )


def fulltext_body(pages: list[str]) -> str:
    return "\n\n".join(
        f"<!-- page {number} -->\n{text.strip()}" for number, text in enumerate(pages, start=1)
    )
