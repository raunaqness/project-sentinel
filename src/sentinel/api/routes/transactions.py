"""Transaction state endpoints."""

from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict

from sentinel.api.deps import SessionDep
from sentinel.services.transactions import get_transaction

router = APIRouter(tags=["transactions"])


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tenant_id: str
    transaction_id: str
    state: str
    payment_amount: Decimal | None
    payment_status: str | None
    payment_captured_at: datetime | None
    capture_count: int
    ledger_amount: Decimal | None
    ledger_status: str | None
    settlement_amount: Decimal | None
    settlement_status: str | None
    internal_refund_amount: Decimal | None
    gateway_refund_amount: Decimal | None
    currency: str | None
    event_count: int
    first_event_at: datetime
    last_event_at: datetime
    updated_at: datetime


@router.get("/transactions/{transaction_id}")
async def read_transaction(
    session: SessionDep, transaction_id: str, tenant_id: str
) -> TransactionOut:
    row = await get_transaction(session, tenant_id, transaction_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "transaction not found")
    return TransactionOut.model_validate(row)
