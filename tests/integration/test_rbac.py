"""Authentication, role-based authorization, tenant isolation and human review
against the running compose stack (`make up` + `make seed`)."""

import os
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

pytestmark = pytest.mark.integration

API_URL = os.environ.get("SENTINEL_API_URL", "http://localhost:8000")
ClientFor = Callable[[str, str], httpx.Client]
ROLES = ["VIEWER", "INVESTIGATOR", "ADMIN", "SERVICE"]


def event(tenant: str, txn: str, source: str, type_: str, amount: int) -> dict[str, Any]:
    return {
        "event_id": f"evt_{uuid.uuid4().hex[:10]}",
        "tenant_id": tenant,
        "transaction_id": txn,
        "source": source,
        "type": type_,
        "amount": amount,
        "currency": "INR",
        "timestamp": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
    }


def mismatch_awaiting_review(client_for: ClientFor, tenant: str = "merchant_123") -> dict[str, Any]:
    service, reader = client_for(tenant, "SERVICE"), client_for(tenant, "VIEWER")
    txn = f"txn_{uuid.uuid4().hex[:8]}"
    for source, type_, amount in [
        ("PAYMENT_GATEWAY", "PAYMENT_CAPTURED", 10000),
        ("LEDGER", "LEDGER_POSTED", 10000),
        ("BANK_SETTLEMENT", "SETTLEMENT_RECEIVED", 9950),
    ]:
        assert (
            service.post("/events", json=event(tenant, txn, source, type_, amount)).status_code
            == 202
        )
    deadline = time.monotonic() + 30
    while True:
        rows: list[dict[str, Any]] = reader.get(
            "/investigations", params={"transaction_id": txn}
        ).json()
        if rows and rows[0]["status"] == "AWAITING_REVIEW":
            return rows[0]
        assert time.monotonic() < deadline, rows
        time.sleep(0.5)


# --- authentication ---------------------------------------------------------------


def test_missing_and_invalid_keys_are_rejected() -> None:
    anonymous = httpx.Client(base_url=API_URL)
    assert anonymous.get("/investigations").status_code == 401
    bad = httpx.Client(base_url=API_URL, headers={"X-API-Key": "sk_not_a_real_key"})
    assert bad.get("/investigations").status_code == 401
    assert anonymous.get("/health").status_code == 200  # probes stay public


# --- role matrix --------------------------------------------------------------------


@pytest.mark.parametrize("role", ROLES)
def test_role_permission_matrix(client_for: ClientFor, role: str) -> None:
    c = client_for("merchant_123", role)
    readers = {"VIEWER", "INVESTIGATOR", "ADMIN"}
    reviewers = {"INVESTIGATOR", "ADMIN"}
    ingestors = {"ADMIN", "SERVICE"}

    def allowed(status: int) -> bool:
        return status not in (401, 403)

    assert allowed(c.get("/investigations").status_code) == (role in readers)
    assert allowed(c.get("/transactions/txn_nope").status_code) == (
        role in readers
    )  # 404 if allowed
    assert allowed(c.get("/knowledge/search", params={"q": "fee"}).status_code) == (role in readers)
    assert allowed(c.get("/audit-logs").status_code) == (role == "ADMIN")
    fake = uuid.uuid4()
    assert allowed(c.post(f"/investigations/{fake}/approve", json={}).status_code) == (
        role in reviewers
    )
    body = event("merchant_123", f"txn_{uuid.uuid4().hex[:8]}", "LEDGER", "LEDGER_POSTED", 1)
    assert allowed(c.post("/events", json=body).status_code) == (role in ingestors)


# --- tenant isolation (spec §24) -----------------------------------------------------


def test_tenant_a_cannot_access_tenant_b_resources(client_for: ClientFor) -> None:
    inv = mismatch_awaiting_review(client_for, "merchant_123")
    txn, inv_id = inv["transaction_id"], inv["id"]
    other = client_for("merchant_456", "ADMIN")

    assert other.get(f"/transactions/{txn}").status_code == 404
    assert other.get(f"/investigations/{inv_id}").status_code == 404
    assert other.post(f"/investigations/{inv_id}/approve", json={}).status_code == 404
    assert other.post(f"/investigations/{inv_id}/retry", json={}).status_code == 404
    assert other.get("/events", params={"transaction_id": txn}).json() == []
    assert other.get("/investigations", params={"transaction_id": txn}).json() == []
    assert other.get("/audit-logs", params={"entity_id": inv_id}).json() == []
    assert all(f["transaction_id"] != txn for f in other.get("/reconciliation-results").json())

    # ...while the owning tenant still sees everything
    owner = client_for("merchant_123", "ADMIN")
    assert owner.get(f"/investigations/{inv_id}").status_code == 200


# --- human review -------------------------------------------------------------------


def test_approve_records_reviewer_and_closes(client_for: ClientFor) -> None:
    inv = mismatch_awaiting_review(client_for)
    assert (
        client_for("merchant_123", "VIEWER")
        .post(f"/investigations/{inv['id']}/approve", json={})
        .status_code
        == 403
    )

    reviewer = client_for("merchant_123", "INVESTIGATOR")
    response = reviewer.post(
        f"/investigations/{inv['id']}/approve", json={"comment": "fee confirmed"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "APPROVED" and body["closed_at"] and body["reviewed_by"]
    assert body["review_comment"] == "fee confirmed"

    assert reviewer.post(f"/investigations/{inv['id']}/approve", json={}).status_code == 409
    assert reviewer.post(f"/investigations/{inv['id']}/reject", json={}).status_code == 409
    actions = [
        e["action"]
        for e in client_for("merchant_123", "ADMIN")
        .get("/audit-logs", params={"entity_id": inv["id"]})
        .json()
    ]
    assert "INVESTIGATION_APPROVED" in actions


def test_concurrent_reviews_only_one_wins(client_for: ClientFor) -> None:
    inv = mismatch_awaiting_review(client_for)
    url = f"/investigations/{inv['id']}"
    reviewers = [client_for("merchant_123", "INVESTIGATOR"), client_for("merchant_123", "ADMIN")]
    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = sorted(
            pool.map(
                lambda pair: pair[0].post(f"{url}/{pair[1]}", json={}).status_code,
                zip(reviewers, ["approve", "reject"], strict=True),
            )
        )
    assert codes == [200, 409]


def test_retry_reruns_the_workflow(client_for: ClientFor) -> None:
    inv = mismatch_awaiting_review(client_for)
    reviewer = client_for("merchant_123", "INVESTIGATOR")
    response = reviewer.post(f"/investigations/{inv['id']}/retry", json={"comment": "re-check"})
    assert response.status_code == 202
    assert response.json()["status"] == "OPEN" and response.json()["steps"] == []

    deadline = time.monotonic() + 30
    while (detail := reviewer.get(f"/investigations/{inv['id']}").json())[
        "status"
    ] != "AWAITING_REVIEW":
        assert time.monotonic() < deadline, detail
        time.sleep(0.5)
    assert len(detail["steps"]) == 7

    reviewer.post(f"/investigations/{inv['id']}/reject", json={})
    assert reviewer.post(f"/investigations/{inv['id']}/retry", json={}).status_code == 409
