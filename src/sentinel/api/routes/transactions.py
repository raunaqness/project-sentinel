"""Transaction state and reconciliation endpoints."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict

from sentinel.api.auth import Reader
from sentinel.api.deps import SessionDep
from sentinel.services.transactions import get_transaction, list_findings

router = APIRouter(tags=["transactions"])


class FindingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    transaction_id: str
    anomaly_type: str
    severity: str
    status: str
    details: dict[str, Any]
    first_detected_at: datetime
    last_evaluated_at: datetime
    resolved_at: datetime | None


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tenant_id: str
    transaction_id: str
    state: str
    payment_amount: Decimal | None
    payment_status: str | None
    payment_captured_at: datetime | None
    payment_received_at: datetime | None
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
    last_received_at: datetime | None
    updated_at: datetime
    findings: list[FindingOut] = []


@router.get("/transactions/{transaction_id}")
async def read_transaction(
    session: SessionDep, principal: Reader, transaction_id: str
) -> TransactionOut:
    tenant_id = principal.tenant_id
    row = await get_transaction(session, tenant_id, transaction_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "transaction not found")
    findings = await list_findings(session, tenant_id, transaction_id=transaction_id)
    out = TransactionOut.model_validate(row)
    out.findings = [FindingOut.model_validate(f) for f in findings]
    return out


@router.get("/reconciliation-results")
async def read_findings(
    session: SessionDep, principal: Reader, status: Literal["OPEN", "RESOLVED"] | None = None
) -> list[FindingOut]:
    rows = await list_findings(session, principal.tenant_id, status=status)
    return [FindingOut.model_validate(r) for r in rows]
