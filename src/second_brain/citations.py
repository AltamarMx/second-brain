"""Citation graph inside the library, from the reference lists Crossref publishes.

- ``sb refs KEY``: which papers of the library this one cites, and which cite it.
- ``sb refs --missing``: works cited by several papers of the library that are not in it yet.

Uses the Crossref responses already cached by the ingestion (network only for
papers never looked up). References without a DOI are counted but not linked.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .ingest.doi import normalize_doi
from .ingest.metadata import MetadataClient, NetworkError
from .library import InvalidDocument, Library
from .models import Paper
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
  body {{ margin: 0; height: 100vh; display: flex; flex-direction: column;
         font-family: system-ui, sans-serif; background: #fafafa; color: #222; }}
  header {{ padding: 10px 16px; border-bottom: 1px solid #ddd; background: #fff; }}
  header h1 {{ font-size: 16px; margin: 0 0 4px; }} header p {{ margin: 0; font-size: 13px; color: #555; }}
  #timeline {{ display: flex; align-items: center; gap: 10px; margin-top: 8px; font-size: 13px; }}
  #timeline[hidden], #pending[hidden] {{ display: none; }}
  #slider {{ flex: 1; max-width: 520px; }}
  #year {{ font-weight: 600; min-width: 3em; font-variant-numeric: tabular-nums; }}
  #shown {{ color: #555; }}
  #play {{ width: 2.2em; font-size: 14px; }}
  #pending {{ margin-top: 6px; font-size: 13px; color: #b4500a; }}
  #pending summary {{ cursor: pointer; }}
  #pending button {{ margin: 4px 4px 0 0; font: inherit; color: inherit; background: #fff4ec;
                     border: 1px dashed #e8590c; border-radius: 4px; cursor: pointer; }}
  #graph {{ flex: 1; min-height: 0; }}
</style></head><body>
<header><h1>Grafo de citas de la biblioteca</h1>
<p>{summary} · Azul: tus artículos (tamaño = cuántos de tus artículos lo citan) · Gris: obras que no tienes y citan {min_count}+ de tus artículos · Borde naranja punteado: sin año · Flecha: A cita a B</p>
<div id="timeline"><button id="play" title="Reproducir por año de publicación">▶</button>
<input id="slider" type="range" step="1" aria-label="Año de publicación"><span id="year"></span><span id="shown"></span></div>
<details id="pending" hidden><summary></summary></details></header>
<div id="graph"></div>
<script>
const nodes = new vis.DataSet({nodes});
const edges = new vis.DataSet({edges});
const network = new vis.Network(document.getElementById("graph"), {{nodes, edges}}, {{
  nodes: {{shape: "dot", font: {{size: 13}}}},
  edges: {{arrows: "to", color: {{color: "#9aa", highlight: "#333"}}, smooth: false}},
  physics: {{stabilization: {{iterations: 300}}}}
}});

// Timeline: each work appears in its publication year. Hidden nodes stay in the physics
// simulation, so the layout is the one of the whole graph and nothing jumps around.
// Papers without a year never hide: they stay put, marked as pending.
const years = [...new Set(nodes.map(n => n.year).filter(y => y != null))].sort((a, b) => a - b);
const slider = document.getElementById("slider"), play = document.getElementById("play");
const papers = nodes.get({{filter: n => n.kind === "paper"}}).length;
const visible = (node, year) => node.year == null || node.year <= year;

function showUntil(year) {{
  nodes.update(nodes.map(n => ({{id: n.id, hidden: !visible(n, year)}})));
  edges.update(edges.map(e => ({{
    id: e.id, hidden: !(visible(nodes.get(e.from), year) && visible(nodes.get(e.to), year))
  }})));
  slider.value = year;
  document.getElementById("year").textContent = year;
  const shown = nodes.get({{filter: n => n.kind === "paper" && visible(n, year)}}).length;
  document.getElementById("shown").textContent = `${{shown}} de ${{papers}} artículos`;
}}

let timer = null;
function stop() {{ clearInterval(timer); timer = null; play.textContent = "▶"; }}
play.onclick = () => {{
  if (timer) return stop();
  let i = years.findIndex(y => y > +slider.value);
  if (i < 0) i = 0;  // at the end: start over
  showUntil(years[i]);
  play.textContent = "⏸";
  timer = setInterval(() => (++i < years.length ? showUntil(years[i]) : stop()), 800);
}};
slider.oninput = () => {{ stop(); showUntil(+slider.value); }};
if (years.length) {{
  slider.min = years[0];
  slider.max = years[years.length - 1];
  showUntil(years[years.length - 1]);
}} else {{
  document.getElementById("timeline").hidden = true;
}}

const pending = nodes.get({{filter: n => n.pending}});
if (pending.length) {{
  const box = document.getElementById("pending");
  box.hidden = false;
  box.querySelector("summary").textContent = `⚠ ${{pending.length}} sin año: siempre visibles en la ` +
    "animación hasta que alguien complete year en su ficha";
  for (const node of pending) {{
    const button = document.createElement("button");
    button.textContent = node.id;
    button.onclick = () => {{
      network.selectNodes([node.id]);
      network.focus(node.id, {{scale: 1.2, animation: true}});
    }};
    box.append(button);
  }}
}}
</script></body></html>
"""

PENDING_COLOR = {"background": "#3b7dd8", "border": "#e8590c"}


def _year(value: str | None) -> int | None:
    """Year from a Crossref reference ("2001", "2001a"…), if it has one."""
    match = re.match(r"\d{4}", str(value or ""))
    return int(match.group()) if match else None


def graph_html(graph: Graph, papers: Mapping[str, Paper], min_count: int = 2) -> str:
    """A self-contained interactive page (vis-network from a CDN) of the citation graph.

    A slider replays it by publication year. Papers without ``year`` stay visible the
    whole time, marked as pending; works outside the library without a year appear with
    the first of your papers that cites them.
    """
    nodes, edges = [], []
    for key, paper in sorted(papers.items()):
        cited = len(graph.cited_by.get(key, []))
        node = {"id": key, "label": key, "title": f"{paper.title} ({paper.year})",
                "value": 1 + cited, "color": "#3b7dd8", "kind": "paper", "year": paper.year}  # fmt: skip
        if paper.year is None:
            node |= {"title": f"{paper.title}\nAño pendiente: falta year en su ficha",
                     "pending": True, "color": {**PENDING_COLOR, "highlight": PENDING_COLOR},
                     "borderWidth": 3, "shapeProperties": {"borderDashes": [4, 3]}}  # fmt: skip
        nodes.append(node)
        for target in graph.cites.get(key, []):
            edges.append({"from": key, "to": target})
    for work in missing_works(graph, min_count, limit=100):
        label = (work.author or work.doi)[:20] + (f" {work.year}" if work.year else "")
        year = _year(work.year) or min(
            (papers[k].year for k in work.cited_by if k in papers and papers[k].year), default=None
        )
        nodes.append({"id": work.doi, "label": label, "title": work.title or work.doi,
                      "value": len(work.cited_by), "color": "#bbbbbb", "kind": "work",
                      "year": year})  # fmt: skip
        edges += [{"from": key, "to": work.doi, "dashes": True} for key in work.cited_by]
    links = sum(len(v) for v in graph.cites.values())
    summary = f"{len(papers)} artículos, {links} citas entre ellos"
    return HTML.format(
        summary=summary, min_count=min_count,
        nodes=json.dumps(nodes, ensure_ascii=False), edges=json.dumps(edges, ensure_ascii=False),
    )  # fmt: skip
