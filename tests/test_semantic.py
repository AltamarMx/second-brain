import json
import re

import numpy as np
import pytest
from conftest import make_paper
from test_processing import TODAY
from typer.testing import CliRunner

from second_brain import cli
from second_brain.index import Filters, SearchIndex, _rrf
from second_brain.models import FullText

# Spanish and English words that mean the same map to the same dimension
CONCEPTS = {
    "ventilation": 0, "ventilación": 0, "night": 1, "nocturna": 1, "concrete": 2, "concreto": 2,
    "sargassum": 3, "sargazo": 3, "comfort": 4, "confort": 4, "carbon": 5, "carbono": 5,
}  # fmt: skip


class FakeEmbedder:
    id = "fake:concepts"

    def __init__(self):
        self.calls = 0

    def embed(self, texts):
        self.calls += 1
        matrix = np.zeros((len(texts), 8), dtype=np.float32)
        for row, text in enumerate(texts):
            for word in re.findall(r"\w+", text.lower()):
                if word in CONCEPTS:
                    matrix[row, CONCEPTS[word]] += 1
            matrix[row, 7] = 0.01
        return matrix / np.linalg.norm(matrix, axis=1, keepdims=True)


@pytest.fixture
def two_papers(lib):
    for key, doi, title, text in (
        (
            "garcia2021thermal",
            "10.1/a",
            "Night ventilation of houses",
            "Night ventilation cools houses.",
        ),
        (
            "rosas2025biomass",
            "10.1/b",
            "Sargassum concrete blocks",
            "Concrete with sargassum lowers carbon.",
        ),
    ):
        lib.write_paper(make_paper(key, doi=doi, title=title))
        lib.write_fulltext(
            FullText(citekey=key, source_pdf_sha256="x", extractor="x", extracted=TODAY, pages=1),
            f"<!-- page 1 -->\n{text}",
        )
    return lib


def test_rrf():
    fused = _rrf([["a", "b"], ["b", "c"]])
    assert max(fused, key=fused.get) == "b"


def test_semantic_finds_spanish_query_in_english_papers(two_papers):
    lexical = SearchIndex(two_papers)
    assert lexical.search("concreto con sargazo", Filters()) == []  # no shared words
    index = SearchIndex(two_papers, FakeEmbedder())
    hits = index.search("concreto con sargazo", Filters(), mode="semantic")
    assert hits[0].citekey == "rosas2025biomass"
    passages = index.passages("ventilación nocturna", Filters(), mode="hybrid")
    assert passages[0].citekey == "garcia2021thermal"


def test_vectors_are_incremental_and_follow_the_model(two_papers):
    embedder = FakeEmbedder()
    index = SearchIndex(two_papers, embedder)
    index.update()
    calls = embedder.calls
    index.update()
    assert embedder.calls == calls  # nothing new to embed
    other = FakeEmbedder()
    other.id = "fake:other"
    SearchIndex(two_papers, other).update()
    assert other.calls > 0  # model changed: everything re-embedded
    two_papers.remove_paper("rosas2025biomass")
    hits = SearchIndex(two_papers, other).search("concreto sargazo", Filters(), mode="semantic")
    assert [h.citekey for h in hits] == ["garcia2021thermal"]  # removed paper has no vectors


def test_filters_apply_to_semantic_results(two_papers):
    index = SearchIndex(two_papers, FakeEmbedder())
    assert index.search("concreto", Filters(year_from=2030), mode="semantic") == []


def test_eval_search_command(two_papers, tmp_path, monkeypatch):
    monkeypatch.setattr(
        cli,
        "open_index",
        lambda lib, semantic=True: SearchIndex(lib, FakeEmbedder() if semantic else None),
    )
    cases = tmp_path / "eval.jsonl"
    cases.write_text(
        json.dumps({"q": "concreto con sargazo", "expected": "rosas2025biomass"})
        + "\n"
        + json.dumps({"q": "night ventilation", "expected": "garcia2021thermal"})
        + "\n"
    )
    result = CliRunner().invoke(
        cli.app, ["--home", str(two_papers.home), "eval", "search", str(cases), "--json"]
    )
    report = json.loads(result.output)
    assert report["lexical"]["recall@5"] == 0.5
    assert report["semantic"]["recall@5"] == 1.0 and report["hybrid"]["recall@5"] == 1.0
