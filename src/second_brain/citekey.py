"""Citekeys: ``{first author's family name}{year}{first significant title word}``.

Lowercase ASCII only (``garcia2021thermal``). A citekey is assigned once and
never changes, because LaTeX documents depend on it.
"""

from __future__ import annotations

import re
import string

from .textutil import ascii_fold, strip_markup

STOPWORDS = {
    # English
    "a", "an", "and", "are", "as", "at", "by", "for", "from", "how", "in", "is", "of", "on",
    "or", "the", "to", "towards", "toward", "using", "via", "what", "when", "with", "why",
    # Spanish / Portuguese
    "al", "como", "con", "de", "del", "el", "en", "la", "las", "lo", "los", "para", "por",
    "sobre", "un", "una", "uno", "unos", "unas", "y", "e", "o", "da", "das", "do", "dos",
    "em", "no", "na", "nos", "nas", "um", "uma",
    # French / German / Italian
    "le", "les", "des", "du", "et", "der", "die", "und", "il",
}  # fmt: skip


def _slug_word(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", ascii_fold(text).lower())


def family_part(family: str | None) -> str:
    """``van der Berg`` → ``vanderberg``; ``García-López`` → ``garcialopez``."""
    return _slug_word(family or "") or "anon"


def title_word(title: str | None) -> str:
    words = re.split(r"[\s" + re.escape(string.punctuation) + "]+", strip_markup(title or ""))
    for word in words:
        slug = _slug_word(word)
        if len(slug) > 1 and slug not in STOPWORDS and not slug.isdigit():
            return slug
    return ""


def make_citekey(
    family: str | None, year: int | None, title: str | None, existing: set[str]
) -> str:
    base = f"{family_part(family)}{year or 'nd'}{title_word(title)}"
    if base not in existing:
        return base
    for suffix in string.ascii_lowercase[1:]:
        candidate = f"{base}-{suffix}"
        if candidate not in existing:
            return candidate
    raise ValueError(f"demasiados citekeys parecidos a {base}")
