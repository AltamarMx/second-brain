"""Backend ``ollama``: a local model through Ollama's native API, nothing leaves the machine.

Structured output uses Ollama's ``format`` (a JSON schema). Images (figures)
are sent base64-encoded and need a vision-capable model. The context window
(``num_ctx``) is set per request; text that would not fit is cut beforehand,
because Ollama would otherwise drop the *beginning* of the prompt silently.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import httpx

from . import BackendError

CHARS_PER_TOKEN = 3  # conservative for mixed Spanish/English scientific text
RESERVED_TOKENS = 6000  # prompt instructions + the model's answer
TIMEOUT_SECONDS = 3600  # CPU-only machines can take many minutes per paper


class OllamaBackend:
    name = "ollama"

    def __init__(self, model: str, base_url: str = "http://localhost:11434", num_ctx: int = 32768,
                 client: httpx.Client | None = None):  # fmt: skip
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.num_ctx = num_ctx
        self.client = client or httpx.Client(timeout=TIMEOUT_SECONDS)

    @property
    def max_input_chars(self) -> int:
        return max(4000, (self.num_ctx - RESERVED_TOKENS) * CHARS_PER_TOKEN)

    def running(self) -> bool:
        try:
            return self.client.get(f"{self.base_url}/api/version", timeout=2).status_code == 200
        except httpx.HTTPError:
            return False

    def run(
        self,
        prompt: str,
        schema: dict[str, Any],
        stdin: str = "",
        images: list[Path] | None = None,
    ) -> tuple[dict[str, Any], str]:
        text = stdin
        if len(text) > self.max_input_chars:
            text = (
                text[: self.max_input_chars]
                + "\n\n[texto truncado para caber en el contexto del modelo]"
            )
        message: dict[str, Any] = {
            "role": "user",
            "content": f"{prompt}\n\nResponde solo con JSON válido según el esquema.\n\n{text}".strip(),
        }
        if images:
            message["images"] = [base64.b64encode(p.read_bytes()).decode() for p in images]
            message["content"] += (
                "\n\n(Las imágenes de las páginas vienen adjuntas en este mensaje, en el orden listado.)"
            )
        body = {
            "model": self.model,
            "messages": [message],
            "format": schema,
            "stream": False,
            "options": {"num_ctx": self.num_ctx, "temperature": 0},
        }
        try:
            response = self.client.post(f"{self.base_url}/api/chat", json=body)
        except httpx.ConnectError as exc:
            raise BackendError(
                "Ollama no está abierto: ábrelo (o `ollama serve`) y reintenta"
            ) from exc
        except httpx.HTTPError as exc:
            raise BackendError(f"Ollama falló: {exc}") from exc
        if response.status_code == 404:
            raise BackendError(
                f"Ollama no tiene el modelo '{self.model}': ollama pull {self.model}"
            )
        if response.status_code != 200:
            raise BackendError(f"Ollama respondió {response.status_code}: {response.text[:300]}")
        content = response.json().get("message", {}).get("content", "")
        try:
            return json.loads(content), self.model
        except json.JSONDecodeError as exc:
            raise BackendError(f"el modelo no devolvió JSON válido: {content[:200]}") from exc
