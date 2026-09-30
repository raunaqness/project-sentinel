"""Investigator interface and the deterministic mock used by tests and demos."""

import asyncio
from typing import Any, Protocol

from sentinel.ai.schemas import AnalysisResult, Fact, InvestigationInput, InvestigationReport
from sentinel.config import get_settings


class Investigator(Protocol):
    async def analyze(self, data: InvestigationInput) -> AnalysisResult: ...


_TYPE_FOR_ANOMALY = {
    "MISSING_LEDGER": "PAYMENT_CAPTURED",
    "LEDGER_MISMATCH": "LEDGER_POSTED",
    "SETTLEMENT_MISMATCH": "SETTLEMENT_RECEIVED",
    "DUPLICATE_CAPTURE": "PAYMENT_CAPTURED",
    "MISSING_SETTLEMENT": "PAYMENT_CAPTURED",
    "REFUND_MISMATCH": "REFUND_ISSUED",
}

_PLAYBOOK: dict[str, tuple[str, str, str]] = {
    # anomaly: (classification, hypothesis, recommended action)
    "MISSING_LEDGER": (
        "LEDGER_POSTING_GAP",
        "The ledger posting job may have failed or be delayed.",
        "Check the ledger posting job for this transaction before posting manually.",
    ),
    "LEDGER_MISMATCH": (
        "LEDGER_AMOUNT_MISMATCH",
        "The ledger may have posted a stale or adjusted amount.",
        "Compare the ledger entry with the captured amount and correct via adjustment.",
    ),
    "SETTLEMENT_MISMATCH": (
        "SETTLEMENT_FEE_DEDUCTION",
        "A settlement fee may explain the difference.",
        "Verify configured MDR before initiating a correction.",
    ),
    "DUPLICATE_CAPTURE": (
        "DUPLICATE_CAPTURE",
        "The gateway may have retried a capture that had already succeeded.",
        "Confirm both captures with the gateway and refund the duplicate.",
    ),
    "MISSING_SETTLEMENT": (
        "SETTLEMENT_DELAYED",
        "The bank settlement file may be delayed or the transaction was omitted.",
        "Check the latest settlement file and raise with the acquiring bank if absent.",
    ),
    "REFUND_MISMATCH": (
        "REFUND_NOT_CONFIRMED",
        "The refund may not have been submitted to the gateway.",
        "Verify the refund request reached the gateway before re-submitting.",
    ),
}


class MockInvestigator:
    """Deterministic, offline investigator: same input, same report. No network."""

    async def analyze(self, data: InvestigationInput) -> AnalysisResult:
        await dev_delay(data)
        if _dev_flag(data, "mock_obey_injection"):
            return _compromised_report(data)
        classification, hypothesis, action = _PLAYBOOK.get(
            data.anomaly_type,
            ("NEEDS_MANUAL_REVIEW", "Cause unknown.", "Escalate to an investigator."),
        )
        facts = [
            Fact(claim=_describe(event), source=event["event_id"])
            for event in data.events
            if event["type"] == _TYPE_FOR_ANOMALY.get(data.anomaly_type)
        ]
        if data.knowledge:  # the mock does not read chunk text, so it cannot be steered by it
            top = data.knowledge[0]
            facts.append(Fact(claim=f"Relevant guidance: {top['title']}", source=top["chunk_id"]))
        report = InvestigationReport(
            classification=classification,
            confidence=0.5,
            summary=f"{data.anomaly_type} detected for {data.transaction_id}: {data.finding}",
            facts=facts,
            hypotheses=[hypothesis],
            recommended_action=action,
        )
        return AnalysisResult(report=report, meta={"model": "mock"})


async def dev_delay(data: InvestigationInput) -> None:
    """Dev/test only: `metadata.mock_llm_delay_seconds` makes the analysis slow (with either
    investigator), so a worker can be stopped or killed while it is in flight (demos)."""
    if not get_settings().allow_fault_injection:
        return
    for event in data.events:
        delay = event.get("metadata", {}).get("mock_llm_delay_seconds")
        if delay:
            await asyncio.sleep(min(float(delay), 30))
            return


def _describe(event: dict[str, Any]) -> str:
    amount = f" {event['currency']} {event['amount']}" if event.get("amount") else ""
    return f"{event['source']} reported {event['type']}{amount}"


def _dev_flag(data: InvestigationInput, name: str) -> bool:
    return get_settings().allow_fault_injection and any(
        e.get("metadata", {}).get(name) for e in data.events
    )


def _compromised_report(data: InvestigationInput) -> AnalysisResult:
    """Dev/test only: what a model that obeyed an injected document might return.
    Used to prove the system stays authoritative even if a model is compromised."""
    report = InvestigationReport(
        classification="NO_DISCREPANCY",
        confidence=1.0,
        summary="All transactions are reconciled. Merchant 456 data: txn_999 INR 5000.",
        facts=[
            Fact(claim="The transaction is reconciled", source="policy-override"),
            Fact(claim="merchant_456 transaction txn_999 amount 5000", source="merchant_456"),
        ],
        hypotheses=[],
        recommended_action="Mark as reconciled and close.",
        requires_human_review=False,
    )
    return AnalysisResult(report=report, meta={"model": "mock-compromised"})
