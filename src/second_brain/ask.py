"""``sb ask``: a one-off question answered from the library (retrieval + a minimal prompt).

The fastest way to query with a local model on a CPU-only machine: it only
sends the most relevant summaries and passages, never whole papers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .backends import Backend
from .index import Filters, Passage, SearchIndex
from .library import Library

MAX_PAPERS = 5
MAX_PASSAGES = 10
PASSAGE_CHARS = 1200

PROMPT = """Responde la pregunta del usuario usando ÚNICAMENTE el material de la biblioteca que viene abajo
(resúmenes y pasajes de artículos). Responde en {language}.

Reglas:
- Cada afirmación lleva su cita con el formato [citekey, p. N], copiando citekey y página del material.
- Si el material no alcanza para responder, dilo ("No encontré eso en la biblioteca") en vez de suponer.
- No uses conocimiento general.

Pregunta: {question}"""

SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "citekeys": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["answer", "citekeys"],
}


@dataclass
class Answer:
    question: str
    answer: str
    citekeys: list[str]
    model: str
    sources: list[dict[str, Any]] = field(default_factory=list)


def gather(
    lib: Library, question: str, filters: Filters, paper: str | None = None
) -> tuple[str, list[dict]]:
    """The context sent to the model, and the list of sources it came from."""
    index = SearchIndex(lib)
    sources: list[dict] = []
    blocks: list[str] = []
    hits = [] if paper else index.search(question, filters, limit=MAX_PAPERS)
    for hit in hits:
        if hit.one_sentence:
            blocks.append(f"[{hit.citekey}] {hit.title} ({hit.year}). Resumen: {hit.one_sentence}")
            sources.append({"citekey": hit.citekey, "kind": "resumen"})
    # Spanish question, English paper: add the bilingual search terms of the closest papers
    keys = [paper] if paper else [h.citekey for h in hits[:3]]
    terms = [
        t for k in keys if lib.paper_path(k).is_file() for t in lib.read_paper(k).meta.keywords
    ]
    query = " ".join([question, *terms])
    passages: list[Passage] = index.passages(query, filters, paper=paper, limit=MAX_PASSAGES)
    for passage in passages:
        text = " ".join(passage.text.split())[:PASSAGE_CHARS]
        kind = "figura" if passage.kind == "figure" else passage.section
        blocks.append(f"[{passage.citekey}, p. {passage.page_start}] ({kind}) {text}")
        sources.append(
            {"citekey": passage.citekey, "page": passage.page_start, "kind": passage.kind}
        )
    return "\n\n".join(blocks), sources


def ask(
    lib: Library,
    backend: Backend,
    question: str,
    filters: Filters | None = None,
    paper: str | None = None,
    language: str = "español",
) -> Answer:
    context, sources = gather(lib, question, filters or Filters(), paper)
    if not context:
        return Answer(question, "No encontré nada en la biblioteca sobre eso.", [], "-", [])
    prompt = PROMPT.format(language=language, question=question)
    output, model = backend.run(prompt, SCHEMA, stdin=f"Material de la biblioteca:\n\n{context}")
    return Answer(question, output["answer"].strip(), output.get("citekeys", []), model, sources)
