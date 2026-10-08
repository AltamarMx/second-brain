"""BibTeX / BibLaTeX generated deterministically from the records.

The LLM never writes entries. Output is sorted by citekey and stable, so a
regenerated ``.bib`` only changes when the records change.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Literal

from pylatexenc.latexencode import unicode_to_latex

from . import __version__
from .models import Paper

Format = Literal["bibtex", "biblatex"]

BIBTEX_TYPES = {
    "article-journal": "article",
    "article": "article",
    "paper-conference": "inproceedings",
    "chapter": "incollection",
    "book": "book",
    "thesis": "phdthesis",
    "report": "techreport",
    "preprint": "misc",
}
BIBLATEX_TYPES = {
    **BIBTEX_TYPES,
    "thesis": "thesis",
    "report": "report",
    "standard": "standard",
    "dataset": "dataset",
}
_SPECIAL = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}
_WORD_CORE = re.compile(r"[\w'’-]+", re.UNICODE)
_EDGES_RE = re.compile(r"^(\W*)(.*?)(\W*)$", re.DOTALL)


SUBSCRIPTS, SUPERSCRIPTS = "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾"
_SCRIPTS_RE = re.compile(f"([{SUBSCRIPTS}]+)|([{SUPERSCRIPTS}]+)")
_SCRIPT_TEXT = str.maketrans(SUBSCRIPTS + SUPERSCRIPTS, "0123456789+-=()" * 2)


def _encode_plain(text: str, fmt: Format) -> str:
    text = unicodedata.normalize("NFKC", text)  # 𝑪𝑶 → CO
    if fmt == "bibtex":
        return unicode_to_latex(text, unknown_char_policy="keep")
    return "".join(_SPECIAL.get(c, c) for c in text)


def encode(text: str, fmt: Format) -> str:
    """BibTeX: everything to LaTeX commands (``{\\'e}``); BibLaTeX: UTF-8, only specials escaped.
    In both, sub- and superscripts become ``\\textsubscript``/``\\textsuperscript`` (CO₂,
    m²): pdfLaTeX cannot typeset the Unicode ones."""
    text = re.sub(r"\s+", " ", text).strip()
    parts, position = [], 0
    for match in _SCRIPTS_RE.finditer(text):
        parts.append(_encode_plain(text[position : match.start()], fmt))
        command = "textsubscript" if match.group(1) else "textsuperscript"
        parts.append(f"\\{command}{{{match.group(0).translate(_SCRIPT_TEXT)}}}")
        position = match.end()
    parts.append(_encode_plain(text[position:], fmt))
    return "".join(parts)


def _is_sentence_case(words: list[str]) -> bool:
    # acronyms (CO2, ASHRAE, EnergyPlus) say nothing about the title's case style
    long_words = [
        w
        for w in words[1:]
        if len(w) > 3 and w[:1].isalpha() and not any(c.isupper() for c in w[1:])
    ]
    if not long_words:
        return True
    capitalized = sum(1 for w in long_words if w[:1].isupper())
    return capitalized / len(long_words) < 0.5


def _needs_protection(word: str, position: int, sentence_case: bool) -> bool:
    core = "".join(_WORD_CORE.findall(word))
    if not core:
        return False
    if any(c.isupper() for c in core[1:]):  # CO2, EnergyPlus, ASHRAE, BIM
        return True
    # In a sentence-case title a capitalized word after the first is a proper noun: México, Brazil
    return sentence_case and position > 0 and core[0].isupper()


def protect_title(title: str, fmt: Format) -> str:
    """Brace the words a bibliography style must not lowercase."""
    words = title.split()
    sentence_case = _is_sentence_case(words)
    out = []
    for position, word in enumerate(words):
        if not _needs_protection(word, position, sentence_case):
            out.append(encode(word, fmt))
            continue
        # brace the word, not the punctuation around it: {IoT}, and ({CO2})
        lead, core, trail = _EDGES_RE.match(word).groups()
        out.append(f"{encode(lead, fmt)}{{{encode(core, fmt)}}}{encode(trail, fmt)}")
    return " ".join(out)


def format_authors(paper: Paper, fmt: Format) -> str | None:
    names = []
    for author in paper.authors:
        family = encode(author.family, fmt)
        if author.given:
            names.append(f"{family}, {encode(author.given, fmt)}")
        elif len(author.family.split()) > 1:  # organization: keep it as one unit
            names.append(f"{{{family}}}")
        else:
            names.append(family)
    return " and ".join(names) or None


def _pages(pages: str | None) -> str | None:
    return re.sub(r"\s*[-–—]+\s*", "--", pages) if pages else None


def _thesis_type(paper: Paper, fmt: Format) -> str | None:
    """The ``type`` field of a thesis: BibLaTeX's localized keys, or the words for a bachelor's
    thesis (no entry type has them). A thesis without ``genre`` is exported as a PhD's."""
    if paper.genre == "bachelors":
        return (
            "Tesis de licenciatura"
            if (paper.language or "").startswith("es")
            else "Bachelor's thesis"
        )
    if fmt == "biblatex":
        return "mathesis" if paper.genre == "masters" else "phdthesis"
    return None


def entry(paper: Paper, fmt: Format = "bibtex", key: str | None = None) -> str:
    types = BIBTEX_TYPES if fmt == "bibtex" else BIBLATEX_TYPES
    kind = types.get(paper.type, "misc")
    container = encode(paper.container_title, fmt) if paper.container_title else None
    if paper.type == "article" and not container:  # generic CSL "article" (older preprints)
        kind = "misc"
    if kind == "phdthesis" and paper.genre in ("masters", "bachelors"):
        kind = "mastersthesis"  # BibTeX has no bachelor's type: @mastersthesis with a "type"
    fields: list[tuple[str, str | None]] = [
        ("author", format_authors(paper, fmt)),
        ("title", protect_title(paper.title, fmt)),
    ]
    if kind == "article":
        fields.append(("journal" if fmt == "bibtex" else "journaltitle", container))
    elif kind in ("inproceedings", "incollection"):
        fields.append(("booktitle", container))
    elif kind == "misc" and container:
        fields.append(("howpublished", container))  # a preprint's server: SSRN, arXiv…
    fields += [
        ("year", str(paper.year) if paper.year else None),
        ("volume", encode(paper.volume, fmt) if paper.volume else None),
        ("number", encode(paper.issue, fmt) if paper.issue else None),
        ("pages", _pages(paper.pages)),
    ]
    publisher = encode(paper.publisher, fmt) if paper.publisher else None
    if kind in ("phdthesis", "mastersthesis", "thesis"):
        fields.append(("school" if fmt == "bibtex" else "institution", publisher))
        fields.append(("type", _thesis_type(paper, fmt)))
    elif kind in ("techreport", "report"):
        fields.append(("institution", publisher))
        if fmt == "biblatex":
            fields.append(("type", "techreport"))
    elif kind != "article":
        fields.append(("publisher", publisher))
    if paper.type == "preprint":
        fields.append(("note", "Preprint"))
    fields += [("doi", paper.doi), ("isbn", paper.ids.isbn)]
    if not paper.authors:  # lets BibTeX sort entries without author
        fields.append(("key", paper.citekey))
    if paper.ids.arxiv and fmt == "biblatex":
        fields += [("eprint", paper.ids.arxiv), ("eprinttype", "arxiv")]
    body = ",\n".join(f"  {name} = {{{value}}}" for name, value in fields if value)
    return f"@{kind}{{{key or paper.citekey},\n{body}\n}}\n"


def render(
    papers: list[Paper], fmt: Format = "bibtex", keys: list[tuple[str, Paper]] | None = None
) -> str:
    """Entries for ``papers`` (each under its citekey and its aliases), or exactly ``keys``."""
    header = (
        f"% Generado por second-brain {__version__} ({fmt}). No lo edites a mano: "
        "se regenera con sb bib.\n"
    )
    if keys is None:
        keys = [(k, p) for p in papers for k in (p.citekey, *p.aliases)]
    unique = {key: paper for key, paper in keys}
    entries = []
    for key in sorted(unique, key=str.lower):
        paper = unique[key]
        note = f"% alias de {paper.citekey}\n" if key != paper.citekey else ""
        entries.append(note + entry(paper, fmt, key))
    return header + "".join(f"\n{e}" for e in entries)
