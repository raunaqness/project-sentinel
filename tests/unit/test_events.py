from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from sentinel.domain.events import EventIn, EventSource, EventType


def payload(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "event_id": "evt_10001",
        "tenant_id": "merchant_123",
        "transaction_id": "txn_50001",
        "source": "PAYMENT_GATEWAY",
        "type": "PAYMENT_CAPTURED",
        "amount": 10000,
        "currency": "INR",
        "timestamp": "2026-09-29T10:30:00Z",
        "metadata": {},
    }
    return base | overrides


def test_spec_example_parses() -> None:
    event = EventIn.model_validate(payload())
    assert event.source is EventSource.PAYMENT_GATEWAY
    assert event.type is EventType.PAYMENT_CAPTURED
    assert event.amount == Decimal("10000")


def test_status_only_event_without_amount() -> None:
    event = EventIn.model_validate(payload(type="PAYMENT_FAILED", amount=None, currency=None))
    assert event.amount is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"amount": 100, "currency": None},  # amount without currency
        {"amount": None, "currency": "INR"},  # currency without amount
        {"amount": -1},
        {"amount": "10.001"},  # more than 2 decimal places
        {"currency": "inr"},
        {"type": "PAYMENT_TELEPORTED"},
        {"source": "UNKNOWN"},
        {"timestamp": "2026-09-29T10:30:00"},  # no timezone
        {"event_id": ""},
        {"surprise": "field"},  # unknown fields rejected
    ],
)
def test_malformed_events_rejected(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        EventIn.model_validate(payload(**overrides))
