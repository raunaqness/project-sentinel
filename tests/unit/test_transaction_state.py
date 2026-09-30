from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import permutations

from sentinel.domain.transaction_state import TxnState, compute_state, overall_state

T0 = datetime(2026, 9, 29, 10, 30, tzinfo=UTC)


@dataclass
class Ev:
    event_id: str
    type: str
    amount: Decimal | None = Decimal("10000")
    currency: str | None = "INR"
    event_timestamp: datetime = T0
    received_at: datetime = T0


def healthy() -> list[Ev]:
    return [
        Ev("evt_p", "PAYMENT_CAPTURED"),
        Ev("evt_l", "LEDGER_POSTED", event_timestamp=T0 + timedelta(minutes=1)),
        Ev("evt_s", "SETTLEMENT_RECEIVED", event_timestamp=T0 + timedelta(days=1)),
    ]


def test_healthy_transaction_facts() -> None:
    facts = compute_state(healthy())
    assert facts.payment_status == "SUCCESS"
    assert facts.ledger_status == "POSTED"
    assert facts.settlement_status == "RECEIVED"
    assert facts.capture_count == 1
    assert overall_state(facts, has_open_findings=False) is TxnState.MATCHED


def test_arrival_order_does_not_matter() -> None:
    results = {compute_state(list(order)) for order in permutations(healthy())}
    assert len(results) == 1


def test_mismatched_amounts_are_recorded_order_independently() -> None:
    events = healthy()
    events[2].amount = Decimal("9950")
    results = {compute_state(list(o)) for o in permutations(events)}
    assert len(results) == 1
    facts = results.pop()
    assert (facts.payment_amount, facts.settlement_amount) == (Decimal("10000"), Decimal("9950"))


def test_open_findings_mean_discrepancy() -> None:
    assert overall_state(compute_state(healthy()), has_open_findings=True) is TxnState.DISCREPANCY


def test_missing_ledger_is_pending() -> None:
    facts = compute_state([healthy()[0], healthy()[2]])
    assert facts.ledger_status is None
    assert overall_state(facts, has_open_findings=False) is TxnState.PENDING


def test_duplicate_capture_counted() -> None:
    events = [
        *healthy(),
        Ev("evt_p2", "PAYMENT_CAPTURED", event_timestamp=T0 + timedelta(seconds=5)),
    ]
    facts = compute_state(events)
    assert facts.capture_count == 2
    assert facts.payment_captured_at == T0  # earliest capture


def test_failed_payment() -> None:
    facts = compute_state([Ev("evt_f", "PAYMENT_FAILED", None, None)])
    assert overall_state(facts, has_open_findings=False) is TxnState.FAILED


def test_unconfirmed_refund_keeps_transaction_pending() -> None:
    facts = compute_state([*healthy(), Ev("evt_r1", "REFUND_ISSUED", Decimal("500"))])
    assert overall_state(facts, has_open_findings=False) is TxnState.PENDING


def test_refund_totals() -> None:
    events = [
        *healthy(),
        Ev("evt_r1", "REFUND_ISSUED", Decimal("500")),
        Ev("evt_r2", "REFUND_ISSUED", Decimal("250")),
        Ev("evt_g1", "REFUND_PROCESSED", Decimal("750")),
    ]
    facts = compute_state(events)
    assert facts.internal_refund_amount == Decimal("750")
    assert facts.gateway_refund_amount == Decimal("750")
    assert facts.event_count == 6
    assert overall_state(facts, has_open_findings=False) is TxnState.MATCHED
