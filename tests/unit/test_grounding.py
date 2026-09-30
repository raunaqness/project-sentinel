from sentinel.ai.grounding import ground
from sentinel.ai.schemas import Fact, InvestigationReport

EVENTS = [
    {"event_id": "evt_p", "type": "PAYMENT_CAPTURED", "amount": "10000.00", "currency": "INR"},
    {"event_id": "evt_s", "type": "SETTLEMENT_RECEIVED", "amount": "9950.00", "currency": "INR"},
]
CHUNKS = [
    {"chunk_id": "chunk_7", "content": "Merchant 123 pays a merchant discount rate of 0.5%."},
]
AUTHORITATIVE = {"finding": {"difference": "50.00"}, "transaction": {}}


def report(*facts: Fact) -> InvestigationReport:
    return InvestigationReport(
        classification="NEEDS_MANUAL_REVIEW",
        confidence=0.9,
        summary="s",
        facts=list(facts),
        hypotheses=[],
        recommended_action="a",
        requires_human_review=False,
    )


def test_supported_facts_kept() -> None:
    grounded, stats = ground(
        report(
            Fact(claim="Captured amount is INR 10,000", source="evt_p"),
            Fact(claim="Settlement is 9950, a difference of 50", source="evt_s"),
            Fact(claim="The agreed MDR is 0.5%", source="chunk_7"),
        ),
        EVENTS,
        CHUNKS,
        AUTHORITATIVE,
    )
    assert len(grounded.facts) == 3
    assert stats["unsupported_claims"] == []


def test_fee_rate_without_evidence_is_demoted() -> None:
    """Spec §11.1: 'The gateway charged 0.5% MDR' is unacceptable unless supported."""
    grounded, stats = ground(
        report(Fact(claim="The gateway charged 0.5% MDR", source="evt_s")),
        EVENTS,
        CHUNKS,
        AUTHORITATIVE,
    )
    assert grounded.facts == []
    assert grounded.hypotheses == ["Unverified: The gateway charged 0.5% MDR"]
    assert "0.5" in stats["unsupported_claims"][0]["reason"]


def test_unknown_source_is_demoted() -> None:
    grounded, stats = ground(
        report(Fact(claim="Merchant 456 had the same issue", source="evt_other_tenant")),
        EVENTS,
        CHUNKS,
        AUTHORITATIVE,
    )
    assert grounded.facts == []
    assert stats["unsupported_claims"][0]["reason"] == "unknown source"


def test_model_cannot_skip_human_review() -> None:
    grounded, _ = ground(report(), EVENTS, CHUNKS, AUTHORITATIVE)
    assert grounded.requires_human_review is True


def test_rule_output_and_state_are_citable() -> None:
    grounded, _ = ground(
        report(Fact(claim="The difference is INR 50.00", source="finding")),
        EVENTS,
        CHUNKS,
        AUTHORITATIVE,
    )
    assert len(grounded.facts) == 1


def test_vps_regression_invented_source_names_are_demoted_and_confidence_capped() -> None:
    """Real run: gpt-4o-mini cited 'TRANSACTION'/'FINDING' (not ids) with confidence 0.9."""
    grounded, stats = ground(
        report(
            Fact(claim="The payment amount is 10000.00 INR.", source="TRANSACTION"),
            Fact(claim="The difference is 50.00 INR.", source="FINDING"),
        ),
        EVENTS,
        CHUNKS,
        AUTHORITATIVE,
    )
    assert grounded.facts == []
    assert grounded.confidence == 0.0
    assert stats["model_confidence"] == 0.9
