import datetime as dt
import json
from types import SimpleNamespace

import pytest
from conftest import make_paper, make_project
from typer.testing import CliRunner

from second_brain import bibtex
from second_brain.checks import run_checks
from second_brain.cli import app
from second_brain.edit import EditError, edit_paper, lookup_doi, parse_author
from second_brain.models import FigureSet, FullText, Supplement, SupplementText

TODAY = dt.date(2026, 10, 7)
runner = CliRunner()


def anon_paper(lib, citekey="anon2007consumo", **overrides):
    """A record made from a PDF without DOI, with everything that must survive an edit."""
    sha = "a" * 64
    fields = {
        "doi": None, "authors": [], "title": "Consumo de energía en viviendas", "year": 2007,
        "status": "needs_review", "flags": ["ocr", "possible_duplicate"], "reading": "leyendo",
        "rating": 4, "projects": {"tesis": {"added": TODAY}},
        "supplements": [Supplement(id="s1", sha256="b" * 64, pages=2, size_bytes=10)],
        "provenance": {"metadata_source": "pdf"},
    }  # fmt: skip
    paper = make_paper(citekey, **{**fields, **overrides})
    lib.write_project(make_project("tesis"))
    lib.write_paper(paper, "Resumen hecho a mano.\n")
    lib.write_fulltext(
        FullText(citekey=citekey, source_pdf_sha256=sha, extractor="x", extracted=TODAY, pages=3),
        "<!-- page 1 -->\nTexto",
    )
    lib.write_figure_set(FigureSet(citekey=citekey), "Fig. 1")
    lib.write_supplement(
        SupplementText(citekey=citekey, id="s1", source_pdf_sha256="b" * 64, extractor="x",
                       extracted=TODAY, pages=2),
        "Datos",
    )  # fmt: skip
    lib.notes_dir.mkdir(parents=True, exist_ok=True)
    (lib.notes_dir / f"{citekey}.md").write_text("mis notas\n")
    lib.pdfs_dir.mkdir(parents=True, exist_ok=True)
    (lib.pdfs_dir / f"{citekey}.pdf").write_bytes(b"%PDF")
    (lib.pdfs_dir / f"{citekey}--s1.pdf").write_bytes(b"%PDF s1")
    return paper


def test_parse_author():
    assert parse_author("García Pérez, Ana") == {"family": "García Pérez", "given": "Ana"}
    assert parse_author("IPCC") == {"family": "IPCC", "given": None}
    with pytest.raises(EditError):
        parse_author(", Ana")


def test_edit_keeps_everything_else_and_marks_reviewed(lib):
    anon_paper(lib)
    result = edit_paper(
        lib, "anon2007consumo",
        {"authors": [parse_author("Huelsz, Guadalupe")], "year": 2018, "container_title": "Ingeniería"},
    )  # fmt: skip
    assert result.changed == ["authors", "year", "container_title"] and result.reviewed
    assert result.old_citekey is None  # the citekey never changes without --rekey
    doc = lib.read_paper("anon2007consumo")
    paper = doc.meta
    assert paper.authors[0].family == "Huelsz" and paper.year == 2018
    assert paper.status == "needs_processing" and paper.flags == ["ocr", "possible_duplicate"]
    assert paper.provenance.metadata_source == "manual"
    assert (paper.reading, paper.rating, list(paper.projects)) == ("leyendo", 4, ["tesis"])
    assert doc.body.strip() == "Resumen hecho a mano."


def test_edit_without_changes_confirms_a_review(lib):
    anon_paper(lib, flags=["doi_uncertain"])
    result = edit_paper(lib, "anon2007consumo", {})
    assert result.changed == [] and result.reviewed
    paper = lib.read_paper("anon2007consumo").meta
    assert paper.status == "needs_processing" and paper.flags == []
    assert paper.provenance.metadata_source == "pdf"  # nothing was edited


def test_rekey_renames_every_file_and_keeps_the_alias(lib):
    anon_paper(lib)
    result = edit_paper(
        lib, "anon2007consumo",
        {"authors": [parse_author("Huelsz, Guadalupe")], "year": 2018}, rekey=True,
    )  # fmt: skip
    new = "huelsz2018consumo"
    assert (result.old_citekey, result.citekey) == ("anon2007consumo", new)
    paper = lib.read_paper(new).meta
    assert paper.citekey == new and paper.aliases == ["anon2007consumo"]
    assert lib.read_fulltext(new).meta.citekey == new
    assert lib.read_figure_set(new).meta.citekey == new
    assert lib.read_supplement(new, "s1").meta.citekey == new
    assert (lib.notes_dir / f"{new}.md").read_text() == "mis notas\n"
    assert (lib.pdfs_dir / f"{new}.pdf").is_file() and (lib.pdfs_dir / f"{new}--s1.pdf").is_file()
    leftovers = [p for p in lib.home.rglob("anon2007consumo*") if ".cache" not in p.parts]
    assert leftovers == []
    entries = bibtex.render([paper])  # the old key still exports, for .tex files
    assert "{huelsz2018consumo," in entries and "{anon2007consumo," in entries
    assert run_checks(lib.home).ok


def test_rekey_to_a_chosen_key_and_conflicts(lib):
    anon_paper(lib)
    lib.write_paper(make_paper("otro2020x", doi="10.1/otro", aliases=["tomado2019"]))
    with pytest.raises(EditError, match="ya lo usa"):
        edit_paper(lib, "anon2007consumo", {}, new_key="tomado2019")
    with pytest.raises(EditError, match="ya es de otro2020x"):
        edit_paper(lib, "anon2007consumo", {"doi": "https://doi.org/10.1/OTRO"})
    with pytest.raises(EditError, match="tipo desconocido"):
        edit_paper(lib, "anon2007consumo", {"type": "articulo"})
    result = edit_paper(lib, "anon2007consumo", {}, new_key="consumo2018")
    assert result.citekey == "consumo2018" and lib.paper_path("consumo2018").is_file()


def test_dry_run_writes_nothing(lib):
    anon_paper(lib)
    before = {p: p.read_bytes() for p in lib.home.rglob("*") if p.is_file()}
    result = edit_paper(lib, "anon2007consumo", {"year": 2018}, rekey=True, dry_run=True)
    assert result.changed == ["year"] and result.citekey == "anon2018consumo"
    assert {p: p.read_bytes() for p in lib.home.rglob("*") if p.is_file()} == before


def test_from_doi_only_fills_what_crossref_has(lib):
    anon_paper(lib, authors=[{"family": "IPCC"}], pages="1-30")
    message = {
        "DOI": "10.1017/9781009157926.001", "type": "report", "title": ["Summary for Policymakers"],
        "author": [], "issued": {"date-parts": [[2023]]}, "publisher": "Cambridge University Press",
    }  # fmt: skip
    client = SimpleNamespace(crossref_work=lambda doi: message, datacite_work=lambda doi: None)
    fields, source = lookup_doi(client, "10.1017/9781009157926.001")
    result = edit_paper(lib, "anon2007consumo", {"year": 2022}, doi_fields=fields, source=source)
    paper = lib.read_paper("anon2007consumo").meta
    assert paper.doi == "10.1017/9781009157926.001" and paper.title == "Summary for Policymakers"
    assert paper.authors[0].family == "IPCC" and paper.pages == "1-30"  # Crossref had none
    assert paper.year == 2022  # what you write wins over Crossref
    assert paper.type == "report" and paper.provenance.metadata_source == "crossref"
    assert "doi" in result.changed
    missing = SimpleNamespace(crossref_work=lambda doi: None, datacite_work=lambda doi: None)
    with pytest.raises(EditError, match="no existe"):
        lookup_doi(missing, "10.1/nada")


def test_cli_edit(lib):
    anon_paper(lib)
    home = ["--home", str(lib.home)]
    result = runner.invoke(app, [*home, "edit", "anon2007consumo", "--author", "Huelsz, Guadalupe",
                                 "--year", "2018", "--rekey", "--json"])  # fmt: skip
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["citekey"] == "huelsz2018consumo" and data["old_citekey"] == "anon2007consumo"
    result = runner.invoke(app, [*home, "edit", "huelsz2018consumo"])
    assert result.exit_code == 0 and "nada que cambiar" in result.output
    result = runner.invoke(app, [*home, "edit", "huelsz2018consumo", "--type", "x"])
    assert result.exit_code == 1 and "tipo desconocido" in result.output
