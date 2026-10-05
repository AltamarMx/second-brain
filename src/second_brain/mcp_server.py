"""MCP server ``sb-mcp``: the library as typed tools for agents (OpenCode with a local model, Claude).

Started by the agent over stdio when a session opens and closed with it. The
library is the current directory (or ``SB_HOME``). Same core as the CLI:
everything still goes through ``library.py``.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer

from . import bibtex
from . import projects as proj
from .config import find_home, load_config
from .doctor import library_status as status_of
from .index import Filters, SearchIndex
from .library import InvalidDocument, Library
from .processing import one_sentence
from .reading import select_pages, select_section

MAX_TEXT_CHARS = 30_000

INSTRUCTIONS = """Biblioteca personal de artículos científicos. Responde solo con lo que devuelvan estas
herramientas y cita cada afirmación como [citekey, p. N]. Flujo: search_papers → get_paper →
search_passages / get_fulltext(pages) para los detalles. Pregunta antes de crear proyectos."""


def build_server(home: Path | None = None) -> MCPServer:
    lib = Library(find_home(home))
    server = MCPServer("second-brain", instructions=INSTRUCTIONS)

    def filters(
        project=None, study_type=None, country=None, region=None, locality=None, years=None
    ):
        start, end = Filters.parse_years(years)
        return Filters(project, study_type, country, region, locality, start, end)

    @server.tool()
    def library_status() -> dict[str, Any]:
        """Cuántos artículos y proyectos hay, por estado, y cuántos PDFs esperan en inbox/."""
        data = dataclasses.asdict(status_of(lib.home))
        data["home"] = str(data["home"])
        return data

    @server.tool()
    def search_papers(
        query: str, country: str | None = None, study_type: str | None = None,
        project: str | None = None, years: str | None = None, limit: int = 10,
    ) -> list[dict[str, Any]]:  # fmt: skip
        """Artículos sobre un tema. Filtros: country (ISO, p. ej. MX), study_type (experimental,
        numerico, ambos, teorico, revision), project (slug), years ("2019", "2015..2024").
        Busca también con los términos en inglés."""
        hits = SearchIndex(lib).search(
            query, filters(project, study_type, country, years=years), limit
        )
        return [dataclasses.asdict(h) for h in hits]

    @server.tool()
    def list_papers(
        country: str | None = None, study_type: str | None = None, project: str | None = None,
        years: str | None = None,
    ) -> list[dict[str, Any]]:  # fmt: skip
        """Artículos que cumplen filtros, sin tema (útil para contar)."""
        hits = SearchIndex(lib).list(filters(project, study_type, country, years=years))
        return [
            {"citekey": h.citekey, "title": h.title, "year": h.year, "places": h.places}
            for h in hits
        ]

    @server.tool()
    def search_passages(
        query: str, paper: str | None = None, limit: int = 8
    ) -> list[dict[str, Any]]:
        """Pasajes del texto completo y de las figuras que responden a la consulta, con página y sección.
        Con paper=citekey busca solo en ese artículo."""
        found = SearchIndex(lib).passages(query, Filters(), paper=paper, limit=limit)
        return [dataclasses.asdict(p) for p in found]

    @server.tool()
    def get_paper(citekey: str) -> dict[str, Any]:
        """Metadatos, clasificación y resumen de un artículo."""
        doc = lib.read_paper(citekey)
        data = doc.meta.model_dump(mode="json")
        data["summary"] = doc.body
        data["one_sentence"] = one_sentence(doc.body)
        return data

    @server.tool()
    def get_fulltext(citekey: str, pages: str | None = None, section: str | None = None) -> str:
        """Texto completo con marcas <!-- page N -->. Pide solo lo necesario: pages="4-6" o
        section="methods". Si es muy largo se corta y lo indica."""
        body = lib.read_fulltext(citekey).body
        if pages:
            body = select_pages(body, pages)
        if section:
            body = select_section(body, section) or f"(no hay una sección que contenga {section!r})"
        if len(body) > MAX_TEXT_CHARS:
            body = body[:MAX_TEXT_CHARS] + "\n\n[cortado: pide un rango de páginas con pages=]"
        return body

    @server.tool()
    def get_figures(citekey: str) -> str:
        """Descripciones generadas de las figuras de un artículo (cifras aproximadas)."""
        path = lib.figures_path(citekey)
        return lib.read_figure_set(citekey).body if path.is_file() else "(sin figuras descritas)"

    @server.tool()
    def list_projects() -> list[dict[str, Any]]:
        """Proyectos con su descripción y número de artículos."""
        return [
            {
                **s.project.model_dump(mode="json"),
                "description": s.description,
                "papers": len(s.members),
            }
            for s in proj.summaries(lib)
        ]

    @server.tool()
    def get_project(slug: str) -> dict[str, Any]:
        """Un proyecto y sus artículos (con la nota de para qué sirve cada uno)."""
        doc = proj.require_project(lib, slug)
        papers = sorted(proj.members(lib, slug), key=lambda p: p.citekey)
        return {
            **doc.meta.model_dump(mode="json"),
            "description": doc.body,
            "papers": [
                {"citekey": p.citekey, "title": p.title, "note": p.projects[slug].note}
                for p in papers
            ],
        }

    @server.tool()
    def export_bibtex(project: str | None = None, citekeys: list[str] | None = None,
                      format: str = "bibtex") -> str:  # fmt: skip
        """BibTeX generado desde los registros (nunca lo escribas a mano). format: bibtex o biblatex."""
        papers = {
            d.meta.citekey: d.meta for d in lib.iter_papers() if not isinstance(d, InvalidDocument)
        }
        selected = proj.members(lib, project) if project else []
        selected += [papers[k] for k in citekeys or [] if k in papers]
        return bibtex.render(selected, "biblatex" if format == "biblatex" else "bibtex")

    @server.tool()
    def create_project(slug: str, name: str, kind: str | None = None, description: str = "") -> str:
        """Crea un proyecto. Confírmalo antes con el usuario."""
        proj.create_project(lib, load_config(lib.home), slug, name, kind, description)
        return f"proyecto {slug} creado"

    @server.tool()
    def add_to_project(slug: str, citekeys: list[str], note: str | None = None) -> str:
        """Agrega artículos a un proyecto existente."""
        added, present = proj.add_papers(lib, slug, citekeys, note)
        return f"agregados: {added}; ya estaban: {present}"

    @server.tool()
    def remove_from_project(slug: str, citekeys: list[str]) -> str:
        """Quita artículos de un proyecto (siguen en la biblioteca)."""
        removed, absent = proj.remove_papers(lib, slug, citekeys)
        return f"quitados: {removed}; no estaban: {absent}"

    return server


def main() -> None:
    build_server().run("stdio")
