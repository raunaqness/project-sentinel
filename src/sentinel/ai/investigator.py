"""Investigator interface and the deterministic mock used by tests and demos."""

from typing import Any, Protocol

from sentinel.ai.schemas import Fact, InvestigationInput, InvestigationReport


class Investigator(Protocol):
    async def analyze(self, data: InvestigationInput) -> InvestigationReport: ...


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
        "SETTLEMENT_FEE_MISMATCH",
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
        "REFUND_NOT_PROCESSED_BY_GATEWAY",
        "The refund may not have been submitted to the gateway.",
        "Verify the refund request reached the gateway before re-submitting.",
    ),
}


class MockInvestigator:
    """Deterministic, offline investigator: same input, same report. No network."""

    async def analyze(self, data: InvestigationInput) -> InvestigationReport:
        classification, hypothesis, action = _PLAYBOOK.get(
            data.anomaly_type,
            ("UNCLASSIFIED", "Cause unknown.", "Escalate to an investigator."),
        )
        facts = [
            Fact(claim=_describe(event), source=event["event_id"])
            for event in data.events
            if event["type"] == _TYPE_FOR_ANOMALY.get(data.anomaly_type)
        ]
        if data.knowledge:  # the mock does not read chunk text, so it cannot be steered by it
            top = data.knowledge[0]
            facts.append(Fact(claim=f"Relevant guidance: {top['title']}", source=top["chunk_id"]))
        return InvestigationReport(
            classification=classification,
            confidence=0.5,
            summary=f"{data.anomaly_type} detected for {data.transaction_id}: {data.finding}",
            facts=facts,
            hypotheses=[hypothesis],
            recommended_action=action,
        )


def _describe(event: dict[str, Any]) -> str:
    amount = f" {event['currency']} {event['amount']}" if event.get("amount") else ""
    return f"{event['source']} reported {event['type']}{amount}"
