"""Investigation endpoints (review actions arrive in Phase 8)."""

import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict

from sentinel.api.deps import SessionDep
from sentinel.services import investigations

router = APIRouter(tags=["investigations"])


class InvestigationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: str
    transaction_id: str
    anomaly_type: str
    severity: str
    priority: str
    status: str
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None


@router.get("/investigations")
async def list_investigations(
    session: SessionDep,
    tenant_id: str,
    status: str | None = None,
    transaction_id: str | None = None,
) -> list[InvestigationOut]:
    rows = await investigations.list_for_tenant(
        session, tenant_id, status=status, transaction_id=transaction_id
    )
    return [InvestigationOut.model_validate(r) for r in rows]


@router.get("/investigations/{investigation_id}")
async def get_investigation(
    session: SessionDep, investigation_id: uuid.UUID, tenant_id: str
) -> InvestigationOut:
    row = await investigations.get(session, tenant_id, investigation_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "investigation not found")
    return InvestigationOut.model_validate(row)
