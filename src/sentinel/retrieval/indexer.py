"""Loads the knowledge base from disk into `documents` / `document_chunks`.

Idempotent: a document is re-chunked and re-embedded only if its content, metadata or
the embedder changed. Documents removed from disk are removed from the index.

    python -m sentinel.retrieval.indexer
"""

import asyncio
import logging
from pathlib import Path

from sqlalchemy import delete, select

from sentinel.config import get_settings
from sentinel.db.models import Document, DocumentChunk
from sentinel.db.session import get_engine, get_sessionmaker
from sentinel.observability.logging import configure_logging
from sentinel.retrieval.chunking import ParsedDocument, chunk, parse_document
from sentinel.retrieval.embeddings import Embedder, fingerprint, get_embedder

log = logging.getLogger("sentinel.indexer")


def load_directory(root: Path) -> list[ParsedDocument]:
    docs = [parse_document(path.read_text()) for path in sorted(root.rglob("*.md"))]
    keys = [d.doc_key for d in docs]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate doc_key in knowledge base")
    return docs


async def index(docs: list[ParsedDocument], embedder: Embedder) -> dict[str, int]:
    stats = {"unchanged": 0, "indexed": 0, "removed": 0, "chunks": 0}
    async with get_sessionmaker()() as session, session.begin():
        existing = {d.doc_key: d for d in await session.scalars(select(Document))}
        for doc in docs:
            digest = fingerprint(
                embedder,
                doc.body,
                doc.title,
                str(doc.tenant_id),
                doc.document_type,
                str(doc.gateway),
                str(doc.effective_date),
            )
            row = existing.pop(doc.doc_key, None)
            if row is not None and row.content_hash == digest:
                stats["unchanged"] += 1
                continue
            if row is not None:
                await session.delete(row)
                await session.flush()
            row = Document(
                doc_key=doc.doc_key,
                tenant_id=doc.tenant_id,
                title=doc.title,
                document_type=doc.document_type,
                gateway=doc.gateway,
                effective_date=doc.effective_date,
                content=doc.body,
                content_hash=digest,
            )
            session.add(row)
            await session.flush()
            pieces = chunk(doc.title, doc.body)
            vectors = await embedder.embed(pieces)
            session.add_all(
                DocumentChunk(
                    document_id=row.id,
                    tenant_id=doc.tenant_id,
                    document_type=doc.document_type,
                    gateway=doc.gateway,
                    effective_date=doc.effective_date,
                    chunk_index=i,
                    content=text,
                    embedding=vector,
                )
                for i, (text, vector) in enumerate(zip(pieces, vectors, strict=True))
            )
            stats["indexed"] += 1
            stats["chunks"] += len(pieces)
        for stale in existing.values():
            await session.execute(delete(Document).where(Document.id == stale.id))
            stats["removed"] += 1
    return stats


async def run() -> None:
    settings = get_settings()
    embedder = get_embedder()
    docs = load_directory(Path(settings.knowledge_base_dir))
    try:
        stats = await index(docs, embedder)
    finally:
        await get_engine().dispose()
    log.info(
        "knowledge base indexed", extra={"embedder": embedder.name, "documents": len(docs), **stats}
    )


def main() -> None:
    configure_logging("kb-indexer")
    asyncio.run(run())


if __name__ == "__main__":
    main()
