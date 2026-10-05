"""Per-machine profiles: ``machines/{name}.toml`` inside the data repository.

Each computer declares which backend processes papers, which local model it
uses and machine-dependent paths. The active machine is ``SB_MACHINE`` or,
failing that, the computer's local host name.
"""

from __future__ import annotations

import os
import re
import socket
import subprocess
import tomllib
import unicodedata
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

MACHINES_DIRNAME = "machines"

Backend = Literal["claude", "ollama", "anthropic", "none"]
Agent = Literal["claude", "opencode"]


class Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProcessSection(Section):
    backend: Backend = "claude"


class LlmSection(Section):
    provider: str = "ollama"
    model: str | None = None
    num_ctx: int = 32768


class ChatSection(Section):
    agent: Agent = "claude"


class EmbeddingsSection(Section):
    model: str | None = None


class MachineProfile(Section):
    process: ProcessSection = ProcessSection()
    llm: LlmSection = LlmSection()
    chat: ChatSection = ChatSection()
    embeddings: EmbeddingsSection = EmbeddingsSection()
    bib_outputs: dict[str, str] = {}


def slugify(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-") or "maquina"


def detect_machine_name() -> str:
    explicit = os.environ.get("SB_MACHINE")
    if explicit:
        return slugify(explicit)
    try:
        result = subprocess.run(
            ["scutil", "--get", "LocalHostName"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        name = result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        name = ""
    return slugify(name or socket.gethostname().split(".")[0])


def profile_path(home: Path, name: str) -> Path:
    return home / MACHINES_DIRNAME / f"{name}.toml"


def load_profile(home: Path, name: str) -> MachineProfile | None:
    path = profile_path(home, name)
    if not path.is_file():
        return None
    with path.open("rb") as handle:
        return MachineProfile.model_validate(tomllib.load(handle))
