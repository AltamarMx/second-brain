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
from typing import Literal

import numpy as np

from .embeddings import Embedder, EmbeddingError
from .library import InvalidDocument, Library
from .models import Paper
from .processing import one_sentence
from .reading import KNOWN_RE, NUMBERED_RE, split_pages

INDEX_VERSION = "3"  # 2: vectors; 3: reading, rating, extra fields, supplements
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
    one_sentence TEXT, reading TEXT, rating INTEGER, extra TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS papers_fts USING fts5(
    citekey UNINDEXED, title, authors, abstract, summary, keywords, places, tokenize = '{TOKENIZER}'
);
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY, citekey TEXT, page_start INTEGER, page_end INTEGER,
    section TEXT, kind TEXT, text TEXT
);
CREATE INDEX IF NOT EXISTS chunks_citekey ON chunks (citekey);
CREATE TABLE IF NOT EXISTS vectors (chunk_id INTEGER PRIMARY KEY, vec BLOB);
CREATE TABLE IF NOT EXISTS paper_vectors (citekey TEXT PRIMARY KEY, vec BLOB);
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
    reading: str | None = None
    extra: tuple[str, ...] = ()  # "field=value" pairs from config.toml [classification.*]

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


Mode = Literal["lexical", "semantic", "hybrid"]
RRF_K = 60
# Weight of each ranked list in hybrid search (paper-level and passage-level, lexical and semantic)
WEIGHTS = {
    "lexical_paper": 1.0,
    "semantic_paper": 1.0,
    "lexical_chunks": 0.7,
    "semantic_chunks": 0.7,
}


def _rrf(rankings: list[list], weights: list[float] | None = None) -> dict:
    """Reciprocal Rank Fusion of several ranked lists of keys."""
    fused: dict = {}
    for ranking, weight in zip(rankings, weights or [1.0] * len(rankings), strict=True):
        for rank, key in enumerate(ranking):
            fused[key] = fused.get(key, 0.0) + weight / (RRF_K + rank)
    return fused


class SearchIndex:
    def __init__(self, lib: Library, embedder: Embedder | None = None):
        self.lib = lib
        self.path = lib.cache_dir / "index.sqlite"
        self.embedder = embedder
        self.warning: str | None = None
        self._cache: dict[str, tuple[list, np.ndarray]] = {}

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

    @property
    def semantic(self) -> bool:
        return self.embedder is not None

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
        if self.embedder is not None:
            try:
                self._embed_missing(db)
            except EmbeddingError as exc:
                self.warning = f"{exc}; búsqueda solo por palabras"
                self.embedder = None
        db.commit()
        db.close()
        return changed

    def _remove(self, db: sqlite3.Connection, key: str) -> None:
        db.execute("DELETE FROM papers WHERE citekey = ?", (key,))
        db.execute("DELETE FROM papers_fts WHERE citekey = ?", (key,))
        db.execute("DELETE FROM paper_vectors WHERE citekey = ?", (key,))
        ids = [row[0] for row in db.execute("SELECT id FROM chunks WHERE citekey = ?", (key,))]
        db.executemany("DELETE FROM chunks_fts WHERE rowid = ?", [(i,) for i in ids])
        db.executemany("DELETE FROM vectors WHERE chunk_id = ?", [(i,) for i in ids])
        db.execute("DELETE FROM chunks WHERE citekey = ?", (key,))
        self._cache.clear()

    def _embed_missing(self, db: sqlite3.Connection) -> None:
        stored = db.execute("SELECT value FROM meta WHERE key = 'embedder'").fetchone()
        if stored is None or stored[0] != self.embedder.id:  # other model: start over
            db.execute("DELETE FROM vectors")
            db.execute("DELETE FROM paper_vectors")
            db.execute("INSERT OR REPLACE INTO meta VALUES ('embedder', ?)", (self.embedder.id,))
        chunks = db.execute(
            """SELECT c.id, c.text, c.section, p.title FROM chunks c JOIN papers p ON p.citekey = c.citekey
               LEFT JOIN vectors v ON v.chunk_id = c.id WHERE v.chunk_id IS NULL AND c.kind != 'refs'"""
        ).fetchall()
        if chunks:
            texts = [f"{r['title']} | {r['section']}\n{r['text']}" for r in chunks]
            vectors = self.embedder.embed(texts)
            db.executemany(
                "INSERT INTO vectors VALUES (?, ?)",
                [
                    (r["id"], v.astype(np.float32).tobytes())
                    for r, v in zip(chunks, vectors, strict=True)
                ],
            )
        papers = db.execute(
            """SELECT f.citekey, f.title, f.abstract, f.summary, f.keywords FROM papers_fts f
               LEFT JOIN paper_vectors v ON v.citekey = f.citekey WHERE v.citekey IS NULL"""
        ).fetchall()
        if papers:
            texts = [
                f"{r['title']}\n{r['keywords']}\n{(r['summary'] or '')[:2000]}\n{(r['abstract'] or '')[:1500]}"
                for r in papers
            ]
            vectors = self.embedder.embed(texts)
            db.executemany(
                "INSERT INTO paper_vectors VALUES (?, ?)",
                [
                    (r["citekey"], v.astype(np.float32).tobytes())
                    for r, v in zip(papers, vectors, strict=True)
                ],
            )
        if chunks or papers:
            self._cache.clear()

    def _add(self, db: sqlite3.Connection, paper: Paper, summary: str) -> None:
        locations = paper.classification.locations
        places = " ".join(
            " ".join(filter(None, (loc.country, loc.region, loc.locality))) for loc in locations
        )
        db.execute(
            "INSERT INTO papers VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                paper.citekey, paper.title, paper.year, paper.status,
                paper.classification.study_type, paper.container_title,
                "; ".join(a.family for a in paper.authors),
                _joined(loc.country for loc in locations),
                _joined(loc.region for loc in locations),
                _joined(loc.locality for loc in locations),
                _joined(paper.projects),
                one_sentence(summary), paper.reading, paper.rating, _extra_tokens(paper),
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
        for supplement in paper.supplements:
            path = self.lib.supplement_path(paper.citekey, supplement.id)
            if not path.is_file():
                continue
            label = f"Suplemento {supplement.id}" + (
                f": {supplement.label}" if supplement.label else ""
            )
            for start, end, section, kind, text in chunk_fulltext(
                self.lib.read_supplement(paper.citekey, supplement.id).body, label
            ):
                if kind != "refs":
                    rows.append(
                        (start, end, f"{label} · {section}".strip(" ·"), "supplement", text)
                    )
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
        for pair in filters.extra:
            clauses.append(f"(' ' || {alias}.extra || ' ') LIKE ?")
            params.append(f"% {pair.strip().lower()} %")
        for column, value in (("study_type", filters.study), ("status", filters.status)):
            if value:
                clauses.append(f"{alias}.{column} = ?")
                params.append(value)
        if filters.reading:  # a paper nobody marked is still to be read
            unmarked = f" OR {alias}.reading IS NULL" if filters.reading == "por-leer" else ""
            clauses.append(f"({alias}.reading = ?{unmarked})")
            params.append(filters.reading)
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

    def _allowed(self, db: sqlite3.Connection, filters: Filters) -> set[str]:
        where, params = self._where(filters)
        return {r[0] for r in db.execute(f"SELECT citekey FROM papers p WHERE {where}", params)}

    def _matrix(self, db: sqlite3.Connection, table: str) -> tuple[list, np.ndarray]:
        if table not in self._cache:
            if table == "vectors":
                rows = db.execute(
                    "SELECT v.chunk_id, c.citekey, v.vec FROM vectors v JOIN chunks c ON c.id = v.chunk_id"
                ).fetchall()
                keys = [(r[0], r[1]) for r in rows]
            else:
                rows = db.execute("SELECT citekey, citekey, vec FROM paper_vectors").fetchall()
                keys = [r[0] for r in rows]
            matrix = (
                np.vstack([np.frombuffer(r[2], dtype=np.float32) for r in rows])
                if rows
                else np.zeros((0, 1))
            )
            self._cache[table] = (keys, matrix)
        return self._cache[table]

    def _semantic_chunks(
        self, db, query_vec, allowed: set[str], paper: str | None, limit: int
    ) -> list[int]:
        keys, matrix = self._matrix(db, "vectors")
        if not keys:
            return []
        scores = matrix @ query_vec
        ranked = []
        for index in np.argsort(-scores):
            chunk_id, citekey = keys[index]
            if citekey in allowed and (paper is None or citekey == paper):
                ranked.append(chunk_id)
                if len(ranked) >= limit:
                    break
        return ranked

    def _semantic_papers(self, db, query_vec, allowed: set[str], limit: int) -> list[str]:
        keys, matrix = self._matrix(db, "paper_vectors")
        if not keys:
            return []
        scores = matrix @ query_vec
        return [keys[i] for i in np.argsort(-scores) if keys[i] in allowed][:limit]

    def _query_vector(self, query: str) -> np.ndarray | None:
        if self.embedder is None:
            return None
        try:
            return self.embedder.embed([query])[0]
        except EmbeddingError as exc:
            self.warning = f"{exc}; búsqueda solo por palabras"
            self.embedder = None
            return None

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

    def _lexical_chunks(self, db, query, filters, paper, limit, include_refs) -> list[int]:
        match = fts_query(query)
        if not match:
            return []
        where, params = self._where(filters)
        extra = ""
        if paper:
            extra += " AND c.citekey = ?"
            params.append(paper)
        if not include_refs:
            extra += " AND c.kind != 'refs'"
        sql = f"""
            SELECT c.id FROM chunks_fts
            JOIN chunks c ON c.id = chunks_fts.rowid
            JOIN papers p ON p.citekey = c.citekey
            WHERE chunks_fts MATCH ? AND {where}{extra}
            ORDER BY bm25(chunks_fts) LIMIT ?
        """
        return [r[0] for r in db.execute(sql, [match, *params, limit])]

    def _chunk_rankings(
        self, db, query, filters, paper, limit, include_refs, mode
    ) -> list[tuple[str, list[int]]]:
        rankings = []
        if mode in ("lexical", "hybrid") or not self.semantic:
            lexical = self._lexical_chunks(db, query, filters, paper, limit, include_refs)
            rankings.append(("lexical_chunks", lexical))
        if mode in ("semantic", "hybrid") and self.semantic:
            vector = self._query_vector(query)
            if vector is not None:
                allowed = self._allowed(db, filters)
                semantic = self._semantic_chunks(db, vector, allowed, paper, limit)
                rankings.append(("semantic_chunks", semantic))
        return rankings

    def passages(
        self, query: str, filters: Filters, paper: str | None = None, limit: int = 8,
        include_refs: bool = False, mode: Mode = "hybrid",
    ) -> list[Passage]:  # fmt: skip
        self.update()
        db = self.connect()
        rankings = self._chunk_rankings(
            db, query, filters, paper, max(limit * 4, 40), include_refs, mode
        )
        fused = _rrf(
            [ranking for _, ranking in rankings], [WEIGHTS[label] for label, _ in rankings]
        )
        ordered = sorted(fused, key=lambda k: -fused[k])[:limit]
        rows = {r["id"]: r for r in db.execute(
            f"SELECT * FROM chunks WHERE id IN ({','.join('?' * len(ordered))})", ordered
        )} if ordered else {}  # fmt: skip
        db.close()
        return [
            Passage(
                r["citekey"],
                r["page_start"],
                r["page_end"],
                r["section"],
                r["kind"],
                r["text"],
                fused[i],
            )
            for i in ordered
            if (r := rows.get(i)) is not None
        ]

    def search(
        self, query: str, filters: Filters, limit: int = 10, mode: Mode = "hybrid"
    ) -> list[Hit]:
        """Papers ranked by RRF of paper-level and passage-level BM25 and, if enabled, vectors."""
        self.update()
        match = fts_query(query)
        if not match and not self.semantic:
            return self.list(filters)[:limit]
        db = self.connect()
        rankings: list[list[str]] = []
        weights: list[float] = []
        if match and (mode in ("lexical", "hybrid") or not self.semantic):
            where, params = self._where(filters)
            rankings.append([r[0] for r in db.execute(
                f"""SELECT p.citekey FROM papers_fts JOIN papers p ON p.citekey = papers_fts.citekey
                    WHERE papers_fts MATCH ? AND {where}
                    ORDER BY bm25(papers_fts, 0, 10, 3, 2, 3, 4, 2) LIMIT 50""",
                [match, *params],
            )])  # fmt: skip
            weights.append(WEIGHTS["lexical_paper"])
        vector = self._query_vector(query) if mode in ("semantic", "hybrid") else None
        if vector is not None:
            rankings.append(self._semantic_papers(db, vector, self._allowed(db, filters), 50))
            weights.append(WEIGHTS["semantic_paper"])
        chunk_rankings = self._chunk_rankings(db, query, filters, None, 200, False, mode)
        chunk_owner = {}
        if any(ranking for _, ranking in chunk_rankings):
            ids = sorted({i for _, ranking in chunk_rankings for i in ranking})
            chunk_owner = dict(db.execute(
                f"SELECT id, citekey FROM chunks WHERE id IN ({','.join('?' * len(ids))})", ids
            ).fetchall())  # fmt: skip
        for label, ranking in chunk_rankings:
            per_paper: list[str] = []
            for chunk_id in ranking:
                owner = chunk_owner.get(chunk_id)
                if owner and owner not in per_paper:
                    per_paper.append(owner)
            rankings.append(per_paper)
            weights.append(WEIGHTS[label])
        fused = _rrf(rankings, weights)
        hits = []
        for key in sorted(fused, key=lambda k: -fused[k])[:limit]:
            row = db.execute("SELECT * FROM papers WHERE citekey = ?", (key,)).fetchone()
            hits.append(_hit(row, fused[key]))
        db.close()
        for hit in hits:
            hit.passages = self.passages(query, filters, paper=hit.citekey, limit=2, mode=mode)
        return hits


def _extra_tokens(paper: Paper) -> str:
    """``clima=aw edificacion=vivienda edificacion=oficinas`` (lowercase), for LIKE filters."""
    tokens = []
    for name, value in paper.classification.extra.items():
        for item in value if isinstance(value, list) else [value] if value else []:
            tokens.append(f"{name}={item}".lower().replace(" ", "_"))
    return " ".join(tokens)


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


def open_index(lib: Library, semantic: bool = True) -> SearchIndex:
    """The index with the active machine profile's embedder (lexical only if disabled or failing)."""
    from .embeddings import get_embedder
    from .machines import detect_machine_name, load_profile

    embedder = None
    warning = None
    if semantic:
        try:
            embedder = get_embedder(load_profile(lib.home, detect_machine_name()))
        except EmbeddingError as exc:
            warning = str(exc)
    index = SearchIndex(lib, embedder)
    index.warning = warning
    return index
