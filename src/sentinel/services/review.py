"""Human review of investigations: approve, reject, retry.

Each action is a single conditional UPDATE, so concurrent reviewers cannot both
succeed: exactly one matches the expected status, the other gets a conflict.
"""

import uuid
from enum import StrEnum

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from sentinel.api.auth import Principal
from sentinel.db.models import Investigation, InvestigationStep
from sentinel.services import audit
from sentinel.workflow.states import Status


class Outcome(StrEnum):
    OK = "ok"
    NOT_FOUND = "not_found"  # absent, or belongs to another tenant
    CONFLICT = "conflict"  # not in a state that allows this action


async def _outcome_when_unmatched(
    session: AsyncSession, principal: Principal, investigation_id: uuid.UUID
) -> Outcome:
    exists = await session.scalar(
        select(Investigation.id).where(
            Investigation.id == investigation_id, Investigation.tenant_id == principal.tenant_id
        )
    )
    return Outcome.CONFLICT if exists else Outcome.NOT_FOUND


async def decide(
    session: AsyncSession,
    principal: Principal,
    investigation_id: uuid.UUID,
    *,
    approve: bool,
    comment: str | None,
) -> Outcome:
    new_status = Status.APPROVED if approve else Status.REJECTED
    decided = await session.scalar(
        update(Investigation)
        .where(
            Investigation.id == investigation_id,
            Investigation.tenant_id == principal.tenant_id,
            Investigation.status == Status.AWAITING_REVIEW,
        )
        .values(
            status=new_status,
            closed_at=func.now(),
            updated_at=func.now(),
            reviewed_by=principal.user_id,
            reviewed_at=func.now(),
            review_comment=comment,
        )
        .returning(Investigation.id)
    )
    if decided is None:
        return await _outcome_when_unmatched(session, principal, investigation_id)
    audit.record(
        session,
        tenant_id=principal.tenant_id,
        actor=principal.actor,
        action=f"INVESTIGATION_{new_status}",
        entity_type="investigation",
        entity_id=str(investigation_id),
        details={"comment": comment, "role": principal.role},
    )
    return Outcome.OK


async def retry(
    session: AsyncSession, principal: Principal, investigation_id: uuid.UUID, reason: str | None
) -> Outcome:
    """Re-run the workflow from scratch for a FAILED or AWAITING_REVIEW investigation."""
    requeued = await session.scalar(
        update(Investigation)
        .where(
            Investigation.id == investigation_id,
            Investigation.tenant_id == principal.tenant_id,
            Investigation.status.in_([Status.FAILED, Status.AWAITING_REVIEW]),
            Investigation.closed_at.is_(None),
        )
        .values(
            status=Status.OPEN,
            current_step=None,
            attempts=0,
            lease_owner=None,
            lease_expires_at=None,
            last_error=None,
            report=None,
            updated_at=func.now(),
        )
        .returning(Investigation.id)
    )
    if requeued is None:
        return await _outcome_when_unmatched(session, principal, investigation_id)
    await session.execute(
        delete(InvestigationStep).where(InvestigationStep.investigation_id == investigation_id)
    )
    audit.record(
        session,
        tenant_id=principal.tenant_id,
        actor=principal.actor,
        action="INVESTIGATION_RETRIED",
        entity_type="investigation",
        entity_id=str(investigation_id),
        details={"reason": reason, "role": principal.role},
    )
    return Outcome.OK
