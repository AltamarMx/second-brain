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


def get_backend(name: str, profile: Any = None, env: dict[str, str] | None = None) -> Backend:
    """``profile`` is the machine profile (``MachineProfile``); ``env`` the values of ``.env``."""
    env = env or {}
    process_model = getattr(getattr(profile, "process", None), "model", None)
    if name == "claude":
        from .claude_cli import ClaudeCliBackend

        return ClaudeCliBackend(model=process_model)
    if name == "ollama":
        from .ollama import OllamaBackend

        llm = getattr(profile, "llm", None)
        if llm is None or not llm.model:
            raise BackendError("falta [llm].model en el perfil de la máquina (p. ej., gemma4)")
        return OllamaBackend(llm.model, llm.base_url, llm.num_ctx)
    if name == "anthropic":
        from .anthropic_api import AnthropicApiBackend

        return AnthropicApiBackend(api_key=env.get("ANTHROPIC_API_KEY"), model=process_model)
    if name == "none":
        raise BackendError(
            'el perfil de esta máquina tiene backend = "none": no se procesan artículos aquí'
        )
    raise BackendError(f"backend desconocido: '{name}' (claude, ollama, anthropic o none)")
