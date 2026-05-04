"""Embedding computation and similarity utilities."""

import json
import math

from openai import AsyncOpenAI

from ..config import settings

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI | None:
    global _client
    if not settings.EMBEDDING_BASE_URL:
        return None
    if _client is None:
        _client = AsyncOpenAI(
            api_key=settings.EMBEDDING_API_KEY or "unused",
            base_url=settings.EMBEDDING_BASE_URL,
        )
    return _client


def is_available() -> bool:
    return bool(settings.EMBEDDING_BASE_URL and settings.EMBEDDING_MODEL)


async def compute_embedding(text: str) -> list[float]:
    """Compute embedding vector for a single text."""
    client = _get_client()
    if client is None:
        return []
    response = await client.embeddings.create(
        model=settings.EMBEDDING_MODEL,
        input=text,
    )
    return response.data[0].embedding


async def compute_embeddings(texts: list[str]) -> list[list[float]]:
    """Compute embedding vectors for multiple texts in one API call."""
    client = _get_client()
    if client is None or not texts:
        return []
    response = await client.embeddings.create(
        model=settings.EMBEDDING_MODEL,
        input=texts,
    )
    return [item.embedding for item in sorted(response.data, key=lambda d: d.index)]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def serialize(embedding: list[float]) -> str:
    return json.dumps(embedding)


def deserialize(data: str | None) -> list[float]:
    if not data:
        return []
    return json.loads(data)
