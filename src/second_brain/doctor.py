"""``sb doctor`` (is this machine ready?) and ``sb status`` (what is pending?)."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import urllib.request
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .config import HomeNotFoundError, find_home, load_config
from .library import InvalidDocument, Library
from .machines import detect_machine_name, load_profile, profile_path
from .scaffold import hooks_installed

State = Literal["ok", "warn", "fail", "info"]
OLLAMA_URL = "http://localhost:11434/api/version"
VERSION_RE = re.compile(r"\d+\.\d+(?:\.\d+)?")


@dataclass(frozen=True)
class Finding:
    name: str
    state: State
    detail: str


def _tool_version(command: str, *args: str) -> str | None:
    if shutil.which(command) is None:
        return None
    try:
        result = subprocess.run([command, *args], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return "instalado"
    match = VERSION_RE.search(result.stdout + result.stderr)
    return match.group(0) if match else "instalado"


def _ollama_running() -> bool:
    try:
        with urllib.request.urlopen(OLLAMA_URL, timeout=1):
            return True
    except OSError:
        return False


def run_doctor(explicit_home: Path | None = None) -> list[Finding]:
    findings: list[Finding] = []
    python = ".".join(map(str, sys.version_info[:3]))
    findings.append(Finding("Python", "ok" if sys.version_info >= (3, 13) else "fail", python))

    machine = detect_machine_name()
    try:
        home = find_home(explicit_home)
        config = load_config(home)
        findings.append(Finding("Biblioteca", "ok", str(home)))
    except HomeNotFoundError as exc:
        home, config = None, None
        findings.append(Finding("Biblioteca", "fail", str(exc)))
    except Exception as exc:
        home, config = None, None
        findings.append(Finding("Biblioteca", "fail", f"config.toml inválido: {exc}"))

    profile = None
    if home is not None:
        try:
            profile = load_profile(home, machine)
        except Exception as exc:
            findings.append(Finding("Máquina", "fail", f"{machine}: perfil inválido: {exc}"))
        else:
            if profile is None:
                findings.append(
                    Finding(
                        "Máquina",
                        "fail",
                        f"{machine}: falta {profile_path(home, machine).relative_to(home)} → sb machine init",
                    )
                )
            else:
                findings.append(
                    Finding(
                        "Máquina",
                        "ok",
                        f"{machine} (procesa con {profile.process.backend}, chat con {profile.chat.agent})",
                    )
                )
        if (home / ".git").exists():
            hooks = hooks_installed(home)
            findings.append(
                Finding(
                    "Hook de git",
                    "ok" if hooks else "warn",
                    "sb check --fast antes de cada commit"
                    if hooks
                    else "no activo → sb machine init",
                )
            )
    else:
        findings.append(Finding("Máquina", "info", machine))

    backend = profile.process.backend if profile else None
    agent = profile.chat.agent if profile else None
    uses_ollama = backend == "ollama" or agent == "opencode" or bool(profile and profile.llm.model)

    tools = [
        ("git", ("--version",), True, "control de versiones"),
        ("uv", ("--version",), True, "entorno de Python"),
        ("tesseract", ("--version",), False, "OCR de PDFs escaneados"),
        ("claude", ("--version",), backend == "claude" or agent == "claude", "Claude Code"),
        ("ollama", ("--version",), uses_ollama, "modelos locales"),
        ("opencode", ("--version",), agent == "opencode", "agente con modelo local"),
    ]
    for command, args, required, purpose in tools:
        version = _tool_version(command, *args)
        if version is not None:
            findings.append(Finding(command, "ok", version))
        else:
            findings.append(
                Finding(command, "fail" if required else "info", f"no instalado ({purpose})")
            )

    if uses_ollama:
        running = _ollama_running()
        findings.append(
            Finding(
                "Servidor Ollama",
                "ok" if running else "warn",
                "respondiendo"
                if running
                else "no está abierto (ábrelo cuando uses el modelo local)",
            )
        )

    target = home or Path.home()
    free_gb = shutil.disk_usage(target).free / 1024**3
    findings.append(Finding("Disco libre", "ok" if free_gb > 20 else "warn", f"{free_gb:.0f} GB"))
    if config is not None and not config.user.email:
        findings.append(
            Finding(
                "Correo",
                "warn",
                "falta [user].email en config.toml (lo piden Crossref y Unpaywall)",
            )
        )
    return findings


@dataclass(frozen=True)
class Status:
    home: Path
    machine: str
    inbox: int
    local_pdfs: int
    papers: int
    by_status: dict[str, int]
    invalid: int
    projects_active: int
    projects_total: int


def library_status(home: Path) -> Status:
    lib = Library(home)
    by_status: Counter[str] = Counter()
    invalid = 0
    papers = 0
    for doc in lib.iter_papers():
        if isinstance(doc, InvalidDocument):
            invalid += 1
            continue
        papers += 1
        by_status[doc.meta.status] += 1
    projects = [d for d in lib.iter_projects() if not isinstance(d, InvalidDocument)]
    return Status(
        home=home,
        machine=detect_machine_name(),
        inbox=len(lib.inbox_pdfs()),
        local_pdfs=len(lib.local_pdfs()),
        papers=papers,
        by_status=dict(by_status),
        invalid=invalid,
        projects_active=sum(1 for d in projects if d.meta.status == "active"),
        projects_total=len(projects),
    )
