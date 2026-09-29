"""Consumes events from Kafka, persists them and reconciles the transaction.

The event insert, state rebuild, rule findings and audit rows share one DB
transaction, and offsets are committed only after it commits. A crash in between
causes redelivery, which the (tenant_id, event_id) unique key absorbs.
"""

import asyncio
import logging

from aiokafka import ConsumerRecord
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from sentinel.db.session import get_engine, get_sessionmaker
from sentinel.domain.events import EventIn
from sentinel.messaging.kafka import EVENTS_TOPIC, make_consumer
from sentinel.observability.logging import configure_logging, log_context
from sentinel.services import audit
from sentinel.services.ingestion import store_event
from sentinel.services.transactions import reconcile
from sentinel.workers.base import stop_on_signals, worker_id

log = logging.getLogger("sentinel.event_consumer")

GROUP_ID = "sentinel-event-consumer"
ACTOR = "system:event-consumer"


async def handle(record: ConsumerRecord[bytes, bytes]) -> None:
    try:
        event = EventIn.model_validate_json(record.value)
    except ValidationError:
        # Dead-lettering comes in the hardening phase; for now, log and skip.
        log.warning("malformed message skipped", extra={"offset": record.offset})
        return

    with log_context(
        tenant_id=event.tenant_id, transaction_id=event.transaction_id, event_id=event.event_id
    ):
        try:
            async with get_sessionmaker()() as session, session.begin():
                if not await store_event(session, event):
                    log.info("duplicate event ignored")
                    return
                audit.record(
                    session,
                    tenant_id=event.tenant_id,
                    actor=ACTOR,
                    action="EVENT_RECEIVED",
                    entity_type="event",
                    entity_id=event.event_id,
                    details={
                        "transaction_id": event.transaction_id,
                        "source": event.source,
                        "type": event.type,
                    },
                )
                outcome = await reconcile(
                    session, event.tenant_id, event.transaction_id, actor=ACTOR
                )
        except IntegrityError:
            log.exception("event rejected by database constraints")
            return
        log.info(
            "event stored",
            extra={
                "state": outcome.state,
                "opened": outcome.opened,
                "resolved": outcome.resolved,
                "investigations_opened": outcome.investigations_opened,
            },
        )


async def run() -> None:
    stop = stop_on_signals()
    consumer = make_consumer(EVENTS_TOPIC, GROUP_ID)
    await consumer.start()
    log.info("consuming", extra={"topic": EVENTS_TOPIC, "group": GROUP_ID})
    try:
        while not stop.is_set():
            batches = await consumer.getmany(timeout_ms=1000, max_records=500)
            for partition, records in batches.items():
                for record in records:
                    await handle(record)
                await consumer.commit({partition: records[-1].offset + 1})
    finally:
        await consumer.stop()
        await get_engine().dispose()
        log.info("stopped")


def main() -> None:
    configure_logging("event-consumer")
    with log_context(worker_id=worker_id()):
        asyncio.run(run())


if __name__ == "__main__":
    main()
