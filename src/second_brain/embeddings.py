"""Text embeddings for semantic search.

- ``model2vec`` (default): multilingual static embeddings computed in-process
  with numpy only; no server, works the same on Intel and Apple Silicon. The
  model is downloaded once to the Hugging Face cache.
- ``ollama``: an embedding model served by Ollama (must be open).

Vectors are L2-normalized, so a dot product is the cosine similarity.
"""

from __future__ import annotations

import os
from typing import Protocol

import httpx
import numpy as np

DEFAULT_PROVIDER = "model2vec"
DEFAULT_MODEL = "minishlab/potion-multilingual-128M"
BATCH = 256


class EmbeddingError(RuntimeError):
    pass


class Embedder(Protocol):
    id: str

    def embed(self, texts: list[str]) -> np.ndarray: ...


def _normalize(matrix: np.ndarray) -> np.ndarray:
    matrix = np.asarray(matrix, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.where(norms == 0, 1, norms)


class Model2VecEmbedder:
    def __init__(self, model: str = DEFAULT_MODEL):
        self.id = f"model2vec:{model}"
        self.model_name = model
        self._model = None

    def embed(self, texts: list[str]) -> np.ndarray:
        if self._model is None:
            os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
            try:
                from model2vec import StaticModel

                self._model = StaticModel.from_pretrained(self.model_name)
            except Exception as exc:  # download or load failures
                raise EmbeddingError(
                    f"no pude cargar el modelo de embeddings {self.model_name}: {exc}"
                ) from exc
        return _normalize(self._model.encode(texts, batch_size=BATCH))


class OllamaEmbedder:
    def __init__(
        self,
        model: str,
        base_url: str = "http://localhost:11434",
        client: httpx.Client | None = None,
    ):
        self.id = f"ollama:{model}"
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.client = client or httpx.Client(timeout=600)

    def embed(self, texts: list[str]) -> np.ndarray:
        vectors = []
        for start in range(0, len(texts), 64):
            try:
                response = self.client.post(
                    f"{self.base_url}/api/embed",
                    json={"model": self.model, "input": texts[start : start + 64]},
                )
            except httpx.HTTPError as exc:
                raise EmbeddingError(
                    "Ollama no está abierto (lo necesitan los embeddings de este perfil)"
                ) from exc
            if response.status_code != 200:
                raise EmbeddingError(
                    f"Ollama respondió {response.status_code}: {response.text[:200]}"
                )
            vectors += response.json()["embeddings"]
        return _normalize(np.array(vectors))


def get_embedder(profile) -> Embedder | None:
    """From the machine profile's ``[embeddings]``; ``None`` disables semantic search."""
    section = getattr(profile, "embeddings", None)
    if section is None or section.provider == "none":
        return None
    if section.provider == "ollama":
        if not section.model:
            raise EmbeddingError("falta [embeddings].model para el proveedor ollama")
        return OllamaEmbedder(
            section.model, getattr(profile.llm, "base_url", "http://localhost:11434")
        )
    return Model2VecEmbedder(section.model or DEFAULT_MODEL)
