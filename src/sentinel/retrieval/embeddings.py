"""Embedders: OpenRouter (OpenAI-compatible API) for real use, a deterministic fake for tests."""

import hashlib
import math
import re
import zlib
from functools import lru_cache
from typing import Protocol

from openai import AsyncOpenAI

from sentinel.config import get_settings
from sentinel.db.models import EMBEDDING_DIM


class Embedder(Protocol):
    name: str  # identifies the vector space; changing it forces re-embedding

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class FakeEmbedder:
    """Hashed bag-of-words: offline and deterministic, with crude lexical similarity."""

    name = "fake-bow-v1"

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._one(text) for text in texts]

    @staticmethod
    def _one(text: str) -> list[float]:
        vector = [0.0] * EMBEDDING_DIM
        for token in re.findall(r"[a-z0-9]+", text.lower()):
            h = zlib.crc32(token.encode())
            vector[h % EMBEDDING_DIM] += 1.0 if (h >> 16) & 1 else -1.0
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]


class OpenRouterEmbedder:
    def __init__(self, api_key: str, base_url: str, model: str) -> None:
        self.name = f"openrouter:{model}"
        self._model = model
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        response = await self._client.embeddings.create(model=self._model, input=texts)
        vectors = [item.embedding for item in sorted(response.data, key=lambda d: d.index)]
        if any(len(v) != EMBEDDING_DIM for v in vectors):
            raise ValueError(f"{self._model} returned vectors not of dimension {EMBEDDING_DIM}")
        return vectors


@lru_cache
def get_embedder() -> Embedder:
    settings = get_settings()
    if settings.embedder == "fake":
        return FakeEmbedder()
    if settings.openrouter_api_key is None:
        raise RuntimeError("SENTINEL_EMBEDDER=openrouter requires OPENROUTER_API_KEY")
    return OpenRouterEmbedder(
        settings.openrouter_api_key.get_secret_value(),
        settings.openrouter_base_url,
        settings.embedding_model,
    )


def fingerprint(embedder: Embedder, *parts: str) -> str:
    return hashlib.sha256("\x1f".join((embedder.name, *parts)).encode()).hexdigest()
