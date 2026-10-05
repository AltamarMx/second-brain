import json
from types import SimpleNamespace

import pytest
from conftest import make_paper
from test_ingest import make_pdf
from test_processing import FULLTEXT, TODAY, FakeBackend
from typer.testing import CliRunner

from second_brain.checks import run_checks
from second_brain.citations import build_graph, graph_html, missing_works
from second_brain.cli import app
from second_brain.config import load_config
from second_brain.index import Filters, SearchIndex
from second_brain.ingest.metadata import crossref_updates, flags_from_updates
from second_brain.models import FullText
from second_brain.processing import Processor
from second_brain.retractions import check_updates
from second_brain.supplements import SupplementError, attach

runner = CliRunner()


def cli(lib, *args):
    return runner.invoke(app, ["--home", str(lib.home), *args])


# --- reading status ---------------------------------------------------------------


def test_reading_status_and_filter(lib):
    lib.write_paper(make_paper())
    lib.write_paper(make_paper("otro2020x", doi="10.1/otro"))
    assert (
        cli(lib, "read", "garcia2021thermal", "--status", "leido", "--rating", "4").exit_code == 0
    )
    paper = lib.read_paper("garcia2021thermal").meta
    assert (paper.reading, paper.rating) == ("leido", 4)
    hits = SearchIndex(lib).list(Filters(reading="leido"))
    assert [h.citekey for h in hits] == ["garcia2021thermal"]
    assert cli(lib, "read", "garcia2021thermal", "--status", "visto").exit_code == 2
    cli(lib, "read", "garcia2021thermal", "--clear")
    assert lib.read_paper("garcia2021thermal").meta.reading is None


# --- retractions ------------------------------------------------------------------

RETRACTED = {
    "updated-by": [
        {
            "DOI": "10.1/corr",
            "type": "correction",
            "source": "publisher",
            "updated": {"date-parts": [[2004, 3, 6]]},
        },
        {
            "DOI": "10.1/retr",
            "type": "retraction",
            "source": "retraction-watch",
            "updated": {"date-parts": [[2010, 2]]},
        },
    ]
}


def test_crossref_updates_and_flags():
    updates = crossref_updates(RETRACTED)
    assert [u["type"] for u in updates] == ["correction", "retraction"]
    assert updates[1]["date"] == "2010-02-01"
    assert flags_from_updates(updates) == ["retracted"]
    assert flags_from_updates([{"type": "expression_of_concern"}]) == ["expression_of_concern"]


def test_check_updates_marks_retracted(lib):
    lib.write_paper(make_paper())
    client = SimpleNamespace(crossref_work=lambda doi, refresh=False: RETRACTED)
    [notice] = check_updates(lib, client)
    assert notice.retracted and len(notice.new) == 2
    paper = lib.read_paper("garcia2021thermal").meta
    assert "retracted" in paper.flags and paper.updates[1].doi == "10.1/retr"
    assert check_updates(lib, client)[0].new == []  # already known


# --- citation graph ---------------------------------------------------------------


def test_citation_graph(lib):
    lib.write_paper(make_paper("a2020x", doi="10.1/a"))
    lib.write_paper(make_paper("b2021x", doi="10.1/b"))
    lib.write_paper(make_paper("c2022x", doi="10.1/c"))
    references = {
        "10.1/b": [
            {"DOI": "10.1/A"},
            {"DOI": "10.9/ext", "article-title": "External work", "year": "2001"},
        ],
        "10.1/c": [
            {"DOI": "10.1/a"},
            {"DOI": "10.1/b"},
            {"DOI": "10.9/ext"},
            {"unstructured": "sin DOI"},
        ],
    }
    client = SimpleNamespace(
        crossref_work=lambda doi, refresh=False: {"reference": references.get(doi, [])}
    )
    graph = build_graph(lib, client)
    assert graph.cites["c2022x"] == ["a2020x", "b2021x"]
    assert sorted(graph.cited_by["a2020x"]) == ["b2021x", "c2022x"]
    assert graph.without_data == ["a2020x"]
    [work] = missing_works(graph, min_count=2)
    assert (work.doi, work.title, sorted(work.cited_by)) == (
        "10.9/ext",
        "External work",
        ["b2021x", "c2022x"],
    )
    page = graph_html(graph, {"a2020x": "A", "b2021x": "B", "c2022x": "C"})
    assert (
        "vis-network" in page and '"from": "c2022x", "to": "a2020x"' in page and "10.9/ext" in page
    )


# --- supplements ------------------------------------------------------------------


def test_attach_supplement_is_searchable_and_deduplicated(lib, tmp_path):
    lib.write_paper(make_paper())
    pdf = make_pdf(
        tmp_path / "datos.pdf",
        title="Supplementary monitoring data of sargassum blocks",
        doi_line=None,
    )
    content = pdf.read_bytes()
    supplement = attach(lib, load_config(lib.home), "garcia2021thermal", pdf, label="Datos")
    assert supplement.id == "s1" and not pdf.exists()
    assert lib.supplement_pdf("garcia2021thermal", "s1").is_file()
    assert lib.read_paper("garcia2021thermal").meta.supplements[0].label == "Datos"
    found = SearchIndex(lib).passages("sargassum monitoring", Filters())
    assert found and found[0].kind == "supplement" and found[0].section.startswith("Suplemento s1")
    assert run_checks(lib.home).ok
    copy = tmp_path / "otra.pdf"
    copy.write_bytes(content)
    with pytest.raises(SupplementError, match="ya es el suplemento s1"):
        attach(lib, load_config(lib.home), "garcia2021thermal", copy)
    result = cli(lib, "text", "garcia2021thermal", "--supplement", "s1")
    assert "sargassum" in result.output.lower()


def test_supplement_dropped_in_inbox_is_a_duplicate(lib, tmp_path):
    from test_ingest import FakeServices, run

    lib.write_paper(make_paper())
    pdf = make_pdf(
        tmp_path / "s.pdf", title="Supplementary material for the thermal paper", doi_line=None
    )
    content = pdf.read_bytes()
    attach(lib, load_config(lib.home), "garcia2021thermal", pdf)
    (lib.inbox_dir / "s.pdf").write_bytes(content)
    [result] = run(lib, FakeServices(works={}))
    assert result.outcome == "duplicate" and "suplemento s1" in result.message


# --- extra classification fields ----------------------------------------------------


class ExtraBackend(FakeBackend):
    def run(self, prompt, schema, stdin="", images=None):
        output, model = super().run(prompt, schema, stdin, images)
        assert "clima (Clima (Köppen))" in prompt
        classification = {
            "study_type": "experimental",
            "locations": [],
            "extra": {"clima": "BWh", "edificacion": ["vivienda", "nave espacial"]},
        }
        if "classification" in output:
            output["classification"] = classification
        else:
            output = {"classification": classification}
        return output, model


def configure_extra(lib):
    config = lib.home / "config.toml"
    config.write_text(
        config.read_text()
        + '\n[classification.clima]\nlabel = "Clima (Köppen)"\ndescription = "Köppen"\n'
        '\n[classification.edificacion]\nlabel = "Edificación"\ndescription = "uso"\n'
        'values = ["vivienda", "oficinas"]\nmultiple = true\n'
    )


def test_extra_fields_process_reclassify_and_filter(lib):
    configure_extra(lib)
    lib.write_paper(make_paper())
    lib.write_fulltext(
        FullText(
            citekey="garcia2021thermal",
            source_pdf_sha256="x",
            extractor="x",
            extracted=TODAY,
            pages=3,
        ),
        FULLTEXT,
    )
    processor = Processor(lib, load_config(lib.home), ExtraBackend(), "test-machine", TODAY)
    processor.process("garcia2021thermal", figures=False)
    extra = lib.read_paper("garcia2021thermal").meta.classification.extra
    assert extra == {"clima": "BWh", "edificacion": ["vivienda"]}  # out-of-vocabulary value dropped
    assert processor.reclassify("garcia2021thermal").outcome == "processed"
    paper = lib.read_paper("garcia2021thermal").meta
    assert paper.provenance.classification.prompt == "classify.v1"
    assert paper.provenance.process is not None  # summary kept
    hits = SearchIndex(lib).list(Filters(extra=("clima=bwh",)))
    assert [h.citekey for h in hits] == ["garcia2021thermal"]
    assert SearchIndex(lib).list(Filters(extra=("edificacion=oficinas",))) == []
    assert run_checks(lib.home).ok


def test_check_flags_values_outside_vocabulary(lib):
    configure_extra(lib)
    lib.write_paper(
        make_paper(classification={"extra": {"edificacion": ["castillo"], "inventado": "x"}})
    )
    report = run_checks(lib.home)
    assert any("castillo" in i.message for i in report.errors)
    assert any("inventado" in i.message for i in report.issues if i.level == "warning")


def test_refs_cli_html(lib, tmp_path, monkeypatch):
    lib.write_paper(make_paper("a2020x", doi="10.1/a"))
    monkeypatch.setattr(
        "second_brain.ingest.metadata.MetadataClient.crossref_work",
        lambda self, doi, refresh=False: {"reference": []},
    )
    out = tmp_path / "grafo.html"
    result = cli(lib, "refs", "--html", str(out))
    assert result.exit_code == 0 and "a2020x" in out.read_text()
    assert json.loads(cli(lib, "refs", "--json").output)["without_data"] == ["a2020x"]
