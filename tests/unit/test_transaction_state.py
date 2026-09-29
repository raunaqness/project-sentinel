from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import permutations

from sentinel.domain.transaction_state import TxnState, compute_state

T0 = datetime(2026, 9, 29, 10, 30, tzinfo=UTC)


@dataclass
class Ev:
    event_id: str
    type: str
    amount: Decimal | None = Decimal("10000")
    currency: str | None = "INR"
    event_timestamp: datetime = T0


def healthy() -> list[Ev]:
    return [
        Ev("evt_p", "PAYMENT_CAPTURED"),
        Ev("evt_l", "LEDGER_POSTED", event_timestamp=T0 + timedelta(minutes=1)),
        Ev("evt_s", "SETTLEMENT_RECEIVED", event_timestamp=T0 + timedelta(days=1)),
    ]


def test_healthy_transaction_matches() -> None:
    state = compute_state(healthy())
    assert state.state is TxnState.MATCHED
    assert state.payment_status == "SUCCESS"
    assert state.ledger_status == "POSTED"
    assert state.settlement_status == "RECEIVED"
    assert state.capture_count == 1


def test_arrival_order_does_not_matter() -> None:
    results = {compute_state(list(order)) for order in permutations(healthy())}
    assert len(results) == 1


def test_settlement_amount_mismatch() -> None:
    events = healthy()
    events[2].amount = Decimal("9950")
    state = compute_state(events)
    assert state.state is TxnState.DISCREPANCY
    assert state.payment_amount == Decimal("10000")
    assert state.settlement_amount == Decimal("9950")


def test_out_of_order_mismatch_is_order_independent() -> None:
    events = healthy()
    events[2].amount = Decimal("9950")
    assert {compute_state(list(o)).state for o in permutations(events)} == {TxnState.DISCREPANCY}


def test_missing_ledger_is_pending() -> None:
    state = compute_state([healthy()[0], healthy()[2]])
    assert state.state is TxnState.PENDING
    assert state.ledger_status is None


def test_duplicate_capture_is_discrepancy() -> None:
    events = [
        *healthy(),
        Ev("evt_p2", "PAYMENT_CAPTURED", event_timestamp=T0 + timedelta(seconds=5)),
    ]
    state = compute_state(events)
    assert state.capture_count == 2
    assert state.state is TxnState.DISCREPANCY
    assert state.payment_captured_at == T0  # earliest capture


def test_failed_payment() -> None:
    assert compute_state([Ev("evt_f", "PAYMENT_FAILED", None, None)]).state is TxnState.FAILED


def test_failed_payment_with_ledger_is_discrepancy() -> None:
    events = [Ev("evt_f", "PAYMENT_FAILED", None, None), Ev("evt_l", "LEDGER_POSTED")]
    assert compute_state(events).state is TxnState.DISCREPANCY


def test_refund_totals() -> None:
    events = [
        *healthy(),
        Ev("evt_r1", "REFUND_ISSUED", Decimal("500")),
        Ev("evt_r2", "REFUND_ISSUED", Decimal("250")),
        Ev("evt_g1", "REFUND_PROCESSED", Decimal("500")),
    ]
    state = compute_state(events)
    assert state.internal_refund_amount == Decimal("750")
    assert state.gateway_refund_amount == Decimal("500")
    assert state.event_count == 6
