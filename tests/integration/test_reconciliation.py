"""Reconciliation and audit against the running compose stack (`make up`).

Assumes the dev compose override (2s grace period, 2s scheduler interval).
"""

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
AN_HOUR_AGO = (datetime.now(UTC) - timedelta(hours=1)).isoformat()


def event(txn: str, source: str, type_: str, amount: int) -> dict[str, Any]:
    return {
        "event_id": f"evt_{uuid.uuid4().hex[:10]}",
        "tenant_id": TENANT,
        "transaction_id": txn,
        "source": source,
        "type": type_,
        "amount": amount,
        "currency": "INR",
        "timestamp": AN_HOUR_AGO,
    }


def wait_for(
    client: httpx.Client, txn: str, ready: Callable[[dict[str, Any]], bool]
) -> dict[str, Any]:
    deadline = time.monotonic() + 15
    while True:
        response = client.get(f"/transactions/{txn}", params={"tenant_id": TENANT})
        if response.status_code == 200 and ready(body := response.json()):
            return body  # type: ignore[no-any-return]
        if time.monotonic() > deadline:
            pytest.fail(f"{txn} never became ready: {response.text}")
        time.sleep(0.25)


def statuses(txn: dict[str, Any]) -> dict[str, str]:
    return {f["anomaly_type"]: f["status"] for f in txn["findings"]}


@pytest.fixture
def client() -> httpx.Client:
    return httpx.Client(base_url=API_URL, timeout=10)


def test_missing_ledger_opens_then_resolves(client: httpx.Client) -> None:
    txn = f"txn_{uuid.uuid4().hex[:8]}"
    for source, type_ in [
        ("PAYMENT_GATEWAY", "PAYMENT_CAPTURED"),
        ("BANK_SETTLEMENT", "SETTLEMENT_RECEIVED"),
    ]:
        assert client.post("/events", json=event(txn, source, type_, 10000)).status_code == 202

    # Opened by the scheduler once the grace period since arrival has passed.
    state = wait_for(client, txn, lambda t: statuses(t).get("MISSING_LEDGER") == "OPEN")
    assert state["state"] == "DISCREPANCY"

    assert (
        client.post("/events", json=event(txn, "LEDGER", "LEDGER_POSTED", 10000)).status_code == 202
    )
    state = wait_for(client, txn, lambda t: t["event_count"] == 3)
    assert state["state"] == "MATCHED"
    assert statuses(state) == {"MISSING_LEDGER": "RESOLVED"}

    actions = [
        e["action"]
        for e in client.get("/audit-logs", params={"tenant_id": TENANT, "entity_id": txn}).json()
    ]
    assert sorted(actions) == ["DISCREPANCY_DETECTED", "DISCREPANCY_RESOLVED"]


def test_settlement_mismatch_listed_as_open_finding(client: httpx.Client) -> None:
    txn = f"txn_{uuid.uuid4().hex[:8]}"
    for source, type_, amount in [
        ("PAYMENT_GATEWAY", "PAYMENT_CAPTURED", 10000),
        ("LEDGER", "LEDGER_POSTED", 10000),
        ("BANK_SETTLEMENT", "SETTLEMENT_RECEIVED", 9950),
    ]:
        assert client.post("/events", json=event(txn, source, type_, amount)).status_code == 202

    state = wait_for(client, txn, lambda t: t["event_count"] == 3)
    open_now = {k for k, v in statuses(state).items() if v == "OPEN"}
    assert open_now == {"SETTLEMENT_MISMATCH"}
    (finding,) = [f for f in state["findings"] if f["anomaly_type"] == "SETTLEMENT_MISMATCH"]
    assert finding["details"]["difference"] == "50.00"

    open_findings = client.get(
        "/reconciliation-results", params={"tenant_id": TENANT, "status": "OPEN"}
    ).json()
    assert any(f["transaction_id"] == txn for f in open_findings)


def test_every_stored_event_is_audited(client: httpx.Client) -> None:
    txn = f"txn_{uuid.uuid4().hex[:8]}"
    body = event(txn, "PAYMENT_GATEWAY", "PAYMENT_CAPTURED", 10000)
    for _ in range(3):  # duplicates must not create extra audit rows
        assert client.post("/events", json=body).status_code == 202
    wait_for(client, txn, lambda t: t["event_count"] == 1)
    time.sleep(0.5)

    entries = client.get(
        "/audit-logs", params={"tenant_id": TENANT, "entity_id": body["event_id"]}
    ).json()
    assert [e["action"] for e in entries] == ["EVENT_RECEIVED"]
    assert entries[0]["actor"] == "system:event-consumer"
