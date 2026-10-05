"""BibTeX / BibLaTeX generated deterministically from the records.

The LLM never writes entries. Output is sorted by citekey and stable, so a
regenerated ``.bib`` only changes when the records change.
"""

from __future__ import annotations

import re
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


def encode(text: str, fmt: Format) -> str:
    """BibTeX: everything to LaTeX commands (``{\\'e}``); BibLaTeX: UTF-8, only specials escaped."""
    text = re.sub(r"\s+", " ", text).strip()
    if fmt == "bibtex":
        return unicode_to_latex(text, unknown_char_policy="keep")
    return "".join(_SPECIAL.get(c, c) for c in text)


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
        encoded = encode(word, fmt)
        out.append(
            f"{{{encoded}}}" if _needs_protection(word, position, sentence_case) else encoded
        )
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


def entry(paper: Paper, fmt: Format = "bibtex") -> str:
    types = BIBTEX_TYPES if fmt == "bibtex" else BIBLATEX_TYPES
    kind = types.get(paper.type, "misc")
    container = encode(paper.container_title, fmt) if paper.container_title else None
    fields: list[tuple[str, str | None]] = [
        ("author", format_authors(paper, fmt)),
        ("title", protect_title(paper.title, fmt)),
    ]
    if kind == "article":
        fields.append(("journal" if fmt == "bibtex" else "journaltitle", container))
    elif kind in ("inproceedings", "incollection"):
        fields.append(("booktitle", container))
    elif kind == "misc" and container:
        fields.append(("howpublished", container))
    fields += [
        ("year", str(paper.year) if paper.year else None),
        ("volume", encode(paper.volume, fmt) if paper.volume else None),
        ("number", encode(paper.issue, fmt) if paper.issue else None),
        ("pages", _pages(paper.pages)),
    ]
    publisher = encode(paper.publisher, fmt) if paper.publisher else None
    if kind in ("phdthesis", "thesis"):
        fields.append(("school" if fmt == "bibtex" else "institution", publisher))
        if fmt == "biblatex":
            fields.append(("type", "phdthesis"))
    elif kind in ("techreport", "report"):
        fields.append(("institution", publisher))
        if fmt == "biblatex":
            fields.append(("type", "techreport"))
    elif kind != "article":
        fields.append(("publisher", publisher))
    fields += [("doi", paper.doi), ("isbn", paper.ids.isbn)]
    if not paper.authors:  # lets BibTeX sort entries without author
        fields.append(("key", paper.citekey))
    if paper.ids.arxiv and fmt == "biblatex":
        fields += [("eprint", paper.ids.arxiv), ("eprinttype", "arxiv")]
    body = ",\n".join(f"  {name} = {{{value}}}" for name, value in fields if value)
    return f"@{kind}{{{paper.citekey},\n{body}\n}}\n"


def render(papers: list[Paper], fmt: Format = "bibtex") -> str:
    header = (
        f"% Generado por second-brain {__version__} ({fmt}). No lo edites a mano: "
        "se regenera con sb bib.\n"
    )
    entries = [entry(p, fmt) for p in sorted(papers, key=lambda p: p.citekey)]
    return header + "".join(f"\n{e}" for e in entries)
