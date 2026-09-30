from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from sentinel.domain.transaction_state import TransactionState
from sentinel.reconciliation.base import RuleContext
from sentinel.reconciliation.engine import RULES, evaluate

CAPTURED = datetime(2026, 9, 29, 10, 0, tzinfo=UTC)
D = Decimal


def matched() -> TransactionState:
    return TransactionState(
        payment_amount=D("10000"),
        payment_status="SUCCESS",
        payment_captured_at=CAPTURED,
        payment_received_at=CAPTURED,
        capture_count=1,
        ledger_amount=D("10000"),
        ledger_status="POSTED",
        settlement_amount=D("10000"),
        settlement_status="RECEIVED",
        internal_refund_amount=None,
        gateway_refund_amount=None,
        currency="INR",
        event_count=3,
        first_event_at=CAPTURED,
        last_event_at=CAPTURED,
        last_received_at=CAPTURED,
    )


def ctx(after: timedelta) -> RuleContext:
    return RuleContext(
        now=CAPTURED + after, grace=timedelta(minutes=5), missing_settlement_after=timedelta(days=1)
    )


def fired(txn: TransactionState, after: timedelta = timedelta(hours=1)) -> set[str]:
    return {f.anomaly_type for f in evaluate(txn, ctx(after))}


def test_all_rules_registered() -> None:
    assert {r.anomaly_type for r in RULES} == {
        "MISSING_LEDGER",
        "LEDGER_MISMATCH",
        "SETTLEMENT_MISMATCH",
        "DUPLICATE_CAPTURE",
        "MISSING_SETTLEMENT",
        "REFUND_MISMATCH",
    }


def test_healthy_transaction_fires_nothing() -> None:
    assert fired(matched(), after=timedelta(days=30)) == set()


def test_missing_ledger_waits_for_grace() -> None:
    txn = replace(matched(), ledger_amount=None, ledger_status=None)
    assert fired(txn, after=timedelta(minutes=1)) == set()
    assert fired(txn, after=timedelta(minutes=10)) == {"MISSING_LEDGER"}


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"settlement_amount": D("9950")}, {"SETTLEMENT_MISMATCH"}),
        ({"ledger_amount": D("9999")}, {"LEDGER_MISMATCH"}),
        ({"capture_count": 2}, {"DUPLICATE_CAPTURE"}),
        (
            {
                "payment_status": "FAILED",
                "payment_amount": None,
                "settlement_amount": None,
                "settlement_status": None,
            },
            {"LEDGER_MISMATCH"},
        ),
    ],
)
def test_amount_rules(changes: dict[str, object], expected: set[str]) -> None:
    assert fired(replace(matched(), **changes)) == expected  # type: ignore[arg-type]


def test_settlement_mismatch_details() -> None:
    (finding,) = evaluate(replace(matched(), settlement_amount=D("9950")), ctx(timedelta(hours=1)))
    assert finding.details == {
        "payment_amount": "10000",
        "settlement_amount": "9950",
        "difference": "50",
    }


def test_missing_ledger_grace_uses_arrival_time_not_event_time() -> None:
    # Payment happened hours ago but was only just delivered: no false alarm yet.
    late = replace(
        matched(),
        ledger_amount=None,
        ledger_status=None,
        payment_received_at=CAPTURED + timedelta(hours=3),
    )
    assert fired(late, after=timedelta(hours=3, minutes=1)) == set()
    assert fired(late, after=timedelta(hours=3, minutes=10)) == {"MISSING_LEDGER"}


def test_missing_settlement_uses_threshold() -> None:
    txn = replace(matched(), settlement_amount=None, settlement_status=None)
    assert fired(txn, after=timedelta(hours=23)) == set()
    assert fired(txn, after=timedelta(hours=25)) == {"MISSING_SETTLEMENT"}


def test_refund_mismatch() -> None:
    txn = replace(matched(), internal_refund_amount=D("500"))
    assert fired(txn, after=timedelta(minutes=1)) == set()
    assert fired(txn, after=timedelta(minutes=10)) == {"REFUND_MISMATCH"}
    assert fired(replace(txn, gateway_refund_amount=D("500"))) == set()
