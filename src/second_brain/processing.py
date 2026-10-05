"""``sb process``: summary, classification and figure descriptions with an LLM.

Everything the LLM produces is validated and stored with its provenance
(backend, model, prompt version, machine, date, hash), so it can be
regenerated selectively. A summary edited by hand is never overwritten
without ``force``.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
import tempfile
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path
from string import Template
from typing import Any, Literal

import pymupdf

from .backends import Backend, BackendError
from .config import LibraryConfig
from .library import Library
from .models import Classification, FigureRef, FigureSet, LlmProvenance, Paper
from .reading import split_pages

PROCESS_PROMPT = "process.v1"
FIGURES_PROMPT = "figures.v1"
MAX_TEXT_CHARS = 400_000  # ~100k tokens; longer documents are truncated (noted in the result)
MAX_FIGURE_PAGES = 12
FIGURE_DPI = 110
CAPTION_RE = re.compile(
    r"^\s*(?:\*\*|_)*\s*(?:Fig\.|Figure|Figura|FIGURE|FIGURA)\s*(\d+[a-z]?)\s*(?:\*\*|_)*\s*[.:|]\s*(.+(?:\n[^\n]+)*)",
    re.MULTILINE,
)
SECTION_TITLES = {
    "one_sentence": "En una frase",
    "problem": "Problema y objetivo",
    "methods": "Datos y métodos",
    "results": "Resultados principales",
    "conclusions": "Conclusiones",
    "limitations": "Limitaciones (según los autores)",
}
FIGURE_KINDS = [
    "line-chart", "bar-chart", "scatter", "map", "diagram", "photo", "table-image", "schematic", "other",
]  # fmt: skip

Outcome = Literal["processed", "skipped", "error"]


class ProcessingError(RuntimeError):
    pass


@dataclass
class ProcessResult:
    citekey: str
    outcome: Outcome
    figures: int = 0
    message: str = ""
    notes: list[str] = field(default_factory=list)


def prompt_text(name: str, **values: str) -> str:
    raw = files("second_brain.prompts").joinpath(f"{name}.md").read_text(encoding="utf-8")
    return Template(raw).safe_substitute(values)


def body_hash(body: str) -> str:
    return hashlib.sha256(body.strip().encode()).hexdigest()


def process_schema(study_types: list[str]) -> dict[str, Any]:
    nullable = {"type": ["string", "null"]}
    return {
        "type": "object",
        "properties": {
            "summary": {
                "type": "object",
                "properties": {
                    "one_sentence": {"type": "string"},
                    "problem": {"type": "string"},
                    "methods": {"type": "string"},
                    "results": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                    "conclusions": {"type": "string"},
                    "limitations": {"type": "string"},
                },
                "required": list(SECTION_TITLES),
            },
            "classification": {
                "type": "object",
                "properties": {
                    "study_type": {"type": "string", "enum": study_types},
                    "locations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "country": {"type": ["string", "null"], "pattern": "^[A-Z]{2}$"},
                                "region": nullable,
                                "locality": nullable,
                                "page": {"type": ["integer", "null"]},
                            },
                            "required": ["country", "region", "locality", "page"],
                        },
                    },
                },
                "required": ["study_type", "locations"],
            },
            "search_terms": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["summary", "classification", "search_terms"],
    }


FIGURES_SCHEMA = {
    "type": "object",
    "properties": {
        "figures": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "number": {"type": "string"},
                    "page": {"type": "integer"},
                    "kind": {"type": "string", "enum": FIGURE_KINDS},
                    "description": {"type": "string"},
                },
                "required": ["number", "page", "kind", "description"],
            },
        }
    },
    "required": ["figures"],
}


def summary_markdown(summary: dict[str, Any]) -> str:
    parts = []
    for key, title in SECTION_TITLES.items():
        value = summary[key]
        if isinstance(value, list):
            text = "\n".join(f"- {item.strip()}" for item in value if item.strip())
        else:
            text = value.strip()
        parts.append(f"## {title}\n{text}")
    return "\n\n".join(parts)


def one_sentence(body: str) -> str | None:
    """The "En una frase" section of a stored summary."""
    match = re.search(r"^## En una frase\n(.+?)(?:\n## |\Z)", body, re.MULTILINE | re.DOTALL)
    return match.group(1).strip() if match else None


@dataclass(frozen=True)
class Caption:
    number: str
    page: int
    text: str


def find_captions(fulltext_body: str) -> list[Caption]:
    """Figure captions ("Fig. 3. …", "Figure 3: …"), not mentions in the text ("Fig. 3 shows")."""
    seen: dict[str, Caption] = {}
    for page, text in split_pages(fulltext_body):
        for match in CAPTION_RE.finditer(text):
            number = match.group(1)
            lines = []
            for line in match.group(2).splitlines():  # the caption ends at its first full stop
                lines.append(line)
                if line.rstrip().endswith("."):
                    break
            caption = " ".join(re.sub(r"[*_]+", "", " ".join(lines)).split())
            if number not in seen and len(caption) > 3:
                seen[number] = Caption(number, page, caption[:300])
    return list(seen.values())


def render_pages(pdf: Path, pages: list[int], directory: Path) -> list[Path]:
    images = []
    with pymupdf.open(pdf) as doc:
        for page in pages:
            if 1 <= page <= doc.page_count:
                path = directory / f"pagina-{page:03d}.png"
                doc[page - 1].get_pixmap(dpi=FIGURE_DPI).save(path)
                images.append(path)
    return images


class Processor:
    def __init__(
        self,
        lib: Library,
        config: LibraryConfig,
        backend: Backend,
        machine: str,
        today: dt.date | None = None,
    ):
        self.lib = lib
        self.config = config
        self.backend = backend
        self.machine = machine
        self.today = today or dt.date.today()

    def _provenance(self, model: str, prompt: str, body: str | None = None) -> LlmProvenance:
        return LlmProvenance(
            backend=self.backend.name,
            model=model,
            prompt=prompt,
            machine=self.machine,
            date=self.today,
            sha256=body_hash(body) if body is not None else None,
        )

    # --- selection ------------------------------------------------------------

    def needs_summary(self, paper: Paper, body: str, stale: bool = False) -> bool:
        current = paper.provenance.process
        if current is None:
            return True
        return stale and current.prompt != self.config.library.process_prompt

    def needs_figures(self, paper: Paper, stale: bool = False) -> bool:
        if not self.config.figures.describe:
            return False
        current = paper.provenance.figures
        if current is None:
            return True
        return stale and current.prompt != FIGURES_PROMPT

    # --- entry point ------------------------------------------------------------

    def process(
        self, citekey: str, *, force: bool = False, stale: bool = False, figures: bool = True,
        summary: bool = True,
    ) -> ProcessResult:  # fmt: skip
        result = ProcessResult(citekey, "skipped")
        try:
            doc = self.lib.read_paper(citekey)
            if not self.lib.fulltext_path(citekey).is_file():
                raise ProcessingError("no tiene texto completo (¿le falta el PDF?)")
            fulltext = self.lib.read_fulltext(citekey).body
            paper, body = doc.meta, doc.body
            done: list[str] = []

            if summary and (force or self.needs_summary(paper, body, stale)):
                stored = paper.provenance.process
                if (
                    body
                    and stored
                    and stored.sha256
                    and stored.sha256 != body_hash(body)
                    and not force
                ):
                    result.notes.append(
                        "el resumen fue editado a mano; usa --force para regenerarlo"
                    )
                else:
                    paper, body = self._summarize(paper, fulltext, result)
                    done.append("resumen y clasificación")

            if figures and (force or self.needs_figures(paper, stale)):
                paper = self._describe_figures(paper, fulltext, result)
                done.append(f"{paper.figures} figuras" if paper.figures else "sin figuras")

            if done:
                if paper.status == "needs_processing" and paper.provenance.process is not None:
                    paper = paper.model_copy(update={"status": "processed"})
                self.lib.write_paper(paper, body)
                result.outcome = "processed"
                result.message = ", ".join(done)
            result.figures = paper.figures
        except (ProcessingError, BackendError) as exc:
            result.outcome, result.message = "error", str(exc)
        return result

    # --- steps ------------------------------------------------------------------

    def _summarize(self, paper: Paper, fulltext: str, result: ProcessResult) -> tuple[Paper, str]:
        text = fulltext
        if len(text) > MAX_TEXT_CHARS:
            text = text[:MAX_TEXT_CHARS]
            result.notes.append("texto muy largo: se resumió solo el inicio")
        vocab = self.config.vocab.study_type
        prompt = prompt_text(
            self.config.library.process_prompt,
            language=_language(self.config.library.summary_language),
            study_types=", ".join(f'"{v}"' for v in vocab),
        )
        header = f"Título: {paper.title}\n\n"
        output, model = self.backend.run(prompt, process_schema(vocab), stdin=header + text)
        body = summary_markdown(output["summary"])
        raw = output["classification"]
        if raw["study_type"] not in vocab:
            raise ProcessingError(f"tipo de estudio inválido: {raw['study_type']}")
        classification = Classification.model_validate(
            {"study_type": raw["study_type"], "locations": raw["locations"], "reviewed": False}
        )
        keywords = paper.keywords or _unique(output.get("search_terms", []))[:12]
        provenance = paper.provenance.model_copy(
            update={"process": self._provenance(model, self.config.library.process_prompt, body)}
        )
        updated = paper.model_copy(
            update={
                "classification": classification,
                "keywords": keywords,
                "provenance": provenance,
            }
        )
        return updated, body

    def _describe_figures(self, paper: Paper, fulltext: str, result: ProcessResult) -> Paper:
        captions = find_captions(fulltext)
        pdf = self.lib.pdfs_dir / f"{paper.citekey}.pdf"
        if captions and not pdf.exists():
            raise ProcessingError("hay figuras pero el PDF no está en esta máquina (sb pdf get)")
        figure_set = FigureSet(citekey=paper.citekey)
        body = ""
        model = "-"
        if captions:
            pages = sorted({c.page for c in captions})
            if len(pages) > MAX_FIGURE_PAGES:
                pages = pages[:MAX_FIGURE_PAGES]
                captions = [c for c in captions if c.page in pages]
                result.notes.append(
                    f"solo se describieron las figuras de {MAX_FIGURE_PAGES} páginas"
                )
            with tempfile.TemporaryDirectory(prefix="sb-figuras-") as tmp:
                images = render_pages(pdf, pages, Path(tmp))
                prompt = prompt_text(
                    FIGURES_PROMPT,
                    language=_language(self.config.library.summary_language),
                    pages="\n".join(
                        f"- {img.name} (página {img.stem.split('-')[1].lstrip('0')})"
                        for img in images
                    ),
                    captions="\n".join(
                        f"- Fig. {c.number} (p. {c.page}): {c.text}" for c in captions
                    ),
                )
                output, model = self.backend.run(prompt, FIGURES_SCHEMA, images=images)
            by_number = {c.number: c for c in captions}
            sections, refs = [], []
            for figure in output["figures"]:
                caption = by_number.get(figure["number"].strip())
                if caption is None:
                    continue  # the model described something we did not ask for
                figure_id = f"fig{caption.number}"
                refs.append(FigureRef(id=figure_id, page=caption.page, kind=figure["kind"]))
                sections.append(
                    f"## Fig. {caption.number} (p. {caption.page})\n"
                    f"**Pie:** {caption.text}\n\n"
                    f"**Descripción (generada):** {figure['description'].strip()}"
                )
            figure_set = FigureSet(
                citekey=paper.citekey,
                figures=refs,
                provenance=self._provenance(model, FIGURES_PROMPT),
            )
            body = "\n\n".join(sections)
        if figure_set.figures:
            self.lib.write_figure_set(figure_set, body)
        backend = self.backend.name if captions else "none"
        provenance = paper.provenance.model_copy(
            update={
                "figures": LlmProvenance(
                    backend=backend,
                    model=model,
                    prompt=FIGURES_PROMPT,
                    machine=self.machine,
                    date=self.today,
                )
            }
        )
        return paper.model_copy(
            update={"figures": len(figure_set.figures), "provenance": provenance}
        )


def _language(code: str) -> str:
    return {"es": "español", "en": "inglés", "pt": "portugués"}.get(code, code)


def _unique(items: list[str]) -> list[str]:
    seen: list[str] = []
    for item in items:
        item = item.strip()
        if item and item.lower() not in {s.lower() for s in seen}:
            seen.append(item)
    return seen
