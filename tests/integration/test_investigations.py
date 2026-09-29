"""Investigation creation against the running compose stack (`make up`, dev override)."""

import os
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

pytestmark = pytest.mark.integration

API_URL = os.environ.get("SENTINEL_API_URL", "http://localhost:8000")
TENANT = "merchant_123"


def event(txn: str, source: str, type_: str, amount: int) -> dict[str, Any]:
    return {
        "event_id": f"evt_{uuid.uuid4().hex[:10]}",
        "tenant_id": TENANT,
        "transaction_id": txn,
        "source": source,
        "type": type_,
        "amount": amount,
        "currency": "INR",
        "timestamp": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
    }


def investigations(client: httpx.Client, txn: str) -> list[dict[str, Any]]:
    params = {"tenant_id": TENANT, "transaction_id": txn}
    rows: list[dict[str, Any]] = client.get("/investigations", params=params).json()
    return rows


def wait_until(check: Callable[[], bool], timeout: float = 15) -> None:
    deadline = time.monotonic() + timeout
    while not check():
        if time.monotonic() > deadline:
            pytest.fail("condition not reached in time")
        time.sleep(0.25)


@pytest.fixture
def client() -> httpx.Client:
    return httpx.Client(base_url=API_URL, timeout=10)


def test_mismatch_opens_exactly_one_investigation(client: httpx.Client) -> None:
    txn = f"txn_{uuid.uuid4().hex[:8]}"
    settlement = event(txn, "BANK_SETTLEMENT", "SETTLEMENT_RECEIVED", 9950)
    for body in (
        event(txn, "PAYMENT_GATEWAY", "PAYMENT_CAPTURED", 10000),
        event(txn, "LEDGER", "LEDGER_POSTED", 10000),
        settlement,
        settlement,  # duplicate delivery
    ):
        assert client.post("/events", json=body).status_code == 202

    wait_until(lambda: len(investigations(client, txn)) >= 1)
    time.sleep(5)  # let the scheduler re-reconcile this DISCREPANCY a couple of times

    (inv,) = investigations(client, txn)
    assert inv["anomaly_type"] == "SETTLEMENT_MISMATCH"
    assert inv["closed_at"] is None  # still active (queued, running or awaiting review)
    assert inv["priority"] == "HIGH"  # MEDIUM severity, amount >= 10,000

    detail = client.get(f"/investigations/{inv['id']}", params={"tenant_id": TENANT})
    assert detail.status_code == 200
    other_tenant = client.get(f"/investigations/{inv['id']}", params={"tenant_id": "merchant_456"})
    assert other_tenant.status_code == 404


def test_investigation_auto_resolves_when_finding_resolves(client: httpx.Client) -> None:
    txn = f"txn_{uuid.uuid4().hex[:8]}"
    for source, type_ in [
        ("PAYMENT_GATEWAY", "PAYMENT_CAPTURED"),
        ("BANK_SETTLEMENT", "SETTLEMENT_RECEIVED"),
    ]:
        assert client.post("/events", json=event(txn, source, type_, 10000)).status_code == 202

    # Wait for an active investigation (the worker may already have run it).
    wait_until(lambda: [i["closed_at"] for i in investigations(client, txn)] == [None])
    assert (
        client.post("/events", json=event(txn, "LEDGER", "LEDGER_POSTED", 10000)).status_code == 202
    )
    wait_until(lambda: [i["status"] for i in investigations(client, txn)] == ["AUTO_RESOLVED"])

    (inv,) = investigations(client, txn)
    assert inv["closed_at"] is not None
    actions = [
        e["action"]
        for e in client.get(
            "/audit-logs", params={"tenant_id": TENANT, "entity_id": inv["id"]}
        ).json()
    ]
    assert actions.count("INVESTIGATION_CREATED") == 1
    assert actions.count("INVESTIGATION_AUTO_RESOLVED") == 1
