import shutil
import subprocess
from pathlib import Path

import pytest
from conftest import make_paper
from typer.testing import CliRunner

from second_brain import bibtex
from second_brain.cli import app
from second_brain.config import load_config
from second_brain.projects import ProjectError, add_papers, create_project, members, remove_papers
from second_brain.texcite import cited_keys

runner = CliRunner()


def paper_with(**overrides):
    return make_paper(**overrides)


# --- projects -------------------------------------------------------------------


def test_create_and_membership(lib):
    config = load_config(lib.home)
    create_project(lib, config, "tesis-doctoral", "Tesis", kind="tesis", description="Confort.")
    lib.write_paper(make_paper())
    added, present = add_papers(lib, "tesis-doctoral", ["garcia2021thermal"], note="Cap. 2")
    assert (added, present) == (["garcia2021thermal"], [])
    assert lib.read_paper("garcia2021thermal").meta.projects["tesis-doctoral"].note == "Cap. 2"
    assert add_papers(lib, "tesis-doctoral", ["garcia2021thermal"]) == ([], ["garcia2021thermal"])
    assert [p.citekey for p in members(lib, "tesis-doctoral")] == ["garcia2021thermal"]
    assert remove_papers(lib, "tesis-doctoral", ["garcia2021thermal"]) == (
        ["garcia2021thermal"],
        [],
    )
    assert lib.read_paper("garcia2021thermal").meta.projects == {}


def test_project_validation(lib):
    config = load_config(lib.home)
    with pytest.raises(ProjectError, match="slug inválido"):
        create_project(lib, config, "Tesis_Doctoral", "x")
    with pytest.raises(ProjectError, match="tipo"):
        create_project(lib, config, "tesis", "x", kind="novela")
    create_project(lib, config, "tesis-doctoral", "x")
    with pytest.raises(ProjectError, match="ya existe"):
        create_project(lib, config, "tesis-doctoral", "x")
    with pytest.raises(ProjectError, match="Quisiste decir 'tesis-doctoral'"):
        add_papers(lib, "tesis-doctoal", ["garcia2021thermal"])
    with pytest.raises(ProjectError, match="no existen"):
        add_papers(lib, "tesis-doctoral", ["noexiste2020x"])


def test_project_cli(lib):
    lib.write_paper(make_paper())
    home = ["--home", str(lib.home)]
    result = runner.invoke(
        app, [*home, "project", "create", "tesis", "--name", "Tesis", "--kind", "tesis"]
    )
    assert result.exit_code == 0, result.output
    assert (
        runner.invoke(app, [*home, "project", "add", "tesis", "garcia2021thermal"]).exit_code == 0
    )
    result = runner.invoke(app, [*home, "project", "list"])
    assert "1 artículos" in result.output
    assert runner.invoke(app, [*home, "project", "archive", "tesis"]).exit_code == 0
    assert "tesis" not in runner.invoke(app, [*home, "project", "list"]).output
    assert "archived" in runner.invoke(app, [*home, "project", "list", "--all"]).output


# --- BibTeX -------------------------------------------------------------------


def test_article_entry_bibtex():
    paper = make_paper(
        title="Night ventilation in México: CO2 savings with EnergyPlus & ASHRAE 55",
        authors=[
            {"family": "García-López", "given": "Ana María"},
            {"family": "Smith", "given": "J."},
        ],
        container_title="Energy & Buildings",
        volume="240",
        issue="3",
        pages="12-18",
    )
    text = bibtex.entry(paper)
    assert text.startswith("@article{garcia2021thermal,\n")
    assert r"author = {Garc{\'\i}a-L\'opez, Ana Mar{\'\i}a and Smith, J.}" in text
    assert (
        r"{M\'exico:}" in text and "{CO2}" in text and "{EnergyPlus}" in text and "{ASHRAE}" in text
    )
    assert r"\&" in text
    assert "journal = {Energy \\& Buildings}" in text
    assert "pages = {12--18}" in text
    assert "doi = {10.5555/ejemplo.2021.0001}" in text


def test_title_case_titles_only_protect_acronyms():
    title = bibtex.protect_title("Thermal Comfort Of Students In Mexico Using BIM", "bibtex")
    assert title == "Thermal Comfort Of Students In Mexico Using {BIM}"


def test_biblatex_keeps_utf8_and_types():
    paper = make_paper(type="thesis", publisher="Universidad Autónoma de Nuevo León")
    text = bibtex.entry(paper, "biblatex")
    assert text.startswith("@thesis{")
    assert "institution = {Universidad Autónoma de Nuevo León}" in text
    assert "type = {phdthesis}" in text
    assert "García" in text


def test_organization_author_is_braced():
    paper = make_paper(authors=[{"family": "International Energy Agency"}])
    assert "author = {{International Energy Agency}}" in bibtex.entry(paper)


def test_render_is_sorted_and_stable():
    papers = [make_paper("zeta2020x"), make_paper("alfa2020x", doi="10.1/b")]
    text = bibtex.render(papers)
    assert text.index("alfa2020x") < text.index("zeta2020x")
    assert text == bibtex.render(list(reversed(papers)))


def test_cited_keys(tmp_path):
    (tmp_path / "cap1.tex").write_text(r"Ver \citep[p.~3]{b2020x, c2021y} y \textcite{a2019z}.")
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n% \\cite{comentado}\n\\cite{a2019z}\n\\input{cap1}\n"
        "\\parencite*[vea][p. 2]{d2022w}\\nocite{*}\n"
    )
    assert cited_keys(tmp_path / "main.tex") == ["a2019z", "b2020x", "c2021y", "d2022w"]


def test_bib_cli_project_and_from_tex(lib, tmp_path):
    home = ["--home", str(lib.home)]
    lib.write_paper(make_paper())
    runner.invoke(app, [*home, "project", "create", "tesis", "--name", "Tesis"])
    runner.invoke(app, [*home, "project", "add", "tesis", "garcia2021thermal"])
    out = tmp_path / "refs.bib"
    result = runner.invoke(app, [*home, "bib", "--project", "tesis", "-o", str(out)])
    assert result.exit_code == 0, result.output
    assert "@article{garcia2021thermal," in out.read_text()
    again = runner.invoke(app, [*home, "bib", "-p", "tesis", "-o", str(out)]).output
    assert "sin cambios" in " ".join(again.split())  # rich wraps lines at 80 columns

    tex = tmp_path / "main.tex"
    tex.write_text(r"\cite{garcia2021thermal,falta2020x}")
    result = runner.invoke(app, [*home, "bib", "--from-tex", str(tex), "--strict"])
    assert result.exit_code == 1
    assert "falta2020x" in result.output


TEMPLATES = {
    "bibtex": (
        "\\documentclass{elsarticle}\n\\usepackage[T1]{fontenc}\n\\begin{document}\n"
        "\\citep{%s}\n\\bibliographystyle{elsarticle-harv}\n\\bibliography{refs}\n\\end{document}\n"
    ),
    "biblatex": (
        "\\documentclass{article}\n\\usepackage[T1]{fontenc}\n\\usepackage[backend=biber]{biblatex}\n"
        "\\addbibresource{refs.bib}\n\\begin{document}\n\\cite{%s}\n\\printbibliography\n\\end{document}\n"
    ),
}


@pytest.mark.skipif(shutil.which("latexmk") is None, reason="requiere LaTeX")
@pytest.mark.parametrize("fmt", ["bibtex", "biblatex"])
def test_bib_compiles_with_latex(tmp_path: Path, fmt):
    papers = [
        make_paper(
            title="Night ventilation in México: CO2 savings & 50% less load",
            authors=[
                {"family": "Pérez-Núñez", "given": "Ángel"},
                {"family": "Ministerio de Energía de Chile"},
            ],
            container_title="Energy & Buildings",
            pages="12-18",
        ),
        make_paper(
            "muller2020buch",
            type="book",
            doi=None,
            title="Wärmeschutz im Hochbau",
            publisher="Springer",
        ),
        make_paper(
            "garza2016analisis",
            type="thesis",
            doi=None,
            title="Análisis del ciclo de vida",
            publisher="UANL",
        ),
        make_paper(
            "lopez2019conf", type="paper-conference", container_title="Windsor Conference 2014"
        ),
    ]
    (tmp_path / "refs.bib").write_text(bibtex.render(papers, fmt), encoding="utf-8")
    keys = ",".join(p.citekey for p in papers)
    (tmp_path / "main.tex").write_text(TEMPLATES[fmt] % keys, encoding="utf-8")
    engine = ["-bibtex"] if fmt == "bibtex" else []  # latexmk detects biber on its own
    result = subprocess.run(
        ["latexmk", "-pdf", "-interaction=nonstopmode", "-halt-on-error", *engine, "main.tex"],
        cwd=tmp_path, capture_output=True, text=True, timeout=180,
    )  # fmt: skip
    log = (tmp_path / "main.log").read_text(errors="replace")
    assert result.returncode == 0, result.stdout[-3000:]
    assert "Citation" not in log or "undefined" not in log
    blg = next(tmp_path.glob("main.blg")).read_text(errors="replace")
    assert "error" not in blg.lower().replace("error(s)", ""), blg[-2000:]


def test_bib_sync_and_check_warning(lib, tmp_path):
    from second_brain.checks import run_checks
    from second_brain.scaffold import init_machine

    home = ["--home", str(lib.home)]
    lib.write_paper(make_paper())
    runner.invoke(app, [*home, "project", "create", "tesis", "--name", "Tesis"])
    runner.invoke(app, [*home, "project", "add", "tesis", "garcia2021thermal"])
    init_machine(lib.home, "test-machine")
    profile = lib.home / "machines" / "test-machine.toml"
    target = tmp_path / "salida" / "refs.bib"
    profile.write_text(
        profile.read_text().replace(
            "[bib_outputs]", f'[bib_outputs]\ntesis = "{target}"\nfantasma = "x.bib"'
        )
    )
    result = runner.invoke(app, [*home, "bib", "sync"])
    assert "garcia2021thermal" in target.read_text()
    assert result.exit_code == 1 and "fantasma" in result.output
    warnings = [i.message for i in run_checks(lib.home).issues if i.level == "warning"]
    assert any("fantasma" in w for w in warnings)
