"""Citekeys cited in a LaTeX document, following ``\\input`` and ``\\include``."""

from __future__ import annotations

import re
from pathlib import Path

# \cite, \citep, \citet*, \parencite, \textcite, \autocite, \citeauthor, \footcite, \nocite…
CITE_RE = re.compile(r"\\(?:[A-Za-z]*cite[A-Za-z]*|nocite)\*?\s*(?:\[[^\]]*\]\s*){0,2}\{([^}]*)\}")
INPUT_RE = re.compile(r"\\(?:input|include|subfile)\s*\{([^}]+)\}")
COMMENT_RE = re.compile(r"(?<!\\)%.*$", re.MULTILINE)


def cited_keys(tex: Path) -> list[str]:
    """Keys in order of first citation; ``\\nocite{*}`` is ignored."""
    keys: list[str] = []
    seen_files: set[Path] = set()

    def visit(path: Path) -> None:
        path = path.resolve()
        if path in seen_files or not path.is_file():
            return
        seen_files.add(path)
        text = COMMENT_RE.sub("", path.read_text(encoding="utf-8", errors="replace"))
        events = sorted(
            [(m.start(), "cite", m.group(1)) for m in CITE_RE.finditer(text)]
            + [(m.start(), "input", m.group(1)) for m in INPUT_RE.finditer(text)]
        )
        for _, kind, value in events:
            if kind == "input":
                child = path.parent / value.strip()
                visit(child if child.suffix == ".tex" else child.with_name(child.name + ".tex"))
                continue
            for key in value.split(","):
                key = key.strip()
                if key and key != "*" and key not in keys:
                    keys.append(key)

    visit(tex)
    return keys
