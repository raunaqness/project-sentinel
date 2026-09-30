"""Knowledge-base retrieval against the running compose stack (`make up`)."""

import os
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sentinel.config import get_settings
from sentinel.retrieval.search import search as hybrid_search

pytestmark = pytest.mark.integration

API_URL = os.environ.get("SENTINEL_API_URL", "http://localhost:8000")
PRIVATE = {"merchant_123": "merchant-123-", "merchant_456": "merchant-456-"}


@pytest.fixture
def search(client_for: Callable[[str, str], httpx.Client]) -> Callable[..., list[dict[str, Any]]]:
    """Search as the given tenant (its VIEWER key); the tenant comes from the key."""

    def run(tenant: str, q: str, **params: Any) -> list[dict[str, Any]]:
        return _search(client_for(tenant, "VIEWER"), q, **params)

    return run


def _search(client: httpx.Client, q: str, **params: Any) -> list[dict[str, Any]]:
    response = client.get("/knowledge/search", params={"q": q, "k": 20, **params})
    assert response.status_code == 200
    rows: list[dict[str, Any]] = response.json()
    return rows


@pytest.mark.parametrize("tenant", ["merchant_123", "merchant_456"])
def test_tenant_never_sees_another_tenants_private_documents(
    search: Callable[..., list[dict[str, Any]]], tenant: str
) -> None:
    others = [prefix for t, prefix in PRIVATE.items() if t != tenant]
    for q in ["merchant fee agreement discount rate", "incident report outage duplicate", "ledger"]:
        for row in search(tenant, q):
            assert row["scope"] in ("global", tenant)
            assert not any(row["doc_key"].startswith(p) for p in others)


def test_tenant_sees_its_own_private_documents(search: Callable[..., list[dict[str, Any]]]) -> None:
    keys = [r["doc_key"] for r in search("merchant_123", "fee agreement discount rate")]
    assert "merchant-123-fee-agreement" in keys
    assert "merchant-456-fee-agreement" not in keys


def test_metadata_filters(search: Callable[..., list[dict[str, Any]]]) -> None:
    rows = search("merchant_123", "settlement", document_type="gateway_guide")
    assert rows and {r["document_type"] for r in rows} == {"gateway_guide"}
    beta_only = {r["doc_key"] for r in search("merchant_456", "settlement", gateway="GATEWAY_BETA")}
    assert "gateway-alpha-guide" not in beta_only


def test_investigation_uses_and_cites_knowledge(client: httpx.Client) -> None:
    txn = f"txn_{uuid.uuid4().hex[:8]}"
    ts = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    for source, type_, amount in [
        ("PAYMENT_GATEWAY", "PAYMENT_CAPTURED", 10000),
        ("LEDGER", "LEDGER_POSTED", 10000),
        ("BANK_SETTLEMENT", "SETTLEMENT_RECEIVED", 9950),
    ]:
        body = {
            "event_id": f"evt_{uuid.uuid4().hex[:10]}",
            "tenant_id": "merchant_123",
            "transaction_id": txn,
            "source": source,
            "type": type_,
            "amount": amount,
            "currency": "INR",
            "timestamp": ts,
            "metadata": {"gateway": "GATEWAY_ALPHA"},
        }
        assert client.post("/events", json=body).status_code == 202

    deadline = time.monotonic() + 30
    while True:
        rows = client.get("/investigations", params={"transaction_id": txn}).json()
        if rows and rows[0]["status"] == "AWAITING_REVIEW":
            break
        assert time.monotonic() < deadline, rows
        time.sleep(0.5)

    report = rows[0]["report"]
    cited = [f["source"] for f in report["facts"] if f["source"].startswith("chunk_")]
    assert cited, report


class _DownEmbedder:
    name = "down"

    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise httpx.ConnectError("embedding provider unreachable")


async def test_embedding_outage_degrades_to_full_text_search() -> None:
    engine = create_async_engine(str(get_settings().database_url))
    try:
        async with async_sessionmaker(engine)() as session:
            result = await hybrid_search(
                session,
                _DownEmbedder(),
                tenant_id="merchant_123",
                query="merchant discount rate deducted at settlement",
            )
    finally:
        await engine.dispose()
    assert result.mode == "text-only"
    assert "merchant-123-fee-agreement" in {c.doc_key for c in result.chunks}
    assert all(c.scope in ("merchant_123", "global") for c in result.chunks)  # still scoped
