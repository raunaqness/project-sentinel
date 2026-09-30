"""Parsing knowledge-base markdown (front-matter + body) and splitting it into chunks."""

import re
from dataclasses import dataclass
from datetime import date

MAX_CHUNK_CHARS = 800


@dataclass(frozen=True)
class ParsedDocument:
    doc_key: str
    title: str
    tenant_id: str | None
    document_type: str
    gateway: str | None
    effective_date: date | None
    body: str


def parse_document(text: str) -> ParsedDocument:
    """Parse `---`-delimited `key: value` front-matter. Empty or `null` values become None."""
    match = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
    if match is None:
        raise ValueError("document has no front-matter")
    meta: dict[str, str | None] = {}
    for line in match.group(1).splitlines():
        key, _, value = line.partition(":")
        value = value.strip()
        meta[key.strip()] = None if value in ("", "null") else value
    for required in ("doc_key", "title", "document_type"):
        if not meta.get(required):
            raise ValueError(f"front-matter is missing {required}")
    effective = meta.get("effective_date")
    return ParsedDocument(
        doc_key=str(meta["doc_key"]),
        title=str(meta["title"]),
        tenant_id=meta.get("tenant_id"),
        document_type=str(meta["document_type"]),
        gateway=meta.get("gateway"),
        effective_date=date.fromisoformat(effective) if effective else None,
        body=match.group(2).strip(),
    )


def chunk(title: str, body: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """Pack paragraphs into chunks of at most `max_chars`, each prefixed with the document
    title and nearest heading so a chunk is understandable (and retrievable) on its own."""
    chunks: list[str] = []
    heading = ""
    current: list[str] = []

    def flush() -> None:
        if current:
            prefix = f"{title} — {heading}" if heading else title
            chunks.append(prefix + "\n\n" + "\n\n".join(current))
            current.clear()

    for paragraph in (p.strip() for p in body.split("\n\n")):
        if not paragraph:
            continue
        if paragraph.startswith("#"):
            flush()
            heading = paragraph.lstrip("#").strip()
            continue
        for piece in _split_long(paragraph, max_chars):
            if sum(len(c) for c in current) + len(piece) > max_chars:
                flush()
            current.append(piece)
    flush()
    return chunks


def _split_long(paragraph: str, max_chars: int) -> list[str]:
    if len(paragraph) <= max_chars:
        return [paragraph]
    pieces, current = [], ""
    for sentence in re.split(r"(?<=[.!?])\s+", paragraph):
        if current and len(current) + len(sentence) + 1 > max_chars:
            pieces.append(current)
            current = ""
        current = f"{current} {sentence}".strip()
    if current:
        pieces.append(current)
    return pieces
