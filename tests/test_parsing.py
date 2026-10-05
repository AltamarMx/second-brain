import pytest

from second_brain.citekey import make_citekey, title_word
from second_brain.ingest.doi import doi_variants, find_dois, normalize_doi
from second_brain.reading import parse_page_range, select_pages, select_section


def test_normalize_doi():
    assert normalize_doi(" https://doi.org/10.1016%2FJ.X ") == "10.1016/j.x"
    assert normalize_doi("doi:10.1/A") == "10.1/a"


def test_find_dois_prefers_labelled_and_handles_wrapping():
    text = "see 10.9999/ref.1 in refs\nhttps://doi.org/10.1016/j.buildenv.\n2018.12.011 Received"
    assert find_dois(text)[0] == "10.1016/j.buildenv.2018.12.011"
    assert "10.9999/ref.1" in find_dois(text)


def test_doi_variants():
    assert doi_variants("10.1016/j.x.2021.110987.") == ["10.1016/j.x.2021.110987"]
    assert doi_variants("10.1016/j.x.2021.110987Received") == [
        "10.1016/j.x.2021.110987received",
        "10.1016/j.x.2021.110987",
    ]
    assert doi_variants("10.1002/(SICI)1097(199)") == ["10.1002/(sici)1097(199)"]
    assert doi_variants("10.1000/abc)") == ["10.1000/abc"]


def test_citekeys():
    assert make_citekey("García-López", 2021, "The thermal mass", set()) == "garcialopez2021thermal"
    assert make_citekey("van der Berg", 2020, "On a model", set()) == "vanderberg2020model"
    assert make_citekey("Müller", None, None, set()) == "mullernd"
    assert make_citekey(None, 2019, "Análisis del ciclo", set()) == "anon2019analisis"
    assert make_citekey("Ng", 2020, "x", {"ng2020", "ng2020-b"}) == "ng2020-c"
    assert make_citekey("Universidad Autónoma de Baja California", 2024, "Aproximación", set()) == (
        "universidad2024aproximacion"
    )
    assert title_word("<i>CO2</i> emissions of 2020 buildings") == "co2"


def test_page_ranges():
    assert parse_page_range("5", 10) == (5, 5)
    assert parse_page_range("4-6", 10) == (4, 6)
    assert parse_page_range("8-", 10) == (8, 10)
    with pytest.raises(ValueError):
        parse_page_range("6-4", 10)


BODY = """<!-- page 1 -->
# Title
**1.** **Introduction**
Intro text.

<!-- page 2 -->
2. Study methodology
Method text.
2.1 Survey
Survey text.
3. Results
Results text.
References
[1] A ref."""


def test_select_pages():
    assert select_pages(BODY, "2").startswith("<!-- page 2 -->\n2. Study")


def test_select_section_numbered_and_nested():
    section = select_section(BODY, "methodology")
    assert "Survey text." in section and "Results text." not in section
    assert select_section(BODY, "survey").endswith("Survey text.")
    assert select_section(BODY, "introduction").endswith("Intro text.\n\n<!-- page 2 -->")
    assert select_section(BODY, "references").endswith("[1] A ref.")
    assert select_section(BODY, "discussion") is None
