"""Backend ``claude``: Claude Code in non-interactive mode (``claude -p``).

Uses the user's Claude subscription, no API key. Runs in a temporary empty
directory, without session persistence and with no tools except ``Read``
(only when images must be read), so it never touches the library.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from . import BackendError

TIMEOUT_SECONDS = 900


class ClaudeCliBackend:
    name = "claude"

    def __init__(self, executable: str = "claude", model: str | None = None):
        self.executable = executable
        self.model = model

    def run(
        self,
        prompt: str,
        schema: dict[str, Any],
        stdin: str = "",
        images: list[Path] | None = None,
    ) -> tuple[dict[str, Any], str]:
        if shutil.which(self.executable) is None:
            raise BackendError("no encontré Claude Code (`claude`); instálalo o cambia el backend")
        with tempfile.TemporaryDirectory(prefix="sb-claude-") as workdir:
            for image in images or []:
                shutil.copy2(image, Path(workdir) / image.name)
            command = [
                self.executable,
                "-p",
                prompt,
                "--output-format",
                "json",
                "--json-schema",
                json.dumps(schema),
                "--no-session-persistence",
            ]
            if images:
                command += ["--tools", "Read", "--allowedTools", "Read"]
            else:
                command += ["--tools", ""]
            if self.model:
                command += ["--model", self.model]
            try:
                completed = subprocess.run(
                    command,
                    input=stdin,
                    capture_output=True,
                    text=True,
                    cwd=workdir,
                    timeout=TIMEOUT_SECONDS,
                )
            except subprocess.TimeoutExpired as exc:
                raise BackendError(
                    f"Claude no respondió en {TIMEOUT_SECONDS // 60} minutos"
                ) from exc
        try:
            reply = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            detail = (completed.stderr or completed.stdout).strip()[-500:]
            raise BackendError(f"respuesta inesperada de Claude: {detail}") from exc
        if reply.get("is_error") or "structured_output" not in reply:
            detail = str(reply.get("result") or reply.get("subtype") or "sin detalle")[:500]
            raise BackendError(f"Claude no pudo completar la tarea: {detail}")
        usage = reply.get("modelUsage") or {}
        model = max(usage, key=lambda m: usage[m].get("outputTokens", 0), default="claude")
        return reply["structured_output"], model
