"""Audit trail endpoint."""

from datetime import datetime
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from sentinel.api.deps import SessionDep
from sentinel.services import audit

router = APIRouter(tags=["audit"])


class AuditEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    created_at: datetime
    tenant_id: str
    actor: str
    action: str
    entity_type: str
    entity_id: str
    details: dict[str, Any]


@router.get("/audit-logs")
async def read_audit_logs(
    session: SessionDep, tenant_id: str, entity_id: str | None = None
) -> list[AuditEntryOut]:
    rows = await audit.list_entries(session, tenant_id, entity_id)
    return [AuditEntryOut.model_validate(r) for r in rows]
