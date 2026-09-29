"""Materialized transaction state, computed from the full set of stored events.

The facts are always rebuilt from scratch from every event of the transaction,
so they depend only on *which* events exist, never on arrival order. Whether the
transaction is in DISCREPANCY is decided by the reconciliation rules, not here.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from sentinel.domain.events import EventType


class TxnState(StrEnum):
    PENDING = "PENDING"  # expected events have not all arrived yet
    MATCHED = "MATCHED"  # complete, and no reconciliation rule fires
    DISCREPANCY = "DISCREPANCY"  # at least one reconciliation rule fires
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
    @property
    def received_at(self) -> datetime: ...


@dataclass(frozen=True)
class TransactionState:
    payment_amount: Decimal | None
    payment_status: str | None  # SUCCESS | FAILED
    payment_captured_at: datetime | None  # business time, from the source system
    payment_received_at: datetime | None  # when Sentinel stored the first capture
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
    last_received_at: datetime


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

    ordered = sorted(events, key=lambda e: (e.event_timestamp, e.event_id))
    return TransactionState(
        payment_amount=payment_amount,
        payment_status=payment_status,
        payment_captured_at=first_capture.event_timestamp if first_capture else None,
        payment_received_at=first_capture.received_at if first_capture else None,
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
        last_received_at=max(e.received_at for e in events),
    )


def overall_state(facts: TransactionState, has_open_findings: bool) -> TxnState:
    if has_open_findings:
        return TxnState.DISCREPANCY
    downstream = facts.ledger_status is not None or facts.settlement_status is not None
    if facts.payment_status == "FAILED" and not downstream:
        return TxnState.FAILED
    complete = facts.payment_status == "SUCCESS" and facts.ledger_status and facts.settlement_status
    refunds_balanced = (facts.internal_refund_amount or Decimal(0)) == (
        facts.gateway_refund_amount or Decimal(0)
    )
    # A refund awaiting gateway confirmation keeps the transaction PENDING, so the
    # scheduler keeps re-checking it until the refund-mismatch grace period passes.
    if complete and refunds_balanced:
        return TxnState.MATCHED
    return TxnState.PENDING
