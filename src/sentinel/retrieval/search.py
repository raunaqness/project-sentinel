"""Hybrid retrieval (vector + full-text, fused with reciprocal rank fusion).

Tenant isolation is not optional: `search` requires a tenant_id and every query it
issues is restricted to that tenant's private documents plus global ones.
"""

import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinel.db.models import Document, DocumentChunk
from sentinel.retrieval.embeddings import Embedder

CANDIDATES = 20  # per method, before fusion
RRF_K = 60


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: str  # citation key, e.g. "chunk_42"
    doc_key: str
    title: str
    document_type: str
    scope: str  # "global" or the owning tenant
    content: str
    score: float

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def _scoped(
    stmt: Select[Any],
    tenant_id: str,
    document_type: str | None,
    gateway: str | None,
    as_of: date | None,
) -> Select[Any]:
    stmt = stmt.where(or_(DocumentChunk.tenant_id == tenant_id, DocumentChunk.tenant_id.is_(None)))
    if document_type is not None:
        stmt = stmt.where(DocumentChunk.document_type == document_type)
    if gateway is not None:
        stmt = stmt.where(or_(DocumentChunk.gateway == gateway, DocumentChunk.gateway.is_(None)))
    if as_of is not None:
        stmt = stmt.where(
            or_(DocumentChunk.effective_date <= as_of, DocumentChunk.effective_date.is_(None))
        )
    return stmt


async def search(
    session: AsyncSession,
    embedder: Embedder,
    *,
    tenant_id: str,
    query: str,
    k: int = 5,
    document_type: str | None = None,
    gateway: str | None = None,
    as_of: date | None = None,
) -> list[RetrievedChunk]:
    if not tenant_id:
        raise ValueError("tenant_id is required for retrieval")
    scope = (tenant_id, document_type, gateway, as_of)

    [query_vector] = await embedder.embed([query])
    by_vector = (
        await session.scalars(
            _scoped(select(DocumentChunk.id), *scope)
            .order_by(DocumentChunk.embedding.cosine_distance(query_vector))
            .limit(CANDIDATES)
        )
    ).all()

    words = re.findall(r"[a-zA-Z0-9]+", query)
    by_text: list[int] = []
    if words:
        tsquery = func.websearch_to_tsquery("english", " or ".join(words))
        by_text = list(
            (
                await session.scalars(
                    _scoped(select(DocumentChunk.id), *scope)
                    .where(DocumentChunk.tsv.op("@@")(tsquery))
                    .order_by(func.ts_rank(DocumentChunk.tsv, tsquery).desc())
                    .limit(CANDIDATES)
                )
            ).all()
        )

    scores: dict[int, float] = {}
    for ranking in (by_vector, by_text):
        for rank, chunk_id in enumerate(ranking):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (RRF_K + rank + 1)
    top = sorted(scores, key=lambda cid: scores[cid], reverse=True)[:k]
    if not top:
        return []

    rows = {
        c.id: (c, d)
        for c, d in (
            await session.execute(
                select(DocumentChunk, Document)
                .join(Document, Document.id == DocumentChunk.document_id)
                .where(DocumentChunk.id.in_(top))
            )
        ).all()
    }
    return [
        RetrievedChunk(
            chunk_id=f"chunk_{cid}",
            doc_key=rows[cid][1].doc_key,
            title=rows[cid][1].title,
            document_type=rows[cid][0].document_type,
            scope=rows[cid][0].tenant_id or "global",
            content=rows[cid][0].content,
            score=round(scores[cid], 5),
        )
        for cid in top
    ]
