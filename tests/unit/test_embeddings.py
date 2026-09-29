import asyncio
import math

from sentinel.db.models import EMBEDDING_DIM
from sentinel.retrieval.embeddings import FakeEmbedder


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True)) / (
        math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    )


def test_fake_embedder_is_deterministic_and_normalised() -> None:
    [a1, a2] = asyncio.run(FakeEmbedder().embed(["settlement fee", "settlement fee"]))
    assert a1 == a2
    assert len(a1) == EMBEDDING_DIM
    assert math.isclose(math.sqrt(sum(v * v for v in a1)), 1.0)


def test_fake_embedder_has_lexical_similarity() -> None:
    q, near, far = asyncio.run(
        FakeEmbedder().embed(
            [
                "settlement mismatch fee",
                "settlement amount mismatch due to fee",
                "refund batch timing",
            ]
        )
    )
    assert cosine(q, near) > cosine(q, far)
