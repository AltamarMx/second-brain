import pymupdf
import pytest

from second_brain.ingest.extract import extract


def cover(path, lines, metadata_title=None, blank_first_page=False):
    """A PDF whose first page with text has ``lines`` of ``(font size, text)``."""
    doc = pymupdf.open()
    if blank_first_page:
        doc.new_page()
    page = doc.new_page()
    y = 80.0
    for size, text in lines:
        page.insert_text((40, y), text, fontsize=size)
        y += size * 1.8
    page.insert_text((40, 700), "Body text of the document. " * 3, fontsize=10)
    if metadata_title:
        doc.set_metadata({"title": metadata_title})
    doc.save(path)
    return path


@pytest.mark.parametrize(
    ("lines", "title"),
    [
        (  # SSRN stamp
            [(30, "Preprint not peer reviewed"), (20, "Window shading and cooling"), (11, "Kyaw et al.")],
            "Window shading and cooling",
        ),
        (  # thesis cover: institution header and the author's name in the title's type
            [(24, "UNIVERSIDAD AUTÓNOMA DE NUEVO LEÓN"), (20, "Confort térmico en viviendas"),
             (20, "A Dissertation Presented by"), (20, "DIANA ANDREA BRITO PICCIOTTO")],
            "Confort térmico en viviendas",
        ),
        ([(30, "Summary Report")], "Summary Report"),  # short, but a title
        ([(20, "Thermal comfort in schools by DIANA BRITO")], "Thermal comfort in schools"),
        ([(20, "Cooling by night ventilation")], "Cooling by night ventilation"),
        ([(20, "Enfriamiento por ventilación nocturna")], "Enfriamiento por ventilación nocturna"),
        ([(20, "Centro histórico de Mérida")], "Centro histórico de Mérida"),
        (
            [(24, "Centro de Investigación en Energía"), (20, "Ventilación natural en aulas")],
            "Ventilación natural en aulas",
        ),
    ],
)  # fmt: skip
def test_title_guess(tmp_path, lines, title):
    assert extract(cover(tmp_path / "a.pdf", lines)).title_guess == title


def test_title_from_metadata_when_the_page_shows_it(tmp_path):
    lines = [(28, "Emissions in 2023"), (12, "CO2 Emissions in 2023, an analysis")]
    pdf = cover(tmp_path / "a.pdf", lines, metadata_title="CO2 Emissions in 2023")
    assert extract(pdf).title_guess == "CO2 Emissions in 2023"
    pdf = cover(tmp_path / "b.pdf", lines, metadata_title="Microsoft Word - informe final.docx")
    assert extract(pdf).title_guess == "Emissions in 2023"


def test_title_on_a_later_page(tmp_path):
    pdf = cover(
        tmp_path / "a.pdf", [(22, "Night ventilation in Hermosillo")], blank_first_page=True
    )
    assert extract(pdf).title_guess == "Night ventilation in Hermosillo"
