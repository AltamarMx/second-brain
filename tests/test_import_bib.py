import datetime as dt

import httpx
from conftest import make_paper
from test_ingest import DOI, TITLE, FakeServices, crossref_message, make_pdf, run
from typer.testing import CliRunner

from second_brain.bibtex import render
from second_brain.checks import run_checks
from second_brain.cli import app
from second_brain.import_bib import import_bib, parse_authors, sanitize_key
from second_brain.ingest.metadata import MetadataClient

BIB = r"""
@article{garcia2021thermal,
  author = {Garc{\'\i}a, Ana and Smith, John},
  title = {{Thermal} performance of earth sheltered dwellings in hot dry climates},
  journal = {Energy and Buildings}, year = {2021}, doi = {https://doi.org/10.1234/ENB.2021.001},
  keywords = {thermal mass; passive cooling}
}
@inproceedings{Lopez:2019_vent,
  author = {L{\'o}pez-P{\'e}rez, L. A. and Juan de la Cruz and {Agencia Internacional de Energ{\'\i}a}},
  title = {Night ventilation in {M\'exico}},
  booktitle = {Windsor Conference}, year = 2014, pages = {12--18}
}
"""


def client(lib, services=None):
    transport = httpx.MockTransport(services or FakeServices())
    return MetadataClient(lib.cache_dir, client=httpx.Client(transport=transport), retries=0)


def write_bib(tmp_path, text=BIB):
    path = tmp_path / "refs.bib"
    path.write_text(text, encoding="utf-8")
    return path


def test_parse_authors():
    authors = parse_authors(
        r"L{\'o}pez-P{\'e}rez, L. A. and Juan de la Cruz and {Agencia Internacional} and Smith"
    )
    assert authors == [
        {"family": "López-Pérez", "given": "L. A."},
        {"family": "de la Cruz", "given": "Juan"},
        {"family": "Agencia Internacional", "given": None},
        {"family": "Smith", "given": None},
    ]


def test_sanitize_key():
    assert sanitize_key("Lopez:2019_vent") == "lopez-2019-vent"
    assert sanitize_key("Pérez2020") == "perez2020"


def test_import_keeps_keys_and_uses_crossref(lib, tmp_path):
    results = import_bib(lib, client(lib), write_bib(tmp_path), today=dt.date(2026, 10, 4))
    assert [(r.key, r.outcome, r.citekey) for r in results] == [
        ("garcia2021thermal", "imported", "garcia2021thermal"),
        ("Lopez:2019_vent", "imported", "lopez-2019-vent"),
    ]
    paper = lib.read_paper("garcia2021thermal").meta
    assert paper.status == "awaiting_pdf" and paper.provenance.metadata_source == "crossref"
    assert paper.container_title == "Energy and Buildings" and paper.tags == [
        "thermal mass",
        "passive cooling",
    ]
    other = lib.read_paper("lopez-2019-vent").meta
    assert other.aliases == ["Lopez:2019_vent"] and other.provenance.metadata_source == "bib"
    assert other.type == "paper-conference" and other.title == "Night ventilation in México"
    assert other.pages == "12-18" and other.authors[2].family == "Agencia Internacional de Energía"
    assert run_checks(lib.home).ok


def test_reimport_is_idempotent_and_adds_aliases(lib, tmp_path):
    path = write_bib(tmp_path)
    import_bib(lib, client(lib), path)
    again = import_bib(lib, client(lib), path)
    assert [r.outcome for r in again] == ["duplicate", "duplicate"]
    renamed = write_bib(tmp_path, BIB.replace("{garcia2021thermal,", "{Garcia_2021,"))
    [alias, _] = import_bib(lib, client(lib), renamed)
    assert alias.outcome == "alias"
    assert lib.read_paper("garcia2021thermal").meta.aliases == ["Garcia_2021"]


def test_conflicting_key(lib, tmp_path):
    lib.write_paper(
        make_paper("garcia2021thermal", doi="10.9/otro", title="Algo totalmente distinto")
    )
    [result, _] = import_bib(lib, client(lib, FakeServices(works={})), write_bib(tmp_path))
    assert result.outcome == "conflict"


def test_bib_output_includes_aliases(lib, tmp_path):
    import_bib(lib, client(lib), write_bib(tmp_path))
    text = render([lib.read_paper("lopez-2019-vent").meta])
    assert "@inproceedings{lopez-2019-vent," in text and "@inproceedings{Lopez:2019_vent," in text
    tex = tmp_path / "main.tex"
    tex.write_text(r"\cite{Lopez:2019_vent}")
    result = CliRunner().invoke(app, ["--home", str(lib.home), "bib", "--from-tex", str(tex)])
    assert "@inproceedings{Lopez:2019_vent," in result.output
    assert "{lopez-2019-vent," not in result.output


def test_pdfs_attach_after_import(lib, tmp_path):
    services = FakeServices(works={DOI: crossref_message()})
    import_bib(lib, client(lib, services), write_bib(tmp_path))
    make_pdf(lib.inbox_dir / "con-doi.pdf")
    make_pdf(lib.inbox_dir / "sin-doi.pdf", title="Night ventilation in México", doi_line=None,
             extra="López-Pérez, Windsor Conference 2014")  # fmt: skip
    results = run(lib, FakeServices(works={DOI: crossref_message()}))
    assert {(r.source, r.outcome, r.citekey) for r in results} == {
        ("con-doi.pdf", "attached", "garcia2021thermal"),
        ("sin-doi.pdf", "attached", "lopez-2019-vent"),
    }
    assert lib.read_paper("lopez-2019-vent").meta.status == "needs_processing"
    assert TITLE  # same fixtures as test_ingest


def test_duplicate_alias_is_an_error(lib):
    lib.write_paper(make_paper("a2020x", doi="10.1/a", aliases=["X:1"]))
    lib.write_paper(make_paper("b2020x", doi="10.1/b", aliases=["X:1"]))
    assert any("alias" in i.message for i in run_checks(lib.home).errors)
