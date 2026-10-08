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


IPCC_DOI = "10.1017/9781009157926.001"
IPCC_BIB = r"""
@techreport{ipcc2022spm,
  author = {{IPCC}}, title = {Summary for Policymakers}, year = {2022},
  institution = {Cambridge University Press}, pages = {3--48}, doi = {10.1017/9781009157926.001}
}
"""


def ipcc_services():
    message = {"DOI": IPCC_DOI, "type": "book-chapter", "title": ["Summary for Policymakers"],
               "author": [], "issued": {"date-parts": [[2023]]}, "publisher": "Cambridge University Press",
               "container-title": ["Climate Change 2022: Mitigation of Climate Change"]}  # fmt: skip
    return FakeServices(works={IPCC_DOI: message})


def test_crossref_never_erases_bib_fields(lib, tmp_path):
    bib = write_bib(tmp_path, IPCC_BIB)
    [result] = import_bib(lib, client(lib, ipcc_services()), bib, today=dt.date(2026, 10, 4))
    paper = lib.read_paper(result.citekey).meta
    assert [a.family for a in paper.authors] == ["IPCC"]  # Crossref has no authors
    assert paper.pages == "3-48"  # nor pages
    assert paper.year == 2023 and paper.doi == IPCC_DOI  # what Crossref has, wins
    assert paper.container_title == "Climate Change 2022: Mitigation of Climate Change"
    assert paper.provenance.metadata_source == "crossref"


def test_prefer_bib(lib, tmp_path):
    bib = write_bib(tmp_path, IPCC_BIB)
    [result] = import_bib(
        lib, client(lib, ipcc_services()), bib, prefer_bib=True, today=dt.date(2026, 10, 4)
    )
    paper = lib.read_paper(result.citekey).meta
    assert (paper.year, paper.type, paper.doi) == (2022, "report", IPCC_DOI)  # the .bib wins
    assert paper.container_title == "Climate Change 2022: Mitigation of Climate Change"  # a gap
    assert paper.provenance.metadata_source == "bib+crossref"
    result = CliRunner().invoke(
        app, ["--home", str(lib.home), "import", "bib", str(bib), "--prefer-bib", "--dry-run"]
    )
    assert result.exit_code == 0, result.output


ZOTERO_BIB = r"""
@article{garcia2021thermal,
  author = {Garc{\'\i}a, Ana}, title = {Thermal performance of earth sheltered dwellings in hot dry climates},
  journal = {Energy and Buildings}, year = {2021}, doi = {10.1234/enb.2021.001},
  file = {Full Text PDF:files/12/Garcia - 2021 - Thermal.pdf:application/pdf;Snapshot:files/12/page.html:text/html}
}
@techreport{nrel2020mexico,
  author = {{NREL}}, title = {Solar resource assessment for Mexico}, year = {2020},
  file = {ZOTERO/storage/AB12/Arduin 2022.pdf}
}
"""


def zotero_export(tmp_path):
    folder = tmp_path / "export"
    (folder / "files" / "12").mkdir(parents=True)
    (folder / "ZOTERO" / "storage" / "AB12").mkdir(parents=True)
    good = make_pdf(folder / "files" / "12" / "Garcia - 2021 - Thermal.pdf")
    # Zotero hung an unrelated paper on the NREL report
    wrong = make_pdf(folder / "ZOTERO" / "storage" / "AB12" / "Arduin 2022.pdf",
                     title="Urban heat islands in Buenos Aires", doi_line=None)  # fmt: skip
    bib = folder / "export.bib"
    bib.write_text(ZOTERO_BIB, encoding="utf-8")
    return bib, good, wrong


def test_import_copies_the_pdfs_of_a_zotero_export(lib, tmp_path):
    bib, good, wrong = zotero_export(tmp_path)
    dry = import_bib(lib, client(lib), bib, dry_run=True, today=dt.date(2026, 10, 4))
    assert [r.pdf for r in dry] == [str(good), str(wrong)]
    assert list(lib.pdfs_dir.glob("*.pdf")) == []
    results = import_bib(lib, client(lib), bib, today=dt.date(2026, 10, 4))
    by_key = {r.key: r for r in results}
    assert by_key["garcia2021thermal"].pdf_outcome == "attached"
    paper = lib.read_paper("garcia2021thermal").meta
    assert paper.status == "needs_processing" and paper.pdf is not None
    assert (lib.pdfs_dir / "garcia2021thermal.pdf").is_file() and good.is_file()  # copied
    nrel = by_key["nrel2020mexico"]
    assert nrel.pdf_outcome == "error" and "no aparece" in nrel.message
    assert lib.read_paper("nrel2020mexico").meta.pdf is None and wrong.is_file()
    output = CliRunner().invoke(app, ["--home", str(lib.home), "import", "bib", str(bib)]).output
    assert "ya existían" in output


def test_ingest_with_key_attaches_to_that_record(lib, tmp_path):
    lib.write_paper(
        make_paper("informe2020x", doi=None, title="Informe de energía", status="awaiting_pdf")
    )
    pdf = make_pdf(tmp_path / "x.pdf", doi_line=None)  # its title is another one
    [result] = run(lib, FakeServices(), paths=[pdf], key="informe2020x")
    assert result.outcome == "attached" and "no aparece" in result.message
    paper = lib.read_paper("informe2020x").meta
    assert paper.pdf is not None and "metadata_mismatch" in paper.flags
    assert paper.status == "needs_processing" and pdf.is_file()
    [again] = run(lib, FakeServices(), paths=[pdf], key="informe2020x")
    assert again.outcome == "duplicate"
    lib.write_paper(make_paper("otro2021x", doi=None, title="Otro", status="awaiting_pdf"))
    [taken] = run(lib, FakeServices(), paths=[pdf], key="otro2021x")
    assert taken.outcome == "error" and "ya es de informe2020x" in taken.message
