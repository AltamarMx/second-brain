"""Search index: ``.cache/index.sqlite`` (SQLite FTS5), derived and outside git.

Papers (metadata, summary, keywords) and passages (full-text chunks with page
and section, plus figure descriptions) are indexed with BM25. The index is
updated incrementally from the files' size and modification time, and can be
rebuilt at any moment.
"""

from __future__ import annotations

import contextlib
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from .library import InvalidDocument, Library
from .models import Paper
from .processing import one_sentence
from .reading import KNOWN_RE, NUMBERED_RE, split_pages

INDEX_VERSION = "1"
CHUNK_WORDS = 350
TOKENIZER = "porter unicode61 remove_diacritics 2"
REFERENCES_RE = re.compile(r"^(references|referencias|bibliograf\w*)$", re.IGNORECASE)
STOP = {
    "a", "al", "and", "are", "as", "at", "by", "como", "con", "cual", "cuales", "de", "del", "el",
    "en", "es", "for", "from", "hay", "how", "in", "is", "la", "las", "lo", "los", "me", "mis",
    "of", "on", "or", "para", "por", "que", "qué", "se", "sobre", "su", "the", "tengo", "to",
    "un", "una", "what", "which", "with", "y",
}  # fmt: skip

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS files (citekey TEXT PRIMARY KEY, signature TEXT);
CREATE TABLE IF NOT EXISTS papers (
    citekey TEXT PRIMARY KEY, title TEXT, year INTEGER, status TEXT, study_type TEXT,
    container TEXT, authors TEXT, countries TEXT, regions TEXT, localities TEXT, projects TEXT,
    one_sentence TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS papers_fts USING fts5(
    citekey UNINDEXED, title, authors, abstract, summary, keywords, places, tokenize = '{TOKENIZER}'
);
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY, citekey TEXT, page_start INTEGER, page_end INTEGER,
    section TEXT, kind TEXT, text TEXT
);
CREATE INDEX IF NOT EXISTS chunks_citekey ON chunks (citekey);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    text, context, tokenize = '{TOKENIZER}'
);
"""


@dataclass(frozen=True)
class Filters:
    project: str | None = None
    study: str | None = None
    country: str | None = None
    region: str | None = None
    locality: str | None = None
    year_from: int | None = None
    year_to: int | None = None
    status: str | None = None

    @staticmethod
    def parse_years(spec: str | None) -> tuple[int | None, int | None]:
        """``2019`` → (2019, 2019); ``2015..2024``, ``2015..`` or ``..2020``."""
        if not spec:
            return None, None
        match = re.fullmatch(r"\s*(\d{4})?\s*(\.\.)?\s*(\d{4})?\s*", spec)
        if not match or not (match.group(1) or match.group(3)):
            raise ValueError(f"años inválidos: {spec!r} (usa 2019, 2015..2024, 2015.. o ..2020)")
        start, dots, end = match.groups()
        if not dots:
            return int(start), int(start)
        return (int(start) if start else None), (int(end) if end else None)


@dataclass
class Passage:
    citekey: str
    page_start: int
    page_end: int
    section: str
    kind: str
    text: str
    score: float


@dataclass
class Hit:
    citekey: str
    title: str
    year: int | None
    study_type: str | None
    places: str
    one_sentence: str | None
    score: float
    passages: list[Passage] = field(default_factory=list)


def fts_query(text: str) -> str:
    """Free text → FTS5 query. Terms are OR-ed (ranking does the rest); FTS syntax passes through."""
    if re.search(r'"|\b(AND|OR|NOT|NEAR)\b|\*', text):
        return text
    terms = [t for t in re.findall(r"\w+", text.lower()) if len(t) > 1 and t not in STOP]
    return " OR ".join(f'"{t}"' for t in terms)


def _signature(paths: list[Path]) -> str:
    parts = []
    for path in paths:
        stat = path.stat() if path.exists() else None
        parts.append(f"{stat.st_size}:{stat.st_mtime_ns}" if stat else "-")
    return "|".join(parts)


def _is_heading(line: str) -> bool:
    return len(line) < 120 and bool(
        NUMBERED_RE.match(line) or KNOWN_RE.match(line) or line.startswith("#")
    )


def chunk_fulltext(body: str, title: str) -> list[tuple[int, int, str, str, str]]:
    """``(page_start, page_end, section, kind, text)``; after the references heading, kind = refs.

    Chunks of ~CHUNK_WORDS words that never cross a section heading.
    """
    chunks = []
    section, kind = "", "text"
    lines: list[str] = []
    words = 0
    start_page = page = 1

    def flush() -> None:
        nonlocal lines, words, start_page
        text = "\n".join(lines).strip()
        if text:
            chunks.append((start_page, page, section, kind, re.sub(r"\n{3,}", "\n\n", text)))
        lines, words = [], 0
        start_page = page

    for page, text in split_pages(body):
        if not lines:
            start_page = page
        for raw in text.splitlines():
            line = raw.strip()
            if line and _is_heading(line):
                flush()
                section = re.sub(r"[#*_]+", "", line).strip()
                if REFERENCES_RE.match(re.sub(r"^\d+(\.\d+)*\.?\s*", "", section)):
                    kind = "refs"
            lines.append(line)
            words += len(line.split())
            if words >= CHUNK_WORDS and not line:  # cut at a paragraph boundary
                flush()
        if words >= CHUNK_WORDS * 1.5:
            flush()
    flush()
    return chunks


class SearchIndex:
    def __init__(self, lib: Library):
        self.lib = lib
        self.path = lib.cache_dir / "index.sqlite"

    def connect(self) -> sqlite3.Connection:
        self.lib.cache_dir.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        version = None
        with contextlib.suppress(sqlite3.OperationalError):
            version = db.execute("SELECT value FROM meta WHERE key = 'version'").fetchone()
        if version is None or version[0] != INDEX_VERSION:
            db.close()
            self.path.unlink(missing_ok=True)
            db = sqlite3.connect(self.path)
            db.row_factory = sqlite3.Row
            db.executescript(SCHEMA)
            db.execute("INSERT INTO meta VALUES ('version', ?)", (INDEX_VERSION,))
            db.commit()
        return db

    # --- building -------------------------------------------------------------

    def rebuild(self) -> int:
        self.path.unlink(missing_ok=True)
        return self.update()

    def update(self) -> int:
        """Re-index papers whose files changed; return how many were (re)indexed."""
        db = self.connect()
        known = {row["citekey"]: row["signature"] for row in db.execute("SELECT * FROM files")}
        present: set[str] = set()
        changed = 0
        for doc in self.lib.iter_papers():
            if isinstance(doc, InvalidDocument):
                continue
            key = doc.meta.citekey
            present.add(key)
            signature = _signature(
                [doc.path, self.lib.fulltext_path(key), self.lib.figures_path(key)]
            )
            if known.get(key) == signature:
                continue
            self._remove(db, key)
            self._add(db, doc.meta, doc.body)
            db.execute("INSERT OR REPLACE INTO files VALUES (?, ?)", (key, signature))
            changed += 1
        for key in set(known) - present:
            self._remove(db, key)
            db.execute("DELETE FROM files WHERE citekey = ?", (key,))
            changed += 1
        db.commit()
        db.close()
        return changed

    def _remove(self, db: sqlite3.Connection, key: str) -> None:
        db.execute("DELETE FROM papers WHERE citekey = ?", (key,))
        db.execute("DELETE FROM papers_fts WHERE citekey = ?", (key,))
        ids = [row[0] for row in db.execute("SELECT id FROM chunks WHERE citekey = ?", (key,))]
        db.executemany("DELETE FROM chunks_fts WHERE rowid = ?", [(i,) for i in ids])
        db.execute("DELETE FROM chunks WHERE citekey = ?", (key,))

    def _add(self, db: sqlite3.Connection, paper: Paper, summary: str) -> None:
        locations = paper.classification.locations
        places = " ".join(
            " ".join(filter(None, (loc.country, loc.region, loc.locality))) for loc in locations
        )
        db.execute(
            "INSERT INTO papers VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                paper.citekey, paper.title, paper.year, paper.status,
                paper.classification.study_type, paper.container_title,
                "; ".join(a.family for a in paper.authors),
                _joined(loc.country for loc in locations),
                _joined(loc.region for loc in locations),
                _joined(loc.locality for loc in locations),
                _joined(paper.projects),
                one_sentence(summary),
            ),
        )  # fmt: skip
        db.execute(
            "INSERT INTO papers_fts VALUES (?,?,?,?,?,?,?)",
            (
                paper.citekey, paper.title,
                " ".join(f"{a.given or ''} {a.family}" for a in paper.authors),
                paper.abstract or "", summary, " ".join(paper.keywords + paper.tags), places,
            ),
        )  # fmt: skip
        rows = []
        if self.lib.fulltext_path(paper.citekey).is_file():
            body = self.lib.read_fulltext(paper.citekey).body
            rows += chunk_fulltext(body, paper.title)
        if self.lib.figures_path(paper.citekey).is_file():
            figures = self.lib.read_figure_set(paper.citekey).body
            for match in re.finditer(
                r"^## (Fig\. \S+) \(p\. (\d+)\)\n(.*?)(?=^## |\Z)", figures, re.M | re.S
            ):
                page = int(match.group(2))
                rows.append((page, page, match.group(1), "figure", match.group(3).strip()))
        for page_start, page_end, section, kind, text in rows:
            cursor = db.execute(
                "INSERT INTO chunks (citekey, page_start, page_end, section, kind, text) VALUES (?,?,?,?,?,?)",
                (paper.citekey, page_start, page_end, section, kind, text),
            )
            db.execute(
                "INSERT INTO chunks_fts (rowid, text, context) VALUES (?, ?, ?)",
                (cursor.lastrowid, text, f"{paper.title} | {section}"),
            )

    # --- queries ----------------------------------------------------------------

    def _where(self, filters: Filters, alias: str = "p") -> tuple[str, list]:
        clauses, params = [], []
        if filters.project:
            clauses.append(f"(' ' || {alias}.projects || ' ') LIKE ?")
            params.append(f"% {filters.project} %")
        for column, value in (
            ("study_type", filters.study),
            ("status", filters.status),
        ):
            if value:
                clauses.append(f"{alias}.{column} = ?")
                params.append(value)
        for column, value in (
            ("countries", filters.country.upper() if filters.country else None),
            ("regions", filters.region),
            ("localities", filters.locality),
        ):
            if value:
                clauses.append(f"{alias}.{column} LIKE ?")
                params.append(f"%{value}%")
        if filters.year_from:
            clauses.append(f"{alias}.year >= ?")
            params.append(filters.year_from)
        if filters.year_to:
            clauses.append(f"{alias}.year <= ?")
            params.append(filters.year_to)
        return (" AND ".join(clauses) or "1"), params

    def list(self, filters: Filters) -> list[Hit]:
        self.update()
        db = self.connect()
        where, params = self._where(filters)
        rows = db.execute(
            f"SELECT * FROM papers p WHERE {where} ORDER BY year DESC, citekey", params
        )
        hits = [_hit(row, 0.0) for row in rows]
        db.close()
        return hits

    def passages(
        self, query: str, filters: Filters, paper: str | None = None, limit: int = 8,
        include_refs: bool = False,
    ) -> list[Passage]:  # fmt: skip
        self.update()
        match = fts_query(query)
        if not match:
            return []
        db = self.connect()
        where, params = self._where(filters)
        extra = ""
        if paper:
            extra += " AND c.citekey = ?"
            params.append(paper)
        if not include_refs:
            extra += " AND c.kind != 'refs'"
        sql = f"""
            SELECT c.*, bm25(chunks_fts) AS score FROM chunks_fts
            JOIN chunks c ON c.id = chunks_fts.rowid
            JOIN papers p ON p.citekey = c.citekey
            WHERE chunks_fts MATCH ? AND {where}{extra}
            ORDER BY score LIMIT ?
        """
        rows = db.execute(sql, [match, *params, limit]).fetchall()
        db.close()
        return [
            Passage(
                r["citekey"],
                r["page_start"],
                r["page_end"],
                r["section"],
                r["kind"],
                r["text"],
                r["score"],
            )
            for r in rows
        ]

    def search(self, query: str, filters: Filters, limit: int = 10) -> list[Hit]:
        """Papers ranked by Reciprocal Rank Fusion of paper-level and passage-level BM25."""
        self.update()
        match = fts_query(query)
        if not match:
            return self.list(filters)[:limit]
        db = self.connect()
        where, params = self._where(filters)
        paper_rows = db.execute(
            f"""SELECT p.*, bm25(papers_fts, 0, 10, 3, 2, 3, 4, 2) AS score FROM papers_fts
                JOIN papers p ON p.citekey = papers_fts.citekey
                WHERE papers_fts MATCH ? AND {where} ORDER BY score LIMIT 50""",
            [match, *params],
        ).fetchall()
        db.close()
        passages = self.passages(query, filters, limit=200)
        fused: dict[str, float] = {}
        for rank, row in enumerate(paper_rows):
            fused[row["citekey"]] = fused.get(row["citekey"], 0) + 1 / (60 + rank)
        by_paper: dict[str, list[Passage]] = {}
        for passage in passages:
            by_paper.setdefault(passage.citekey, []).append(passage)
        for rank, key in enumerate(by_paper):
            fused[key] = fused.get(key, 0) + 1 / (60 + rank)
        db = self.connect()
        hits = []
        for key, score in sorted(fused.items(), key=lambda kv: -kv[1])[:limit]:
            row = db.execute("SELECT * FROM papers WHERE citekey = ?", (key,)).fetchone()
            hit = _hit(row, score)
            hit.passages = by_paper.get(key, [])[:2]
            hits.append(hit)
        db.close()
        return hits


def _joined(values) -> str:
    return " ".join(sorted({v for v in values if v}))


def _hit(row: sqlite3.Row, score: float) -> Hit:
    places = ", ".join(filter(None, (row["localities"], row["regions"], row["countries"])))
    return Hit(
        row["citekey"],
        row["title"],
        row["year"],
        row["study_type"],
        places,
        row["one_sentence"],
        score,
    )
