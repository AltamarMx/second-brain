"""LLM backends: who processes papers (summary, classification, figures).

Each machine chooses one in ``machines/{name}.toml`` → ``[process].backend``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class BackendError(RuntimeError):
    pass


class Backend(Protocol):
    name: str

    def run(
        self,
        prompt: str,
        schema: dict[str, Any],
        stdin: str = "",
        images: list[Path] | None = None,
    ) -> tuple[dict[str, Any], str]:
        """Return the structured output (validated against ``schema``) and the model used."""
        ...


def get_backend(name: str) -> Backend:
    if name == "claude":
        from .claude_cli import ClaudeCliBackend

        return ClaudeCliBackend()
    if name == "none":
        raise BackendError(
            'el perfil de esta máquina tiene backend = "none": no se procesan artículos aquí'
        )
    raise BackendError(f"el backend '{name}' llegará en la fase 6; por ahora usa \"claude\"")
