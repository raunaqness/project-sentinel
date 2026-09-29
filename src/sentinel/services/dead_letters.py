"""Dead-letter records: inspectable, tenant-scoped, resolved when the work is retried."""

from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from sentinel.db.models import DeadLetter

EVENT = "EVENT"
INVESTIGATION = "INVESTIGATION"


def record(
    session: AsyncSession,
    *,
    kind: str,
    error: str,
    payload: dict[str, Any],
    tenant_id: str | None = None,
    reference: str | None = None,
) -> None:
    session.add(
        DeadLetter(
            tenant_id=tenant_id, kind=kind, reference=reference, error=error, payload=payload
        )
    )


async def resolve(session: AsyncSession, kind: str, reference: str, by: str) -> None:
    await session.execute(
        update(DeadLetter)
        .where(
            DeadLetter.kind == kind,
            DeadLetter.reference == reference,
            DeadLetter.resolved_at.is_(None),
        )
        .values(resolved_at=func.now(), resolved_by=by)
    )


async def list_for_tenant(
    session: AsyncSession, tenant_id: str, *, include_resolved: bool = False, limit: int = 200
) -> Sequence[DeadLetter]:
    stmt = select(DeadLetter).where(DeadLetter.tenant_id == tenant_id)
    if not include_resolved:
        stmt = stmt.where(DeadLetter.resolved_at.is_(None))
    stmt = stmt.order_by(DeadLetter.created_at.desc()).limit(limit)
    return (await session.scalars(stmt)).all()
