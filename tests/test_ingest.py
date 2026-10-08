import datetime as dt
import json
from pathlib import Path

import httpx
import pymupdf
import pytest
from conftest import make_project

from second_brain.checks import run_checks
from second_brain.config import load_config
from second_brain.ingest.metadata import MetadataClient
from second_brain.ingest.pipeline import IngestError, IngestOptions, Ingestor, publication_year

TODAY = dt.date(2026, 10, 4)
DOI = "10.1234/enb.2021.001"
TITLE = "Thermal performance of earth sheltered dwellings in hot dry climates"


def make_pdf(path: Path, title: str = TITLE, doi_line: str | None = f"https://doi.org/{DOI}",
             pages: int = 3, extra: str = "") -> Path:  # fmt: skip
    doc = pymupdf.open()
    for number in range(1, pages + 1):
        page = doc.new_page()
        if number == 1:
            page.insert_textbox(pymupdf.Rect(50, 60, 550, 140), title, fontsize=18)
            page.insert_text((50, 170), "Ana Garcia, John Smith", fontsize=10)
            if doi_line:
                page.insert_text((50, 190), doi_line, fontsize=9)
            if extra:
                page.insert_text((50, 210), extra, fontsize=9)
        body = f"Page {number} discusses passive cooling, thermal mass and night ventilation. " * 8
        page.insert_textbox(pymupdf.Rect(50, 240, 550, 780), body, fontsize=10)
    doc.save(path)
    return path


def crossref_message(doi: str = DOI, title: str = TITLE) -> dict:
    return {
        "DOI": doi,
        "type": "journal-article",
        "title": [title],
        "author": [{"family": "García", "given": "Ana", "ORCID": "https://orcid.org/0000-0001"}],
        "issued": {"date-parts": [[2021, 5]]},
        "container-title": ["Energy and Buildings"],
        "volume": "240",
        "page": "110987",
        "publisher": "Elsevier",
        "abstract": "<jats:title>Abstract</jats:title><jats:p>Earth-sheltered <i>houses</i>.</jats:p>",
    }


class FakeServices:
    """Crossref/DataCite stand-in: ``works`` maps DOI → message, ``search`` lists results."""

    def __init__(self, works=None, search=None, offline=False):
        self.works = works if works is not None else {DOI: crossref_message()}
        self.search = search or []
        self.offline = offline
        self.requests: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(str(request.url))
        if self.offline:
            raise httpx.ConnectError("sin red", request=request)
        path = request.url.path
        if request.url.host == "api.crossref.org" and path.startswith("/works/"):
            doi = path.removeprefix("/works/").lower()
            if doi in self.works:
                return httpx.Response(200, json={"message": self.works[doi]})
        elif request.url.host == "api.crossref.org" and path == "/works":
            return httpx.Response(200, json={"message": {"items": self.search}})
        return httpx.Response(404, json={})


def run(lib, services: FakeServices, paths=None, **options):
    client = MetadataClient(
        lib.cache_dir, client=httpx.Client(transport=httpx.MockTransport(services)), retries=0
    )
    ingestor = Ingestor(lib, load_config(lib.home), client, IngestOptions(today=TODAY, **options))
    return ingestor.run(paths if paths is not None else lib.inbox_pdfs())


def test_ingest_valid_pdf(lib):
    make_pdf(lib.inbox_dir / "articulo.pdf")
    [result] = run(lib, FakeServices())
    assert result.outcome == "ingested", result.message
    assert result.citekey == "garcia2021thermal"
    paper = lib.read_paper("garcia2021thermal").meta
    assert paper.doi == DOI and paper.status == "needs_processing"
    assert paper.pdf.pages == 3 and paper.pdf.original_filename == "articulo.pdf"
    assert paper.abstract == "Earth-sheltered houses."
    assert paper.authors[0].orcid == "0000-0001"
    fulltext = lib.read_fulltext("garcia2021thermal")
    assert fulltext.body.count("<!-- page ") == 3
    assert (lib.pdfs_dir / "garcia2021thermal.pdf").is_file()
    assert lib.inbox_pdfs() == []
    assert run_checks(lib.home).ok


def test_same_file_twice_is_a_duplicate(lib):
    pdf = make_pdf(lib.inbox_dir / "a.pdf")
    copy = lib.home / "copia.pdf"
    copy.write_bytes(pdf.read_bytes())
    run(lib, FakeServices())
    (lib.inbox_dir / "b.pdf").write_bytes(copy.read_bytes())
    [result] = run(lib, FakeServices())
    assert result.outcome == "duplicate"
    assert (lib.inbox_dir / "_duplicados" / "b.pdf").is_file()


def test_missing_local_pdf_is_relinked(lib):
    pdf = make_pdf(lib.inbox_dir / "a.pdf")
    content = pdf.read_bytes()
    run(lib, FakeServices())
    (lib.pdfs_dir / "garcia2021thermal.pdf").unlink()
    (lib.inbox_dir / "otra-maquina.pdf").write_bytes(content)
    services = FakeServices()
    [result] = run(lib, services)
    assert result.outcome == "relinked"
    assert (lib.pdfs_dir / "garcia2021thermal.pdf").is_file()
    assert services.requests == []  # recognised by hash, no network needed


def test_original_replaces_another_version(lib):
    original = make_pdf(lib.inbox_dir / "a.pdf").read_bytes()
    run(lib, FakeServices())
    local = lib.pdfs_dir / "garcia2021thermal.pdf"
    local.unlink()
    make_pdf(lib.inbox_dir / "manuscrito.pdf", extra="Accepted manuscript")
    [other] = run(lib, FakeServices())
    assert other.outcome == "relinked"
    assert "pdf_version_mismatch" in lib.read_paper("garcia2021thermal").meta.flags
    stand_in = local.read_bytes()
    (lib.inbox_dir / "original.pdf").write_bytes(original)
    [result] = run(lib, FakeServices())
    assert result.outcome == "relinked", result.message
    assert local.read_bytes() == original
    assert "pdf_version_mismatch" not in lib.read_paper("garcia2021thermal").meta.flags
    aside = lib.inbox_dir / "_duplicados" / "garcia2021thermal-otra-version.pdf"
    assert aside.read_bytes() == stand_in and lib.inbox_pdfs() == []
    (lib.inbox_dir / "otra-vez.pdf").write_bytes(original)
    [again] = run(lib, FakeServices())
    assert again.outcome == "duplicate"


def test_same_doi_other_file_is_a_duplicate(lib):
    make_pdf(lib.inbox_dir / "a.pdf")
    run(lib, FakeServices())
    make_pdf(lib.inbox_dir / "b.pdf", extra="Accepted manuscript")
    [result] = run(lib, FakeServices())
    assert result.outcome == "duplicate"
    assert "mismo DOI" in result.message


def test_doi_of_another_work_needs_review(lib):
    make_pdf(lib.inbox_dir / "a.pdf")
    services = FakeServices(works={DOI: crossref_message(title="Something completely different")})
    [result] = run(lib, services)
    assert result.outcome == "review"
    assert "doi_uncertain" in result.flags


def test_glued_doi_is_cut(lib):
    make_pdf(lib.inbox_dir / "a.pdf", doi_line=f"doi:{DOI}Received 3 May 2021")
    [result] = run(lib, FakeServices())
    assert result.outcome == "ingested"
    assert result.doi == DOI


def test_without_doi_title_search(lib):
    make_pdf(lib.inbox_dir / "a.pdf", doi_line=None)
    services = FakeServices(works={}, search=[crossref_message()])
    [result] = run(lib, services)
    assert result.outcome == "review"
    assert result.doi == DOI
    assert "doi_uncertain" in result.flags


def test_without_doi_and_no_match_uses_pdf(lib):
    make_pdf(lib.inbox_dir / "a.pdf", doi_line=None, extra="Conference paper, November 2019")
    [result] = run(lib, FakeServices(works={}))
    assert result.outcome == "review"
    paper = lib.read_paper(result.citekey).meta
    assert paper.provenance.metadata_source == "pdf"
    assert paper.year == 2019
    assert result.citekey == "anon2019thermal"


def test_pdf_outside_inbox_is_copied_not_moved(lib, tmp_path):
    (folder := tmp_path / "Zotero" / "storage" / "ABC").mkdir(parents=True)
    zotero = make_pdf(folder / "x.pdf")
    [result] = run(lib, FakeServices(), paths=[zotero])
    assert result.outcome == "ingested", result.message
    assert zotero.is_file()  # another program's file: left in place
    assert (lib.pdfs_dir / f"{result.citekey}.pdf").read_bytes() == zotero.read_bytes()
    [again] = run(lib, FakeServices(), paths=[zotero])
    assert again.outcome == "duplicate" and zotero.is_file()


@pytest.mark.parametrize(
    ("text", "year"),
    [
        ("Revista Ingeniería ISSN: 2007-3615 Vol. 19, núm. 3, 2018 pp. 1-12", 2018),
        ("Data for 1990-2010. Received 12 March 2017; accepted 5 January 2018", 2018),
        ("Periodo 1995 a 2005. © 2016 Elsevier Ltd. All rights reserved.", 2016),
        ("Tel. +52 55 5622 2019, correo x@unam.mx. Estudio realizado en 2015", 2015),
        ("ISBN 978-607-02-1234-5 Ciudad de México, 2014", 2014),
        ("doi: 10.1016/j.enbuild.2019.05.001 Energy and Buildings", None),
        ("Tesis 2020 presentada en marzo de 2021", 2021),
        ("Datos de 2010 y de 2012", 2010),
        ("Sin años aquí", None),
    ],
)
def test_publication_year(text, year):
    assert publication_year(text, TODAY) == year


def test_ssrn_id_on_the_page_gives_the_doi(lib):
    ssrn_doi = "10.2139/ssrn.4856145"
    make_pdf(
        lib.inbox_dir / "kyaw.pdf",
        doi_line="Electronic copy available at: https://ssrn.com/abstract=4856145",
    )
    services = FakeServices(works={ssrn_doi: crossref_message(doi=ssrn_doi)})
    [result] = run(lib, services)
    assert result.outcome == "ingested", result.message
    assert lib.read_paper(result.citekey).meta.doi == ssrn_doi


def test_forced_doi(lib):
    make_pdf(lib.inbox_dir / "a.pdf", doi_line=None)
    [result] = run(lib, FakeServices(), forced_doi=f"https://doi.org/{DOI.upper()}")
    assert result.outcome == "ingested"


def test_forced_doi_is_validated_even_if_title_not_on_page(lib):
    # documented in the agents' AGENTS.md: a hand-given DOI does not leave it in needs_review
    make_pdf(lib.inbox_dir / "a.pdf", title="Manuscript 1 with numbered 2 lines", doi_line=None)
    [result] = run(lib, FakeServices(), forced_doi=DOI)
    paper = lib.read_paper(result.citekey).meta
    assert (result.outcome, paper.status) == ("ingested", "needs_processing")
    assert "metadata_mismatch" in paper.flags


def test_forced_doi_requires_single_pdf(lib):
    make_pdf(lib.inbox_dir / "a.pdf")
    make_pdf(lib.inbox_dir / "b.pdf", title="Another title for a second test paper")
    with pytest.raises(IngestError):
        run(lib, FakeServices(), forced_doi=DOI)


def test_project_must_exist(lib):
    make_pdf(lib.inbox_dir / "a.pdf")
    with pytest.raises(IngestError, match="no existe"):
        run(lib, FakeServices(), project="tesis-doctoral")
    lib.write_project(make_project())
    [result] = run(lib, FakeServices(), project="tesis-doctoral")
    assert "tesis-doctoral" in lib.read_paper(result.citekey).meta.projects


def test_dry_run_changes_nothing(lib):
    make_pdf(lib.inbox_dir / "a.pdf")
    [result] = run(lib, FakeServices(), dry_run=True)
    assert result.outcome == "ingested"
    assert list(lib.papers_dir.glob("*.md")) == []
    assert len(lib.inbox_pdfs()) == 1


def test_broken_pdf_goes_to_errors(lib):
    (lib.inbox_dir / "roto.pdf").write_bytes(b"esto no es un pdf")
    [result] = run(lib, FakeServices())
    assert result.outcome == "error"
    assert (lib.inbox_dir / "_errores" / "roto.pdf").is_file()
    assert (lib.inbox_dir / "_errores" / "roto.motivo.txt").is_file()


def test_offline_keeps_pdf_in_inbox(lib):
    make_pdf(lib.inbox_dir / "a.pdf")
    [result] = run(lib, FakeServices(offline=True))
    assert result.outcome == "offline"
    assert len(lib.inbox_pdfs()) == 1


def test_responses_are_cached(lib):
    make_pdf(lib.inbox_dir / "a.pdf")
    run(lib, FakeServices(), dry_run=True)
    services = FakeServices()
    run(lib, services)
    assert services.requests == []
    cached = next((lib.cache_dir / "http").glob("*.json"))
    assert json.loads(cached.read_text())["url"].startswith("https://api.crossref.org")


def test_citekey_collision_gets_suffix(lib):
    make_pdf(lib.inbox_dir / "a.pdf")
    other = "10.1234/enb.2021.002"
    make_pdf(lib.inbox_dir / "b.pdf", title=TITLE + " revisited", doi_line=f"doi: {other}")
    services = FakeServices(
        works={DOI: crossref_message(), other: crossref_message(other, TITLE + " revisited")}
    )
    results = run(lib, services)
    assert [r.citekey for r in results] == ["garcia2021thermal", "garcia2021thermal-b"]
    assert "possible_duplicate" in results[1].flags
