"""Citation graph inside the library, from the reference lists Crossref publishes.

- ``sb refs KEY``: which papers of the library this one cites, and which cite it.
- ``sb refs --missing``: works cited by several papers of the library that are not in it yet.

Uses the Crossref responses already cached by the ingestion (network only for
papers never looked up). References without a DOI are counted but not linked.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .ingest.doi import normalize_doi
from .ingest.metadata import MetadataClient, NetworkError
from .library import InvalidDocument, Library
from .textutil import strip_markup


@dataclass
class CitedWork:
    doi: str
    title: str | None
    author: str | None
    year: str | None
    container: str | None
    cited_by: list[str] = field(default_factory=list)


@dataclass
class Graph:
    cites: dict[str, list[str]]  # citekey → citekeys of the library it cites
    cited_by: dict[str, list[str]]  # citekey → citekeys of the library that cite it
    references: dict[str, int]  # citekey → number of references Crossref lists
    external: dict[str, CitedWork]  # DOI → work outside the library
    without_data: list[str]  # papers without DOI or without reference list


def _describe(reference: dict[str, Any]) -> tuple[str | None, str | None, str | None, str | None]:
    title = reference.get("article-title") or reference.get("volume-title")
    if not title and reference.get("unstructured"):
        title = reference["unstructured"]
    return (
        strip_markup(title)[:200] if title else None,
        reference.get("author"),
        reference.get("year"),
        reference.get("journal-title") or reference.get("series-title"),
    )


def build_graph(lib: Library, client: MetadataClient) -> Graph:
    papers = {
        d.meta.citekey: d.meta for d in lib.iter_papers() if not isinstance(d, InvalidDocument)
    }
    by_doi = {normalize_doi(p.doi): k for k, p in papers.items() if p.doi}
    graph = Graph({k: [] for k in papers}, {k: [] for k in papers}, {}, {}, [])
    for citekey, paper in sorted(papers.items()):
        message = None
        if paper.doi:
            try:
                message = client.crossref_work(paper.doi)
            except NetworkError:
                message = None
        references = (message or {}).get("reference") or []
        if not references:
            graph.without_data.append(citekey)
            continue
        graph.references[citekey] = len(references)
        for reference in references:
            if not reference.get("DOI"):
                continue
            doi = normalize_doi(reference["DOI"])
            target = by_doi.get(doi)
            if target and target != citekey:
                if target not in graph.cites[citekey]:
                    graph.cites[citekey].append(target)
                    graph.cited_by[target].append(citekey)
            elif target is None:
                work = graph.external.get(doi)
                if work is None:
                    work = graph.external[doi] = CitedWork(doi, *_describe(reference))
                if citekey not in work.cited_by:
                    work.cited_by.append(citekey)
    return graph


def missing_works(graph: Graph, min_count: int = 2, limit: int = 20) -> list[CitedWork]:
    """Works outside the library cited by at least ``min_count`` of its papers, most cited first."""
    works = [w for w in graph.external.values() if len(w.cited_by) >= min_count]
    return sorted(works, key=lambda w: (-len(w.cited_by), w.year or ""))[:limit]


HTML = """<!doctype html>
<html lang="es"><head><meta charset="utf-8"><title>Grafo de citas</title>
<script src="https://unpkg.com/vis-network@9.1.9/standalone/umd/vis-network.min.js"></script>
<style>
  body {{ margin: 0; font-family: system-ui, sans-serif; background: #fafafa; color: #222; }}
  header {{ padding: 10px 16px; border-bottom: 1px solid #ddd; background: #fff; }}
  header h1 {{ font-size: 16px; margin: 0 0 4px; }} header p {{ margin: 0; font-size: 13px; color: #555; }}
  #graph {{ height: calc(100vh - 64px); }}
</style></head><body>
<header><h1>Grafo de citas de la biblioteca</h1>
<p>{summary} · Azul: tus artículos (tamaño = cuántos de tus artículos lo citan) · Gris: obras que no tienes y citan {min_count}+ de tus artículos · Flecha: A cita a B</p></header>
<div id="graph"></div>
<script>
const nodes = new vis.DataSet({nodes});
const edges = new vis.DataSet({edges});
new vis.Network(document.getElementById("graph"), {{nodes, edges}}, {{
  nodes: {{shape: "dot", font: {{size: 13}}}},
  edges: {{arrows: "to", color: {{color: "#9aa", highlight: "#333"}}, smooth: false}},
  physics: {{stabilization: {{iterations: 300}}}}
}});
</script></body></html>
"""


def graph_html(graph: Graph, titles: dict[str, str], min_count: int = 2) -> str:
    """A self-contained interactive page (vis-network from a CDN) of the citation graph."""
    nodes, edges = [], []
    for key, title in sorted(titles.items()):
        cited = len(graph.cited_by.get(key, []))
        nodes.append(
            {"id": key, "label": key, "title": title, "value": 1 + cited, "color": "#3b7dd8"}
        )
        for target in graph.cites.get(key, []):
            edges.append({"from": key, "to": target})
    for work in missing_works(graph, min_count, limit=100):
        label = (work.author or work.doi)[:20] + (f" {work.year}" if work.year else "")
        nodes.append({"id": work.doi, "label": label, "title": work.title or work.doi,
                      "value": len(work.cited_by), "color": "#bbbbbb"})  # fmt: skip
        edges += [{"from": key, "to": work.doi, "dashes": True} for key in work.cited_by]
    links = sum(len(v) for v in graph.cites.values())
    summary = f"{len(titles)} artículos, {links} citas entre ellos"
    return HTML.format(
        summary=summary, min_count=min_count,
        nodes=json.dumps(nodes, ensure_ascii=False), edges=json.dumps(edges, ensure_ascii=False),
    )  # fmt: skip
