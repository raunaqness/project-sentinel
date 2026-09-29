"""Periodically re-reconciles unfinished transactions.

Time-based rules (missing ledger, missing settlement, refund mismatch) can start
firing without any new event arriving, so something has to re-check them.
"""

import asyncio
import contextlib
import logging
from datetime import UTC, datetime

from sqlalchemy import select

from sentinel.config import get_settings
from sentinel.db.models import Transaction
from sentinel.db.session import get_engine, get_sessionmaker
from sentinel.domain.transaction_state import TxnState
from sentinel.observability.logging import configure_logging, log_context
from sentinel.services.transactions import reconcile
from sentinel.workers.base import stop_on_signals, worker_id

log = logging.getLogger("sentinel.scheduler")

ACTOR = "system:scheduler"
BATCH_SIZE = 500


async def sweep() -> int:
    """Re-reconcile up to BATCH_SIZE unfinished transactions, least recently evaluated first."""
    now = datetime.now(UTC)
    async with get_sessionmaker()() as session:
        candidates = (
            await session.execute(
                select(Transaction.tenant_id, Transaction.transaction_id)
                .where(Transaction.state.in_([TxnState.PENDING, TxnState.DISCREPANCY]))
                .order_by(Transaction.updated_at)
                .limit(BATCH_SIZE)
            )
        ).all()

    for tenant_id, transaction_id in candidates:
        with log_context(tenant_id=tenant_id, transaction_id=transaction_id):
            async with get_sessionmaker()() as session, session.begin():
                outcome = await reconcile(session, tenant_id, transaction_id, actor=ACTOR, now=now)
            if outcome.opened or outcome.resolved:
                log.info(
                    "reconciliation changed",
                    extra={
                        "state": outcome.state,
                        "opened": outcome.opened,
                        "resolved": outcome.resolved,
                        "investigations_opened": outcome.investigations_opened,
                    },
                )
    return len(candidates)


async def run() -> None:
    stop = stop_on_signals()
    interval = get_settings().scheduler_interval_seconds
    log.info("started", extra={"interval_seconds": interval})
    try:
        while not stop.is_set():
            try:
                checked = await sweep()
                log.debug("sweep done", extra={"checked": checked})
            except Exception:
                log.exception("sweep failed; retrying next interval")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=interval)
    finally:
        await get_engine().dispose()
        log.info("stopped")


def main() -> None:
    configure_logging("scheduler")
    with log_context(worker_id=worker_id()):
        asyncio.run(run())


if __name__ == "__main__":
    main()
