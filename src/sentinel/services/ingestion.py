"""Event persistence. Callers own the DB transaction boundary."""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from sentinel.db.models import Event, Tenant
from sentinel.domain.events import EventIn


async def tenant_exists(session: AsyncSession, tenant_id: str) -> bool:
    return await session.get(Tenant, tenant_id) is not None


async def store_event(session: AsyncSession, event: EventIn) -> bool:
    """Insert the event; return False if it was already stored (duplicate delivery)."""
    stmt = (
        insert(Event)
        .values(
            tenant_id=event.tenant_id,
            event_id=event.event_id,
            transaction_id=event.transaction_id,
            source=event.source,
            type=event.type,
            amount=event.amount,
            currency=event.currency,
            event_timestamp=event.timestamp,
            metadata_=event.metadata,
        )
        .on_conflict_do_nothing(constraint="uq_events_tenant_event")
        .returning(Event.id)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none() is not None


async def list_events(
    session: AsyncSession, tenant_id: str, transaction_id: str | None = None
) -> Sequence[Event]:
    stmt = select(Event).where(Event.tenant_id == tenant_id)
    if transaction_id is not None:
        stmt = stmt.where(Event.transaction_id == transaction_id)
    stmt = stmt.order_by(Event.event_timestamp, Event.id).limit(500)
    return (await session.scalars(stmt)).all()
