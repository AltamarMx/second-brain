import json
import subprocess

import pytest
from typer.testing import CliRunner

from second_brain.cli import app
from second_brain.config import HomeNotFoundError, find_home, load_config
from second_brain.machines import detect_machine_name, load_profile, slugify
from second_brain.scaffold import hooks_installed, init_library, init_machine

runner = CliRunner()


def test_init_creates_layout_and_config(home):
    for relative in ("inbox/.gitkeep", "pdfs/.gitkeep", "library/papers/.gitkeep", ".gitignore"):
        assert (home / relative).is_file()
    config = load_config(home)
    assert config.user.email == "test@example.org"
    assert config.access.ip_ranges == ["192.0.2.0/24"]
    assert hooks_installed(home)


def test_init_is_idempotent(home):
    (home / "README.md").write_text("mío")
    report = init_library(home)
    assert report.created == []
    assert (home / "README.md").read_text() == "mío"


def test_gitignore_keeps_folders_but_not_contents(home):
    (home / "inbox" / "a.pdf").write_bytes(b"%PDF")
    (home / "pdfs" / "b.pdf").write_bytes(b"%PDF")
    subprocess.run(["git", "add", "-A"], cwd=home, check=True)
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=home, capture_output=True, text=True, check=True
    ).stdout.split()
    assert "inbox/.gitkeep" in tracked and "pdfs/.gitkeep" in tracked
    assert not any(p.endswith(".pdf") for p in tracked)


def test_find_home(home, tmp_path, monkeypatch):
    nested = home / "library" / "papers"
    assert find_home(cwd=nested) == home
    assert find_home(home) == home
    monkeypatch.setenv("SB_HOME", str(home))
    assert find_home(cwd=tmp_path) == home
    monkeypatch.delenv("SB_HOME")
    with pytest.raises(HomeNotFoundError):
        find_home(cwd=tmp_path)


def test_machine_profile(home, monkeypatch):
    monkeypatch.setenv("SB_MACHINE", "Mi iMac")
    assert detect_machine_name() == "mi-imac"
    init_machine(home, "mi-imac", backend="ollama", agent="opencode")
    profile = load_profile(home, "mi-imac")
    assert profile.process.backend == "ollama"
    assert profile.chat.agent == "opencode"
    assert slugify("Máquina Ñ") == "maquina-n"


def test_cli_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "check" in result.output


def test_cli_check_and_status(home):
    result = runner.invoke(app, ["--home", str(home), "check", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["ok"] is True
    result = runner.invoke(app, ["--home", str(home), "status", "--json"])
    assert json.loads(result.output)["papers"] == 0


def test_cli_without_library(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["check"])
    assert result.exit_code == 2
