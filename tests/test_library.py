import re

import pytest
from conftest import make_paper, make_project

from second_brain.library import (
    FrontmatterError,
    InvalidDocument,
    NewerSchemaError,
    dump_frontmatter,
    split_frontmatter,
)
from second_brain.models import Paper


def test_roundtrip_is_byte_identical(lib):
    paper = make_paper(
        abstract="Primera línea del resumen.\nSegunda línea con acentos: México, Müller.",
        classification={
            "study_type": "ambos",
            "locations": [{"country": "MX", "region": "Sonora"}],
        },
    )
    body = "## En una frase\nUn resumen."
    path = lib.write_paper(paper, body)
    first = path.read_text(encoding="utf-8")

    doc = lib.read_paper("garcia2021thermal")
    assert doc.meta == paper
    assert doc.body == body
    lib.write_paper(doc.meta, doc.body)
    assert path.read_text(encoding="utf-8") == first


def test_dump_uses_block_style_and_unicode(lib):
    text = dump_frontmatter(make_paper(abstract="línea uno\nlínea dos"))
    assert "abstract: |" in text  # block style, also for "|-"
    assert "García" in text
    assert text.startswith("---\n")


def test_atomic_write_leaves_no_temp_files(lib):
    lib.write_paper(make_paper())
    assert [p.name for p in lib.papers_dir.iterdir() if p.name != ".gitkeep"] == [
        "garcia2021thermal.md"
    ]


def test_newer_schema_is_refused(lib):
    lib.write_paper(make_paper())
    path = lib.paper_path("garcia2021thermal")
    path.write_text(re.sub(r"schema_version: \d+", "schema_version: 99", path.read_text()))
    with pytest.raises(NewerSchemaError):
        lib.read_paper("garcia2021thermal")


def test_invalid_documents_are_reported_not_raised(lib):
    (lib.papers_dir / "roto.md").write_text("sin frontmatter")
    (lib.papers_dir / "campo.md").write_text("---\ncitekey: campo\ntitulo: x\n---\n")
    docs = list(lib.iter_papers())
    assert all(isinstance(d, InvalidDocument) for d in docs)
    assert len(docs) == 2


def test_split_frontmatter_requires_delimiters():
    with pytest.raises(FrontmatterError):
        split_frontmatter("---\ntitle: x\n")


def test_unknown_fields_are_rejected():
    with pytest.raises(ValueError):
        Paper.model_validate({**make_paper().model_dump(), "titel": "typo"})


def test_project_roundtrip(lib):
    project = make_project(kind="tesis")
    lib.write_project(project, "Descripción.")
    doc = lib.read_project("tesis-doctoral")
    assert doc.meta == project
    assert doc.body == "Descripción."


def test_inbox_lists_only_top_level_pdfs(lib):
    (lib.inbox_dir / "a.pdf").write_bytes(b"%PDF")
    (lib.inbox_dir / "B.PDF").write_bytes(b"%PDF")
    (lib.inbox_dir / "_errores").mkdir()
    (lib.inbox_dir / "_errores" / "c.pdf").write_bytes(b"%PDF")
    assert [p.name for p in lib.inbox_pdfs()] == ["B.PDF", "a.pdf"]


def test_repeated_values_have_no_yaml_aliases():
    import datetime as dt

    from second_brain.models import LlmProvenance, Provenance

    day = dt.date(2026, 10, 4)
    llm = {"backend": "claude", "model": "m", "prompt": "p", "date": day}
    paper = make_paper(
        provenance=Provenance(process=LlmProvenance(**llm), figures=LlmProvenance(**llm))
    )
    text = dump_frontmatter(paper)
    assert "&id" not in text and "*id" not in text
