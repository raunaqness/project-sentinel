"""Rebuilds and reads materialized transaction state. Callers own the DB transaction."""

from dataclasses import asdict

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from sentinel.db.models import Event, Transaction
from sentinel.domain.transaction_state import TransactionState, compute_state


async def rebuild_state(
    session: AsyncSession, tenant_id: str, transaction_id: str
) -> TransactionState:
    """Recompute the transaction's state from all of its events and upsert it."""
    events = (
        await session.scalars(
            select(Event).where(
                Event.tenant_id == tenant_id, Event.transaction_id == transaction_id
            )
        )
    ).all()
    state = compute_state(list(events))

    values = asdict(state) | {"tenant_id": tenant_id, "transaction_id": transaction_id}
    stmt = insert(Transaction).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Transaction.tenant_id, Transaction.transaction_id],
        set_={**asdict(state), "updated_at": func.now()},
    )
    await session.execute(stmt)
    return state


async def get_transaction(
    session: AsyncSession, tenant_id: str, transaction_id: str
) -> Transaction | None:
    return await session.get(Transaction, (tenant_id, transaction_id))
