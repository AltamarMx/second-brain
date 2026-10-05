"""Create a data repository (``sb init``) and machine profiles (``sb machine init``).

Never overwrites an existing file unless ``force`` is set, so it is safe to
run again on an existing library.
"""

from __future__ import annotations

import json
import stat
import subprocess
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path
from string import Template

from .machines import Agent, Backend, profile_path

HOOKS_DIRNAME = ".githooks"
LIBRARY_SUBDIRS = ("papers", "fulltext", "figures", "supplements", "notes", "projects")


@dataclass
class ScaffoldReport:
    created: list[Path] = field(default_factory=list)
    skipped: list[Path] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _template(template: str, /, **values: str) -> str:
    text = files("second_brain.templates").joinpath(template).read_text(encoding="utf-8")
    return Template(text).substitute(values) if values else text


def _toml_string(value: str | None) -> str:
    return json.dumps(value or "", ensure_ascii=False)


def _write(path: Path, text: str, report: ScaffoldReport, force: bool) -> None:
    if path.exists() and not force:
        report.skipped.append(path)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    report.created.append(path)


def init_library(
    home: Path,
    *,
    email: str | None = None,
    institution: str | None = None,
    ip_ranges: list[str] | None = None,
    vpn_hint: str | None = None,
    force: bool = False,
) -> ScaffoldReport:
    home = home.expanduser().resolve()
    report = ScaffoldReport()
    home.mkdir(parents=True, exist_ok=True)

    for directory in ("inbox", "pdfs", *(f"library/{d}" for d in LIBRARY_SUBDIRS)):
        _write(home / directory / ".gitkeep", "", report, force=False)
    (home / "machines").mkdir(exist_ok=True)

    config = _template(
        "config.toml",
        email=_toml_string(email),
        institution=_toml_string(institution),
        ip_ranges=json.dumps(ip_ranges or []),
        vpn_hint=_toml_string(vpn_hint),
    )
    _write(home / "config.toml", config, report, force)
    _write(home / ".gitignore", _template("gitignore"), report, force)
    _write(home / ".gitattributes", _template("gitattributes"), report, force)
    _write(home / ".env.example", _template("env.example"), report, force)
    _write(home / "pyproject.toml", _template("pyproject.toml", name=home.name), report, force)
    _write(home / "README.md", _template("README.md", name=home.name), report, force)

    hook = home / HOOKS_DIRNAME / "pre-commit"
    _write(hook, _template("pre-commit"), report, force)
    hook.chmod(hook.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    if not (home / ".git").exists():
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=home, check=True)
        report.notes.append("Inicialicé un repositorio git nuevo.")
    install_hooks(home)
    from .agents import sync_agents

    report.created += [p for p in sync_agents(home) if p not in report.created]
    report.notes.append(
        f"git usa los hooks de {HOOKS_DIRNAME}/ (sb check --fast antes de cada commit)."
    )
    return report


def install_hooks(home: Path) -> None:
    subprocess.run(["git", "config", "core.hooksPath", HOOKS_DIRNAME], cwd=home, check=True)


def hooks_installed(home: Path) -> bool:
    result = subprocess.run(
        ["git", "config", "--get", "core.hooksPath"],
        cwd=home,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() == HOOKS_DIRNAME


def init_machine(
    home: Path,
    name: str,
    *,
    backend: Backend = "claude",
    agent: Agent = "claude",
    force: bool = False,
) -> ScaffoldReport:
    report = ScaffoldReport()
    text = _template("machine.toml", name=name, backend=backend, agent=agent)
    _write(profile_path(home, name), text, report, force)
    if (home / ".git").exists() and not hooks_installed(home):
        install_hooks(home)
        report.notes.append(f"Activé los hooks de {HOOKS_DIRNAME}/ en este clon.")
    return report
