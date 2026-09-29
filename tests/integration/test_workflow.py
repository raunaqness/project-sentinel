"""Workflow and crash recovery against the running compose stack (`make up`, dev override).

The dev override gives the worker a 5s lease and enables per-event fault injection:
an event with metadata.fail_after_step makes the *real* worker container hard-crash
(os._exit) on that investigation's first attempt. Docker restarts it; the job must
resume from its last checkpoint and finish exactly once.
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


def mismatch_events(txn: str, fault: str | None = None) -> list[dict[str, Any]]:
    ts = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    events = []
    for source, type_, amount in [
        ("PAYMENT_GATEWAY", "PAYMENT_CAPTURED", 10000),
        ("LEDGER", "LEDGER_POSTED", 10000),
        ("BANK_SETTLEMENT", "SETTLEMENT_RECEIVED", 9950),
    ]:
        events.append(
            {
                "event_id": f"evt_{uuid.uuid4().hex[:10]}",
                "tenant_id": TENANT,
                "transaction_id": txn,
                "source": source,
                "type": type_,
                "amount": amount,
                "currency": "INR",
                "timestamp": ts,
                "metadata": {"fail_after_step": fault} if fault else {},
            }
        )
    return events


def wait_for(fetch: Callable[[], Any], ready: Callable[[Any], bool], timeout: float = 45) -> Any:
    deadline = time.monotonic() + timeout
    while True:
        value = fetch()
        if ready(value):
            return value
        if time.monotonic() > deadline:
            pytest.fail(f"not ready in time: {value}")
        time.sleep(0.5)


@pytest.fixture
def client() -> httpx.Client:
    return httpx.Client(base_url=API_URL, timeout=10)


def run_to_review(client: httpx.Client, fault: str | None) -> dict[str, Any]:
    txn = f"txn_{uuid.uuid4().hex[:8]}"
    for body in mismatch_events(txn, fault):
        assert client.post("/events", json=body).status_code == 202

    def listing() -> list[dict[str, Any]]:
        params = {"tenant_id": TENANT, "transaction_id": txn}
        rows: list[dict[str, Any]] = client.get("/investigations", params=params).json()
        return rows

    (inv,) = wait_for(listing, lambda rows: [r["status"] for r in rows] == ["AWAITING_REVIEW"])
    detail: dict[str, Any] = client.get(
        f"/investigations/{inv['id']}", params={"tenant_id": TENANT}
    ).json()
    return detail


def audit_actions(client: httpx.Client, investigation_id: str) -> list[str]:
    params = {"tenant_id": TENANT, "entity_id": investigation_id}
    return sorted(e["action"] for e in client.get("/audit-logs", params=params).json())


def test_happy_path_produces_verified_report(client: httpx.Client) -> None:
    inv = run_to_review(client, fault=None)
    assert inv["attempts"] == 1
    assert inv["llm_requests"] == 1
    assert [s["step"] for s in inv["steps"]] == [
        "STARTED",
        "TRANSACTION_DATA_COLLECTED",
        "RELATED_EVENTS_COLLECTED",
        "KNOWLEDGE_RETRIEVED",
        "AI_ANALYSIS_COMPLETED",
        "RESULT_VERIFIED",
        "COMPLETED",
    ]
    report = inv["report"]
    assert report["classification"] == "SETTLEMENT_FEE_MISMATCH"
    assert report["facts"] and report["requires_human_review"] is True


def test_crash_after_llm_response_before_checkpoint(client: httpx.Client) -> None:
    """Spec §9: killed after the LLM answered but before the result was committed."""
    inv = run_to_review(client, fault="LLM_RESPONSE")
    assert inv["attempts"] == 2
    assert inv["llm_requests"] == 2  # the uncommitted answer is lost, so the call is redone
    steps = {s["step"]: s["attempt"] for s in inv["steps"]}
    assert steps["KNOWLEDGE_RETRIEVED"] == 1  # earlier checkpoints reused, not redone
    assert steps["AI_ANALYSIS_COMPLETED"] == 2
    assert len(inv["steps"]) == 7  # each step recorded exactly once
    assert "WORKFLOW_RESUMED" in audit_actions(client, inv["id"])


def test_crash_after_verification_reuses_llm_result(client: httpx.Client) -> None:
    inv = run_to_review(client, fault="RESULT_VERIFIED")
    assert inv["attempts"] == 2
    assert inv["llm_requests"] == 1  # analysis was checkpointed, so no second LLM call
    steps = {s["step"]: s["attempt"] for s in inv["steps"]}
    assert steps["RESULT_VERIFIED"] == 1
    assert steps["COMPLETED"] == 2
    assert audit_actions(client, inv["id"]).count("INVESTIGATION_COMPLETED") == 1
