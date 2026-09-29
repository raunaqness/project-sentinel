"""Investigation lifecycle. Callers own the DB transaction boundary."""

import uuid
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from sentinel.db.models import Investigation, ReconciliationResult
from sentinel.domain.priority import score
from sentinel.services import audit

OPEN = "OPEN"
AUTO_RESOLVED = "AUTO_RESOLVED"


async def open_for_finding(
    session: AsyncSession, finding: ReconciliationResult, amount: Decimal | None, *, actor: str
) -> uuid.UUID | None:
    """Open an investigation unless an active one already exists for this anomaly.

    The partial unique index decides races: concurrent callers all attempt the
    INSERT, exactly one row is created, the others get a no-op.
    """
    priority = score(finding.anomaly_type, finding.severity, amount)
    investigation_id: uuid.UUID | None = await session.scalar(
        insert(Investigation)
        .values(
            tenant_id=finding.tenant_id,
            transaction_id=finding.transaction_id,
            anomaly_type=finding.anomaly_type,
            severity=finding.severity,
            priority=priority,
            status=OPEN,
            reconciliation_result_id=finding.id,
        )
        .on_conflict_do_nothing(
            index_elements=["tenant_id", "transaction_id", "anomaly_type"],
            index_where=Investigation.closed_at.is_(None),
        )
        .returning(Investigation.id)
    )
    if investigation_id is not None:
        audit.record(
            session,
            tenant_id=finding.tenant_id,
            actor=actor,
            action="INVESTIGATION_CREATED",
            entity_type="investigation",
            entity_id=str(investigation_id),
            details={
                "transaction_id": finding.transaction_id,
                "anomaly_type": finding.anomaly_type,
                "priority": priority,
            },
        )
    return investigation_id


async def auto_resolve(
    session: AsyncSession,
    tenant_id: str,
    transaction_id: str,
    anomaly_type: str,
    *,
    actor: str,
    now: datetime,
) -> list[uuid.UUID]:
    """Close not-yet-started investigations whose finding resolved on its own."""
    closed = (
        await session.scalars(
            update(Investigation)
            .where(
                Investigation.tenant_id == tenant_id,
                Investigation.transaction_id == transaction_id,
                Investigation.anomaly_type == anomaly_type,
                Investigation.status == OPEN,
                Investigation.closed_at.is_(None),
            )
            .values(status=AUTO_RESOLVED, closed_at=now, updated_at=func.now())
            .returning(Investigation.id)
        )
    ).all()
    for investigation_id in closed:
        audit.record(
            session,
            tenant_id=tenant_id,
            actor=actor,
            action="INVESTIGATION_AUTO_RESOLVED",
            entity_type="investigation",
            entity_id=str(investigation_id),
            details={"transaction_id": transaction_id, "anomaly_type": anomaly_type},
        )
    return list(closed)


async def get(
    session: AsyncSession, tenant_id: str, investigation_id: uuid.UUID
) -> Investigation | None:
    row = await session.get(Investigation, investigation_id)
    return row if row is not None and row.tenant_id == tenant_id else None


async def list_for_tenant(
    session: AsyncSession,
    tenant_id: str,
    *,
    status: str | None = None,
    transaction_id: str | None = None,
    limit: int = 200,
) -> Sequence[Investigation]:
    stmt = select(Investigation).where(Investigation.tenant_id == tenant_id)
    if status is not None:
        stmt = stmt.where(Investigation.status == status)
    if transaction_id is not None:
        stmt = stmt.where(Investigation.transaction_id == transaction_id)
    stmt = stmt.order_by(Investigation.created_at.desc()).limit(limit)
    return (await session.scalars(stmt)).all()
