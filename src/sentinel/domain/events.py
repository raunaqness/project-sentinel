"""Inbound event schema. This is the contract every producer must satisfy."""

from decimal import Decimal
from enum import StrEnum
from typing import Any, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class EventSource(StrEnum):
    PAYMENT_GATEWAY = "PAYMENT_GATEWAY"
    LEDGER = "LEDGER"
    BANK_SETTLEMENT = "BANK_SETTLEMENT"
    REFUND_SERVICE = "REFUND_SERVICE"
    MERCHANT_PLATFORM = "MERCHANT_PLATFORM"


class EventType(StrEnum):
    PAYMENT_CAPTURED = "PAYMENT_CAPTURED"
    PAYMENT_FAILED = "PAYMENT_FAILED"
    LEDGER_POSTED = "LEDGER_POSTED"
    SETTLEMENT_RECEIVED = "SETTLEMENT_RECEIVED"
    REFUND_ISSUED = "REFUND_ISSUED"  # internal refund service
    REFUND_PROCESSED = "REFUND_PROCESSED"  # gateway confirms the refund


class EventIn(BaseModel):
    """A transaction event as received from a source system.

    Unknown fields are rejected so that producer bugs surface as 422s
    instead of silently losing data.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    event_id: str = Field(min_length=1, max_length=128)
    tenant_id: str = Field(min_length=1, max_length=64)
    transaction_id: str = Field(min_length=1, max_length=128)
    source: EventSource
    type: EventType
    amount: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    timestamp: AwareDatetime
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def amount_and_currency_together(self) -> Self:
        if (self.amount is None) != (self.currency is None):
            raise ValueError("amount and currency must be provided together")
        return self
