"""Out-of-order delivery against the running compose stack (`make up`)."""

import os
import time
import uuid
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
        "timestamp": "2026-09-29T10:30:00Z",
    }


def wait_for_state(client: httpx.Client, txn: str, event_count: int) -> dict[str, Any]:
    deadline = time.monotonic() + 15
    while True:
        response = client.get(f"/transactions/{txn}", params={"tenant_id": TENANT})
        if response.status_code == 200 and response.json()["event_count"] >= event_count:
            body: dict[str, Any] = response.json()
            return body
        if time.monotonic() > deadline:
            pytest.fail(f"state for {txn} not ready: {response.status_code} {response.text}")
        time.sleep(0.25)


@pytest.fixture
def client() -> httpx.Client:
    return httpx.Client(base_url=API_URL, timeout=10)


def test_out_of_order_with_duplicate_reaches_correct_state(client: httpx.Client) -> None:
    txn = f"txn_{uuid.uuid4().hex[:8]}"
    settlement = event(txn, "BANK_SETTLEMENT", "SETTLEMENT_RECEIVED", 9950)
    ledger = event(txn, "LEDGER", "LEDGER_POSTED", 10000)
    payment = event(txn, "PAYMENT_GATEWAY", "PAYMENT_CAPTURED", 10000)

    # The spec's arrival order: settlement, ledger, payment, payment (duplicate).
    for body in (settlement, ledger, payment, payment):
        assert client.post("/events", json=body).status_code == 202

    state = wait_for_state(client, txn, event_count=3)
    assert state["event_count"] == 3
    assert state["capture_count"] == 1
    assert state["payment_amount"] == "10000.00"
    assert state["ledger_amount"] == "10000.00"
    assert state["settlement_amount"] == "9950.00"
    assert state["state"] == "DISCREPANCY"


def test_healthy_transaction_matches(client: httpx.Client) -> None:
    txn = f"txn_{uuid.uuid4().hex[:8]}"
    for source, type_ in [
        ("LEDGER", "LEDGER_POSTED"),
        ("PAYMENT_GATEWAY", "PAYMENT_CAPTURED"),
        ("BANK_SETTLEMENT", "SETTLEMENT_RECEIVED"),
    ]:
        assert client.post("/events", json=event(txn, source, type_, 10000)).status_code == 202

    assert wait_for_state(client, txn, event_count=3)["state"] == "MATCHED"


def test_unknown_transaction_is_404(client: httpx.Client) -> None:
    response = client.get("/transactions/txn_nope", params={"tenant_id": TENANT})
    assert response.status_code == 404
