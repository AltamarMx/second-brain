import datetime as dt
import json
import re

import pymupdf
import pytest
from conftest import make_paper
from typer.testing import CliRunner

from second_brain import cli
from second_brain.agents import BEGIN, END, sync_agents
from second_brain.config import load_config
from second_brain.index import Filters, SearchIndex, chunk_fulltext, fts_query
from second_brain.models import FullText
from second_brain.processing import Processor, body_hash, find_captions, one_sentence

TODAY = dt.date(2026, 10, 4)
FULLTEXT = """<!-- page 1 -->
# Night ventilation in Hermosillo
1. Introduction
Passive cooling with night ventilation reduces indoor temperature.

<!-- page 2 -->
2. Methods
We measured air temperature in 12 houses in Hermosillo, Sonora.
Fig. 1. Indoor air temperature for cases A and B
during July.
As Fig. 1 shows, case B is cooler.

<!-- page 3 -->
3. Results
Night ventilation lowered peak temperature by 2.5 °C.
References
[1] Smith, Thermal comfort in hot climates, 2010."""


class FakeBackend:
    name = "fake"

    def __init__(self):
        self.calls = []

    def run(self, prompt, schema, stdin="", images=None):
        self.calls.append(
            {"prompt": prompt, "stdin": stdin, "images": [p.name for p in images or []]}
        )
        if "summary" in schema["properties"]:
            return {
                "summary": {
                    "one_sentence": "La ventilación nocturna enfría casas en Hermosillo.",
                    "problem": "Calor extremo (p. 1).",
                    "methods": "Mediciones en 12 casas (p. 2).",
                    "results": ["Baja 2.5 °C el pico (p. 3)."],
                    "conclusions": "Funciona.",
                    "limitations": "Los autores no reportan limitaciones",
                },
                "classification": {
                    "study_type": "experimental",
                    "locations": [
                        {"country": "MX", "region": "Sonora", "locality": "Hermosillo", "page": 2}
                    ],
                },
                "search_terms": ["ventilación nocturna", "night ventilation", "Night ventilation"],
            }, "fake-model"
        numbers = re.findall(r"- Fig\. (\S+) \(p\. (\d+)\)", prompt)
        return {
            "figures": [
                {"number": n, "page": int(p), "kind": "line-chart", "description": f"Gráfica {n}."}
                for n, p in numbers
            ]
            + [{"number": "99", "page": 1, "kind": "other", "description": "no pedida"}]
        }, "fake-model"


@pytest.fixture
def paper(lib):
    lib.write_paper(make_paper(title="Night ventilation in Hermosillo"))
    lib.write_fulltext(
        FullText(
            citekey="garcia2021thermal",
            source_pdf_sha256="ab",
            extractor="x",
            extracted=TODAY,
            pages=3,
        ),
        FULLTEXT,
    )
    doc = pymupdf.open()
    for _ in range(3):
        doc.new_page()
    doc.save(lib.pdfs_dir / "garcia2021thermal.pdf")
    return "garcia2021thermal"


def processor(lib, backend=None):
    return Processor(lib, load_config(lib.home), backend or FakeBackend(), "test-machine", TODAY)


def test_find_captions_ignores_mentions():
    captions = find_captions(FULLTEXT)
    assert [(c.number, c.page) for c in captions] == [("1", 2)]
    assert captions[0].text == "Indoor air temperature for cases A and B during July."


def test_process_writes_summary_classification_and_figures(lib, paper):
    backend = FakeBackend()
    result = processor(lib, backend).process(paper)
    assert result.outcome == "processed", result.message
    doc = lib.read_paper(paper)
    assert doc.meta.status == "processed"
    assert doc.meta.classification.study_type == "experimental"
    assert doc.meta.classification.locations[0].locality == "Hermosillo"
    assert doc.meta.keywords == ["ventilación nocturna", "night ventilation"]
    assert doc.meta.provenance.process.model == "fake-model"
    assert doc.meta.provenance.process.sha256 == body_hash(doc.body)
    assert one_sentence(doc.body) == "La ventilación nocturna enfría casas en Hermosillo."
    assert "## Resultados principales\n- Baja 2.5 °C" in doc.body
    assert doc.meta.figures == 1
    figures = lib.read_figure_set(paper)
    assert [f.id for f in figures.meta.figures] == ["fig1"]
    assert "**Descripción (generada):** Gráfica 1." in figures.body
    assert backend.calls[1]["images"] == ["pagina-002.png"]
    assert "Título: Night ventilation" in backend.calls[0]["stdin"]


def test_process_is_idempotent_and_respects_hand_edits(lib, paper):
    proc = processor(lib)
    proc.process(paper)
    assert proc.process(paper).outcome == "skipped"
    doc = lib.read_paper(paper)
    lib.write_paper(doc.meta, doc.body + "\n\nMi comentario.")
    result = proc.process(paper, force=True, figures=False)
    assert result.outcome == "processed"  # force overwrites
    lib.write_paper(lib.read_paper(paper).meta, "editado a mano")
    result = processor(lib).process(paper, stale=True)
    assert result.outcome == "skipped"


def test_needs_review_stays_needs_review(lib, paper):
    doc = lib.read_paper(paper)
    lib.write_paper(doc.meta.model_copy(update={"status": "needs_review"}))
    processor(lib).process(paper)
    assert lib.read_paper(paper).meta.status == "needs_review"


def test_figures_need_local_pdf(lib, paper):
    (lib.pdfs_dir / f"{paper}.pdf").unlink()
    result = processor(lib).process(paper)
    assert result.outcome == "error" and "sb pdf get" in result.message


def test_no_captions_means_no_figure_call(lib, paper):
    lib.write_fulltext(lib.read_fulltext(paper).meta, "<!-- page 1 -->\nSolo texto.")
    backend = FakeBackend()
    processor(lib, backend).process(paper)
    assert len(backend.calls) == 1
    assert lib.read_paper(paper).meta.provenance.figures.backend == "none"


# --- index ----------------------------------------------------------------------


def test_chunks_mark_references():
    chunks = chunk_fulltext(FULLTEXT, "t")
    assert chunks[-1][3] == "refs"
    assert {c[2] for c in chunks if c[3] == "text"} >= {"2. Methods", "3. Results"}


def test_fts_query():
    assert fts_query("¿qué tengo sobre ventilación nocturna?") == '"ventilación" OR "nocturna"'
    assert fts_query('"night ventilation" AND cooling') == '"night ventilation" AND cooling'


def test_search_list_and_passages(lib, paper):
    processor(lib).process(paper)
    lib.write_paper(make_paper("otro2020x", doi="10.1/otro", title="Solar chimneys in Spain"))
    index = SearchIndex(lib)
    hits = index.search("ventilación nocturna", Filters())
    assert hits[0].citekey == paper and hits[0].places == "Hermosillo, Sonora, MX"
    assert hits[0].one_sentence.startswith("La ventilación nocturna")
    assert [h.citekey for h in index.list(Filters(country="mx"))] == [paper]
    assert index.list(Filters(study="numerico")) == []
    assert {h.citekey for h in index.list(Filters(year_from=2021, year_to=2021))} == {
        paper,
        "otro2020x",
    }
    found = index.passages("peak temperature", Filters(), paper=paper)
    assert found and found[0].page_start == 3
    assert index.passages("Smith thermal comfort", Filters()) == []  # references excluded
    assert index.passages("Smith thermal comfort", Filters(), include_refs=True)
    figure = index.passages("Gráfica", Filters())
    assert figure and figure[0].kind == "figure"
    assert index.update() == 0
    lib.remove_paper("otro2020x")
    assert index.update() == 1 and len(index.list(Filters())) == 1


def test_parse_years():
    assert Filters.parse_years("2019") == (2019, 2019)
    assert Filters.parse_years("2015..2024") == (2015, 2024)
    assert Filters.parse_years("..2020") == (None, 2020)
    with pytest.raises(ValueError):
        Filters.parse_years("hace poco")


# --- agents ---------------------------------------------------------------------


def test_agents_sync_preserves_user_content(home):
    agents = (home / "AGENTS.md").read_text()
    assert BEGIN in agents and END in agents
    (home / "AGENTS.md").write_text(agents + "\n## Mis reglas\nSiempre en español.\n")
    settings = home / ".claude" / "settings.json"
    data = json.loads(settings.read_text())
    data["permissions"]["allow"].append("Bash(git status)")
    settings.write_text(json.dumps(data, indent=2) + "\n")
    assert sync_agents(home) == []  # nothing of ours changed
    assert "Mis reglas" in (home / "AGENTS.md").read_text()
    merged = json.loads(settings.read_text())
    assert "Bash(git status)" in merged["permissions"]["allow"]
    assert "Bash(uv run sb:*)" in merged["permissions"]["allow"]
    assert len(merged["hooks"]["SessionStart"]) == 1
    assert (home / ".claude" / "skills" / "sb-consultar" / "SKILL.md").is_file()
    assert (home / "CLAUDE.md").read_text().strip() == "@AGENTS.md"


def test_agents_md_lists_every_command():
    from importlib.resources import files

    from typer.main import get_command

    text = files("second_brain.templates").joinpath("agents", "AGENTS.md").read_text()

    def paths(group, prefix):
        for name, command in group.commands.items():
            if not command.hidden:
                yield f"{prefix} {name}", command
                yield from (
                    paths(command, f"{prefix} {name}") if hasattr(command, "commands") else ()
                )

    missing = [path for path, _ in paths(get_command(cli.app), "sb") if f"`{path}" not in text]
    assert missing == [], f"faltan en templates/agents/AGENTS.md: {missing}"


# --- CLI ------------------------------------------------------------------------


def test_cli_process_pending_and_search(lib, paper, monkeypatch):
    from second_brain.scaffold import init_machine

    init_machine(lib.home, "test-machine")
    monkeypatch.setattr(cli, "get_backend", lambda *args, **kwargs: FakeBackend())
    runner = CliRunner()
    home = ["--home", str(lib.home)]
    result = runner.invoke(cli.app, [*home, "process", "--pending", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)[0]["outcome"] == "processed"
    result = runner.invoke(cli.app, [*home, "search", "night ventilation", "--json"])
    assert json.loads(result.output)[0]["citekey"] == paper
    result = runner.invoke(cli.app, [*home, "list", "--study", "experimental", "--json"])
    assert len(json.loads(result.output)) == 1
    assert "Nada que procesar" in runner.invoke(cli.app, [*home, "process", "--pending"]).output


def test_ingest_all_processes_pending_checks_and_commits(lib, paper, monkeypatch):
    import subprocess

    from second_brain.scaffold import init_machine

    init_machine(lib.home, "test-machine")
    for var in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        monkeypatch.setenv(var, "test")
    for var in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        monkeypatch.setenv(var, "test@example.org")
    subprocess.run(["git", "config", "core.hooksPath", "/dev/null"], cwd=lib.home, check=True)
    monkeypatch.setattr(cli, "get_backend", lambda *args, **kwargs: FakeBackend())
    result = CliRunner().invoke(cli.app, ["--home", str(lib.home), "ingest", "--all"])
    assert result.exit_code == 0, result.output
    assert lib.read_paper(paper).meta.status == "processed"
    log = subprocess.run(["git", "log", "--oneline"], cwd=lib.home, capture_output=True, text=True)
    assert "sb ingest --all" in log.stdout
    again = CliRunner().invoke(cli.app, ["--home", str(lib.home), "ingest", "--all"])
    assert "Nada pendiente" in again.output and "Sin cambios" in again.output
