import subprocess

from conftest import make_paper, make_project

from second_brain.checks import normalize_doi, run_checks


def messages(report):
    return [i.message for i in report.errors]


def test_empty_library_is_valid(home):
    report = run_checks(home)
    assert report.ok, report.issues


def test_valid_library_with_content(home, lib):
    lib.write_project(make_project(kind="tesis"))
    lib.write_paper(make_paper(projects={"tesis-doctoral": {"added": "2026-10-04"}}))
    report = run_checks(home)
    assert report.ok, report.issues
    assert (report.papers, report.projects) == (1, 1)


def test_duplicate_doi(home, lib):
    lib.write_paper(make_paper("a2021x", doi="10.1/ABC"))
    lib.write_paper(make_paper("b2021x", doi="https://doi.org/10.1/abc"))
    assert any("DOI repetido" in m for m in messages(run_checks(home)))


def test_unknown_project(home, lib):
    lib.write_paper(make_paper(projects={"no-existe": {"added": "2026-10-04"}}))
    assert any("no-existe" in m for m in messages(run_checks(home)))


def test_vocabularies(home, lib):
    lib.write_paper(make_paper(classification={"study_type": "inventado"}))
    lib.write_project(make_project(kind="raro"))
    found = messages(run_checks(home))
    assert any("study_type 'inventado'" in m for m in found)
    assert any("kind 'raro'" in m for m in found)


def test_filename_must_match_citekey(home, lib):
    path = lib.write_paper(make_paper())
    path.rename(lib.papers_dir / "otro.md")
    assert any("no coincide con citekey" in m for m in messages(run_checks(home)))


def test_pdf_tracked_in_git(home):
    (home / "library" / "notes" / "x.pdf").write_bytes(b"%PDF")
    subprocess.run(["git", "add", "-f", "library/notes/x.pdf"], cwd=home, check=True)
    assert any("PDF en git" in m for m in messages(run_checks(home)))


def test_oversized_file(home):
    (home / "config.toml").write_text(
        (home / "config.toml").read_text().replace("max_file_mb = 10", "max_file_mb = 0.001")
    )
    (home / "library" / "notes" / "grande.md").write_text("x" * 5000)
    assert any("pesa" in m for m in messages(run_checks(home)))


def test_large_files_in_local_folders_are_ignored(home):
    (home / "pdfs" / "grande.pdf").write_bytes(b"0" * (11 * 1024 * 1024))
    assert run_checks(home).ok


def test_missing_gitkeep(home):
    (home / "inbox" / ".gitkeep").unlink()
    assert any(".gitkeep" in m for m in messages(run_checks(home)))


def test_orphan_fulltext_is_a_warning(home, lib):
    (lib.fulltext_dir / "huerfano.md").write_text(
        "---\ncitekey: huerfano\nsource_pdf_sha256: ab\nextractor: x\n"
        "extracted: 2026-10-04\npages: 1\n---\ntexto\n"
    )
    report = run_checks(home)
    assert report.ok
    assert any(i.level == "warning" for i in report.issues)
    assert run_checks(home, fast=True).issues == []


def test_normalize_doi():
    assert normalize_doi(" https://doi.org/10.1016%2FJ.X ") == "10.1016/j.x"
    assert normalize_doi("doi:10.1/A") == "10.1/a"
