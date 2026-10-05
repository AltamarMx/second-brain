"""Backend ``anthropic``: the Claude API with an API key (``ANTHROPIC_API_KEY`` in ``.env``).

For large unattended batches. Structured outputs (``output_config.format``)
guarantee schema-valid JSON; long inputs are streamed. Server-side fallbacks
are enabled so a policy decline is retried on another model in the same call.
Needs the optional dependency: ``uv add "second-brain[anthropic]"``.
"""

from __future__ import annotations

import base64
import copy
import json
from pathlib import Path
from typing import Any

from . import BackendError

DEFAULT_MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
UNSUPPORTED_KEYWORDS = ("pattern", "minItems", "maxItems")


def strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """The JSON-schema subset structured outputs accept: closed objects, no regex/length keywords.

    The removed constraints are re-checked locally after the response.
    """
    schema = copy.deepcopy(schema)

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            for keyword in UNSUPPORTED_KEYWORDS:
                node.pop(keyword, None)
            if node.get("type") == "object" or "properties" in node:
                node["additionalProperties"] = False
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for item in node:
                visit(item)

    visit(schema)
    return schema


class AnthropicApiBackend:
    name = "anthropic"

    def __init__(self, api_key: str | None = None, model: str | None = None, client: Any = None):
        self.model = model or DEFAULT_MODEL
        if client is not None:
            self.client = client
            return
        try:
            import anthropic
        except ImportError as exc:
            raise BackendError(
                'falta el SDK de Anthropic: en la biblioteca, uv add "second-brain[anthropic]"'
            ) from exc
        self.client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()

    def run(
        self,
        prompt: str,
        schema: dict[str, Any],
        stdin: str = "",
        images: list[Path] | None = None,
    ) -> tuple[dict[str, Any], str]:
        content: list[dict[str, Any]] = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": base64.standard_b64encode(path.read_bytes()).decode("utf-8"),
                },
            }
            for path in images or []
        ]
        content.append({"type": "text", "text": f"{prompt}\n\n{stdin}".strip()})
        try:
            with self.client.beta.messages.stream(
                model=self.model,
                max_tokens=16000,
                betas=[FALLBACK_BETA],
                fallbacks="default",
                output_config={
                    "effort": "medium",
                    "format": {"type": "json_schema", "schema": strict_schema(schema)},
                },
                messages=[{"role": "user", "content": content}],
            ) as stream:
                message = stream.get_final_message()
        except Exception as exc:  # anthropic.APIError and network errors
            raise BackendError(f"la API de Anthropic falló: {type(exc).__name__}: {exc}") from exc
        if message.stop_reason == "refusal":
            raise BackendError("el modelo declinó la solicitud (refusal)")
        if message.stop_reason == "max_tokens":
            raise BackendError("la respuesta se cortó por longitud (max_tokens)")
        text = next((b.text for b in message.content if b.type == "text"), "")
        try:
            return json.loads(text), message.model
        except json.JSONDecodeError as exc:
            raise BackendError(f"respuesta no es JSON: {text[:200]}") from exc
