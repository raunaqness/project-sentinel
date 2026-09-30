import asyncio
from typing import Any, cast

from sentinel.ai.investigator import MockInvestigator
from sentinel.ai.schemas import InvestigationInput
from sentinel.workflow.failure_injection import VALID_POINTS
from sentinel.workflow.states import STEPS, Step, remaining
from sentinel.workflow.steps import StepContext, verify

EVENTS = [
    {
        "event_id": "evt_p",
        "source": "PAYMENT_GATEWAY",
        "type": "PAYMENT_CAPTURED",
        "amount": "10000.00",
        "currency": "INR",
    },
    {
        "event_id": "evt_s",
        "source": "BANK_SETTLEMENT",
        "type": "SETTLEMENT_RECEIVED",
        "amount": "9950.00",
        "currency": "INR",
    },
]


def test_step_order_matches_spec() -> None:
    assert [s.value for s in STEPS] == [
        "STARTED",
        "TRANSACTION_DATA_COLLECTED",
        "RELATED_EVENTS_COLLECTED",
        "KNOWLEDGE_RETRIEVED",
        "AI_ANALYSIS_COMPLETED",
        "RESULT_VERIFIED",
        "COMPLETED",
    ]


def test_resume_skips_completed_steps() -> None:
    done = {Step.STARTED, Step.TRANSACTION_DATA_COLLECTED, Step.RELATED_EVENTS_COLLECTED}
    assert remaining(set(done))[0] is Step.KNOWLEDGE_RETRIEVED
    assert remaining(set(STEPS)) == []


def test_llm_response_is_a_valid_failure_point() -> None:
    assert "LLM_RESPONSE" in VALID_POINTS
    assert "RESULT_VERIFIED" in VALID_POINTS


def mock_report(anomaly: str = "SETTLEMENT_MISMATCH") -> dict[str, Any]:
    data = InvestigationInput(
        tenant_id="merchant_123",
        transaction_id="txn_1",
        anomaly_type=anomaly,
        finding={"difference": "50.00"},
        transaction={},
        events=EVENTS,
    )
    return asyncio.run(MockInvestigator().analyze(data)).report.model_dump(mode="json")


def test_mock_investigator_is_deterministic_and_cites_events() -> None:
    report = mock_report()
    assert report == mock_report()
    assert report["classification"] == "SETTLEMENT_FEE_DEDUCTION"
    assert [f["source"] for f in report["facts"]] == ["evt_s"]
    assert report["requires_human_review"] is True


def context(report: dict[str, Any]) -> StepContext:
    outputs = {
        Step.TRANSACTION_DATA_COLLECTED: {"finding": {"difference": "50.00"}, "transaction": {}},
        Step.RELATED_EVENTS_COLLECTED: {"events": EVENTS},
        Step.KNOWLEDGE_RETRIEVED: {"chunks": []},
        Step.AI_ANALYSIS_COMPLETED: {"report": report},
    }
    return cast(StepContext, type("Ctx", (), {"outputs": outputs})())


def test_verify_keeps_cited_facts() -> None:
    out = asyncio.run(verify(context(mock_report())))
    assert out["verification"]["facts_supported"] == 1


def test_verify_demotes_unsupported_facts() -> None:
    report = mock_report()
    report["facts"].append({"claim": "Gateway charged 0.5% MDR", "source": "evt_made_up"})
    out = asyncio.run(verify(context(report)))
    assert out["verification"]["facts_supported"] == 1
    assert "Unverified: Gateway charged 0.5% MDR" in out["report"]["hypotheses"]
