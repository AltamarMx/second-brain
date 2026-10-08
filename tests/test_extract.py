import pymupdf
import pytest

from second_brain.ingest.extract import extract, plain_math, repair_math_tounicode


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


def word_math_pdf(path, mapping, codes):
    """A PDF with "MONITOR DE" and then a run in a Type0 math font whose ToUnicode map is
    ``mapping`` (glyph id hex → UTF-16 hex), as Word writes equations: CO₂ → "𝐶𝐶𝐶𝐶"."""
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((50, 100), "MONITOR DE", fontsize=16)
    page.insert_text((50, 700), "Body text of the document. " * 3, fontsize=10)
    entries = "\n".join(f"<{gid}> <{value}>" for gid, value in mapping.items())
    cmap = (
        "/CIDInit /ProcSet findresource begin 12 dict begin begincmap\n"
        "/CMapName /Adobe-Identity-UCS def /CMapType 2 def\n"
        "1 begincodespacerange <0000> <FFFF> endcodespacerange\n"
        f"{len(mapping)} beginbfchar\n{entries}\nendbfchar\n"
        "endcmap CMapName currentdict /CMap defineresource pop end end\n"
    )
    tounicode = doc.get_new_xref()
    doc.update_object(tounicode, "<<>>")
    doc.update_stream(tounicode, cmap.encode())
    descriptor = doc.get_new_xref()
    doc.update_object(
        descriptor,
        "<< /Type /FontDescriptor /FontName /CambriaMath /Flags 4 /FontBBox [0 -200 1000 900] "
        "/ItalicAngle 0 /Ascent 900 /Descent -200 /CapHeight 700 /StemV 80 >>",
    )
    cid = doc.get_new_xref()
    doc.update_object(
        cid,
        "<< /Type /Font /Subtype /CIDFontType2 /BaseFont /CambriaMath /CIDSystemInfo "
        "<< /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> "
        f"/FontDescriptor {descriptor} 0 R /CIDToGIDMap /Identity /DW 600 >>",
    )
    font = doc.get_new_xref()
    doc.update_object(
        font,
        "<< /Type /Font /Subtype /Type0 /BaseFont /CambriaMath /Encoding /Identity-H "
        f"/DescendantFonts [{cid} 0 R] /ToUnicode {tounicode} 0 R >>",
    )
    resources = int(doc.xref_get_key(page.xref, "Resources")[1].split()[0])
    doc.xref_set_key(resources, "Font/FM", f"{font} 0 R")
    content = page.get_contents()[0]
    run = f"\nBT /FM 16 Tf 160 742 Td <{codes}> Tj ET\n".encode()
    doc.update_stream(content, doc.xref_stream(content) + run)
    doc.save(path)
    return path


ITALIC_C = "D835DC36D835DC36"  # 𝐶 twice: what Word writes for both C (0725) and O (0731)


def test_word_equation_text_is_repaired(tmp_path):
    pdf = word_math_pdf(tmp_path / "a.pdf", {"0725": ITALIC_C, "0731": ITALIC_C}, "07250731")
    assert "𝐶𝐶𝐶𝐶" in pymupdf.open(pdf)[0].get_text()  # the bug, as in the real PDF
    extraction = extract(pdf)
    assert "MONITOR DE CO" in extraction.front_text
    assert "CO" in extraction.pages[0] and "𝐶" not in extraction.pages[0]


def test_colliding_glyphs_resolved_by_first_use(tmp_path):
    italic_s = "D835DC46D835DC46"  # 𝑆 twice, for S (0735) and O (0731): "SO"
    pdf = word_math_pdf(tmp_path / "a.pdf", {"0735": italic_s, "0731": italic_s}, "07350731")
    doc = pymupdf.open(pdf)
    assert repair_math_tounicode(doc) == 1
    doc = pymupdf.open(stream=doc.tobytes(), filetype="pdf")
    assert "MONITOR DE SO" in plain_math(doc[0].get_text())


def test_ligatures_are_not_undoubled(tmp_path):
    pdf = word_math_pdf(tmp_path / "a.pdf", {"0725": "00660066"}, "0725")  # "ff"
    assert repair_math_tounicode(pymupdf.open(pdf)) == 0
