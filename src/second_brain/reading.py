"""Read parts of a full text: pages (``<!-- page N -->``) and sections (headings)."""

from __future__ import annotations

import re

PAGE_RE = re.compile(r"^<!-- page (\d+) -->$", re.MULTILINE)
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$", re.MULTILINE)
# "2. Study methodology", "**1.** **Introduction**", "2.3 Survey"
NUMBERED_RE = re.compile(
    r"^(?:#{1,6}\s*)?(?:\*\*)?(?P<num>\d{1,2}(?:\.\d{1,2})*)\.?(?:\*\*)?\s+(?:\*\*)?"
    r"(?P<title>[A-Z][^\n]{2,80}?)(?:\*\*)?\s*$",
    re.MULTILINE,
)
KNOWN_RE = re.compile(
    r"^(?:\*\*)?(?P<title>abstract|resumen|introduc\w*|methods?|methodology|materials? and methods|"
    r"results?|discussion|conclusions?|conclusiones|references|referencias|bibliograf\w*|"
    r"acknowledge?ments?|agradecimientos)(?:\*\*)?\s*$",
    re.MULTILINE | re.IGNORECASE,
)


def split_pages(body: str) -> list[tuple[int, str]]:
    marks = list(PAGE_RE.finditer(body))
    pages = []
    for i, mark in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(body)
        pages.append((int(mark.group(1)), body[mark.end() : end].strip()))
    return pages


def parse_page_range(spec: str, last: int) -> tuple[int, int]:
    """``"5"`` → (5, 5); ``"4-6"`` → (4, 6); ``"8-"`` → (8, last)."""
    match = re.fullmatch(r"\s*(\d+)\s*(?:-\s*(\d*)\s*)?", spec)
    if not match:
        raise ValueError(f"rango de páginas inválido: {spec!r} (usa 5, 4-6 u 8-)")
    start = int(match.group(1))
    if match.group(2) is None:
        end = start
    elif match.group(2):
        end = int(match.group(2))
    else:
        end = last
    if start < 1 or end < start:
        raise ValueError(f"rango de páginas inválido: {spec!r}")
    return start, min(end, last)


def select_pages(body: str, spec: str) -> str:
    pages = split_pages(body)
    start, end = parse_page_range(spec, pages[-1][0] if pages else 0)
    return "\n\n".join(f"<!-- page {n} -->\n{text}" for n, text in pages if start <= n <= end)


def headings(body: str) -> list[tuple[int, int, str]]:
    """``(position, level, title)`` of Markdown headings and numbered or well-known section titles."""
    found: dict[int, tuple[int, int, str]] = {}
    for match in KNOWN_RE.finditer(body):
        found[match.start()] = (match.start(), 1, match.group("title"))
    for match in NUMBERED_RE.finditer(body):
        title = match.group("title").replace("**", "").strip()
        if not title.endswith("."):
            found[match.start()] = (match.start(), match.group("num").count(".") + 1, title)
    for match in HEADING_RE.finditer(body):
        found[match.start()] = (
            match.start(),
            len(match.group(1)),
            match.group(2).replace("**", ""),
        )
    return sorted(found.values())


def select_section(body: str, name: str) -> str | None:
    """From the first heading containing ``name`` to the next heading of equal or higher level."""
    wanted = name.lower()
    marks = headings(body)
    for i, (position, level, title) in enumerate(marks):
        if wanted in title.lower():
            end = next((p for p, lvl, _ in marks[i + 1 :] if lvl <= level), len(body))
            return body[position:end].strip()
    return None
