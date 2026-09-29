"""Materialized transaction state, computed from the full set of stored events.

The state is always rebuilt from scratch from every event of the transaction,
so the result depends only on *which* events exist, never on arrival order.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from sentinel.domain.events import EventType


class TxnState(StrEnum):
    PENDING = "PENDING"  # some expected events have not arrived yet
    MATCHED = "MATCHED"  # gateway, ledger and settlement agree
    DISCREPANCY = "DISCREPANCY"  # sources disagree
    FAILED = "FAILED"  # payment failed and nothing downstream happened


class StoredEvent(Protocol):
    """The fields the reducer needs; satisfied by the `Event` ORM model."""

    @property
    def event_id(self) -> str: ...
    @property
    def type(self) -> str: ...
    @property
    def amount(self) -> Decimal | None: ...
    @property
    def currency(self) -> str | None: ...
    @property
    def event_timestamp(self) -> datetime: ...


@dataclass(frozen=True)
class TransactionState:
    payment_amount: Decimal | None
    payment_status: str | None  # SUCCESS | FAILED
    payment_captured_at: datetime | None
    capture_count: int
    ledger_amount: Decimal | None
    ledger_status: str | None  # POSTED
    settlement_amount: Decimal | None
    settlement_status: str | None  # RECEIVED
    internal_refund_amount: Decimal | None
    gateway_refund_amount: Decimal | None
    currency: str | None
    event_count: int
    first_event_at: datetime
    last_event_at: datetime
    state: TxnState


def _latest(events: list[StoredEvent]) -> StoredEvent | None:
    return max(events, key=lambda e: (e.event_timestamp, e.event_id), default=None)


def _earliest(events: list[StoredEvent]) -> StoredEvent | None:
    return min(events, key=lambda e: (e.event_timestamp, e.event_id), default=None)


def _sum(events: list[StoredEvent]) -> Decimal | None:
    amounts = [e.amount for e in events if e.amount is not None]
    return sum(amounts, Decimal(0)) if amounts else None


def compute_state(events: list[StoredEvent]) -> TransactionState:
    if not events:
        raise ValueError("cannot compute state without events")

    by_type: dict[str, list[StoredEvent]] = {t: [] for t in EventType}
    for event in events:
        by_type.setdefault(event.type, []).append(event)

    captures = by_type[EventType.PAYMENT_CAPTURED]
    first_capture = _earliest(captures)
    ledger = _latest(by_type[EventType.LEDGER_POSTED])
    settlement = _latest(by_type[EventType.SETTLEMENT_RECEIVED])

    if captures:
        payment_status: str | None = "SUCCESS"
    elif by_type[EventType.PAYMENT_FAILED]:
        payment_status = "FAILED"
    else:
        payment_status = None

    payment_amount = first_capture.amount if first_capture else None
    ledger_amount = ledger.amount if ledger else None
    settlement_amount = settlement.amount if settlement else None
    currencies = {e.currency for e in events if e.currency is not None}

    present = [a for a in (payment_amount, ledger_amount, settlement_amount) if a is not None]
    if len(captures) > 1 or len(currencies) > 1 or len(set(present)) > 1:
        state = TxnState.DISCREPANCY
    elif payment_status == "FAILED" and ledger is None and settlement is None:
        state = TxnState.FAILED
    elif payment_status == "FAILED":
        state = TxnState.DISCREPANCY  # downstream activity for a failed payment
    elif first_capture and ledger and settlement:
        state = TxnState.MATCHED
    else:
        state = TxnState.PENDING

    ordered = sorted(events, key=lambda e: (e.event_timestamp, e.event_id))
    return TransactionState(
        payment_amount=payment_amount,
        payment_status=payment_status,
        payment_captured_at=first_capture.event_timestamp if first_capture else None,
        capture_count=len(captures),
        ledger_amount=ledger_amount,
        ledger_status="POSTED" if ledger else None,
        settlement_amount=settlement_amount,
        settlement_status="RECEIVED" if settlement else None,
        internal_refund_amount=_sum(by_type[EventType.REFUND_ISSUED]),
        gateway_refund_amount=_sum(by_type[EventType.REFUND_PROCESSED]),
        currency=min(currencies) if currencies else None,
        event_count=len(events),
        first_event_at=ordered[0].event_timestamp,
        last_event_at=ordered[-1].event_timestamp,
        state=state,
    )
