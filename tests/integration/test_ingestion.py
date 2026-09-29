"""End-to-end ingestion against the running compose stack (`make up`)."""

import os
import time
import uuid
from typing import Any

import httpx
import pytest

pytestmark = pytest.mark.integration

API_URL = os.environ.get("SENTINEL_API_URL", "http://localhost:8000")


def wait_for_events(
    client: httpx.Client, tenant_id: str, transaction_id: str, count: int
) -> list[dict[str, Any]]:
    deadline = time.monotonic() + 15
    while True:
        rows: list[dict[str, Any]] = client.get(
            "/events", params={"transaction_id": transaction_id}
        ).json()
        if len(rows) >= count or time.monotonic() > deadline:
            return rows
        time.sleep(0.25)


def test_event_is_stored_once_even_if_sent_twice(client: httpx.Client) -> None:
    txn = f"txn_{uuid.uuid4().hex[:8]}"
    event = {
        "event_id": f"evt_{uuid.uuid4().hex[:8]}",
        "tenant_id": "merchant_123",
        "transaction_id": txn,
        "source": "PAYMENT_GATEWAY",
        "type": "PAYMENT_CAPTURED",
        "amount": 10000,
        "currency": "INR",
        "timestamp": "2026-09-29T10:30:00Z",
    }
    for _ in range(2):
        assert client.post("/events", json=event).status_code == 202

    # A second, different event acts as a marker: once it is stored, the
    # duplicate (sent earlier on the same partition) has been processed too.
    marker = event | {"event_id": f"evt_{uuid.uuid4().hex[:8]}", "type": "LEDGER_POSTED"}
    assert client.post("/events", json=marker).status_code == 202

    rows = wait_for_events(client, "merchant_123", txn, count=2)
    assert sorted(r["event_id"] for r in rows) == sorted([event["event_id"], marker["event_id"]])


def test_malformed_event_rejected(client: httpx.Client) -> None:
    response = client.post("/events", json={"event_id": "evt_bad"})
    assert response.status_code == 422


def test_event_for_another_tenant_is_forbidden(client: httpx.Client) -> None:
    """The merchant_123 key cannot submit events on behalf of merchant_456."""
    event = {
        "event_id": "evt_x",
        "tenant_id": "merchant_456",
        "transaction_id": "txn_x",
        "source": "LEDGER",
        "type": "LEDGER_POSTED",
        "amount": 1,
        "currency": "INR",
        "timestamp": "2026-09-29T10:30:00Z",
    }
    assert client.post("/events", json=event).status_code == 403
