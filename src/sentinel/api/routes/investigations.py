"""Investigation endpoints: listing, detail and human review (approve / reject / retry)."""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from sentinel.api.auth import Reader, Reviewer
from sentinel.api.deps import SessionDep
from sentinel.services import investigations, review

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
    current_step: str | None
    attempts: int
    llm_requests: int
    last_error: str | None
    report: dict[str, Any] | None
    reviewed_by: uuid.UUID | None
    reviewed_at: datetime | None
    review_comment: str | None
    next_attempt_at: datetime | None
    errors: list[dict[str, Any]]


class StepOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    step: str
    attempt: int
    completed_at: datetime


class InvestigationDetailOut(InvestigationOut):
    steps: list[StepOut] = []


class ReviewIn(BaseModel):
    comment: str | None = Field(default=None, max_length=2000)


@router.get("/investigations")
async def list_investigations(
    session: SessionDep,
    principal: Reader,
    status: str | None = None,
    transaction_id: str | None = None,
) -> list[InvestigationOut]:
    rows = await investigations.list_for_tenant(
        session, principal.tenant_id, status=status, transaction_id=transaction_id
    )
    return [InvestigationOut.model_validate(r) for r in rows]


async def _detail(session: SessionDep, tenant_id: str, investigation_id: uuid.UUID) -> Any:
    row = await investigations.get(session, tenant_id, investigation_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "investigation not found")
    out = InvestigationDetailOut.model_validate(row)
    out.steps = [StepOut.model_validate(s) for s in await investigations.steps(session, row.id)]
    return out


@router.get("/investigations/{investigation_id}")
async def get_investigation(
    session: SessionDep, principal: Reader, investigation_id: uuid.UUID
) -> InvestigationDetailOut:
    detail: InvestigationDetailOut = await _detail(session, principal.tenant_id, investigation_id)
    return detail


def _raise_for(outcome: review.Outcome, action: str) -> None:
    if outcome is review.Outcome.NOT_FOUND:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "investigation not found")
    if outcome is review.Outcome.CONFLICT:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"investigation is not in a state that allows {action}"
        )


async def _decide(
    session: SessionDep,
    principal: Reviewer,
    investigation_id: uuid.UUID,
    body: ReviewIn,
    *,
    approve: bool,
) -> InvestigationDetailOut:
    # The session already has a transaction open (authentication used it); commit it here.
    outcome = await review.decide(
        session, principal, investigation_id, approve=approve, comment=body.comment
    )
    await session.commit()
    _raise_for(outcome, "approve" if approve else "reject")
    detail: InvestigationDetailOut = await _detail(session, principal.tenant_id, investigation_id)
    return detail


@router.post("/investigations/{investigation_id}/approve")
async def approve_investigation(
    session: SessionDep, principal: Reviewer, investigation_id: uuid.UUID, body: ReviewIn
) -> InvestigationDetailOut:
    return await _decide(session, principal, investigation_id, body, approve=True)


@router.post("/investigations/{investigation_id}/reject")
async def reject_investigation(
    session: SessionDep, principal: Reviewer, investigation_id: uuid.UUID, body: ReviewIn
) -> InvestigationDetailOut:
    return await _decide(session, principal, investigation_id, body, approve=False)


@router.post("/investigations/{investigation_id}/retry", status_code=status.HTTP_202_ACCEPTED)
async def retry_investigation(
    session: SessionDep, principal: Reviewer, investigation_id: uuid.UUID, body: ReviewIn
) -> InvestigationDetailOut:
    outcome = await review.retry(session, principal, investigation_id, body.comment)
    await session.commit()
    _raise_for(outcome, "retry")
    detail: InvestigationDetailOut = await _detail(session, principal.tenant_id, investigation_id)
    return detail
