"""Dead-letter inspection (ADMIN): malformed events and exhausted investigations."""

from datetime import datetime
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from sentinel.api.auth import Auditor
from sentinel.api.deps import SessionDep
from sentinel.services import dead_letters

router = APIRouter(tags=["dead letters"])


class DeadLetterOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    reference: str | None
    error: str
    payload: dict[str, Any]
    created_at: datetime
    resolved_at: datetime | None
    resolved_by: str | None


@router.get("/dead-letters")
async def list_dead_letters(
    session: SessionDep, principal: Auditor, include_resolved: bool = False
) -> list[DeadLetterOut]:
    rows = await dead_letters.list_for_tenant(
        session, principal.tenant_id, include_resolved=include_resolved
    )
    return [DeadLetterOut.model_validate(r) for r in rows]
