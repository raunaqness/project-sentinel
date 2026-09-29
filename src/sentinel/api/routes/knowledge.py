"""Knowledge-base search (for inspection; the workflow calls retrieval directly)."""

from typing import Any

from fastapi import APIRouter, Query

from sentinel.api.deps import SessionDep
from sentinel.retrieval.embeddings import get_embedder
from sentinel.retrieval.search import search

router = APIRouter(tags=["knowledge"])


@router.get("/knowledge/search")
async def search_knowledge(
    session: SessionDep,
    tenant_id: str,
    q: str,
    document_type: str | None = None,
    gateway: str | None = None,
    k: int = Query(default=5, ge=1, le=20),
) -> list[dict[str, Any]]:
    chunks = await search(
        session,
        get_embedder(),
        tenant_id=tenant_id,
        query=q,
        k=k,
        document_type=document_type,
        gateway=gateway,
    )
    return [c.as_dict() for c in chunks]
