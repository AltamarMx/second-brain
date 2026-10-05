"""Small text helpers shared by ingestion, deduplication and citekeys."""

from __future__ import annotations

import html
import re
import unicodedata

_EXTRA_ASCII = str.maketrans(
    {"ß": "ss", "ø": "o", "Ø": "O", "ł": "l", "Ł": "L", "æ": "ae", "Æ": "AE", "đ": "d", "Đ": "D"}
)
_BLOCK_TAG_RE = re.compile(r"</?(?:[a-z]+:)?(?:p|title|sec|br|div|li|list-item)\b[^>]*>", re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")


def ascii_fold(text: str) -> str:
    """``Pérez`` → ``Perez``, ``Müller`` → ``Muller``, ``ﬁ`` → ``fi``."""
    text = unicodedata.normalize("NFKD", text.translate(_EXTRA_ASCII))
    return text.encode("ascii", "ignore").decode("ascii")


def strip_markup(text: str) -> str:
    """Remove HTML/JATS tags and entities that Crossref puts in titles and abstracts."""
    text = _TAG_RE.sub("", _BLOCK_TAG_RE.sub(" ", text))
    return _SPACE_RE.sub(" ", html.unescape(text)).strip()


def normalize_for_match(text: str) -> str:
    """Lowercase ASCII words separated by single spaces, for fuzzy comparisons."""
    text = re.sub(r"(?<=[a-z])-\s*\n\s*(?=[a-z])", "", text)  # words hyphenated across lines
    text = ascii_fold(strip_markup(text)).lower()
    return _SPACE_RE.sub(" ", re.sub(r"[^a-z0-9]+", " ", text)).strip()
