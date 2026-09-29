"""Consumes events from Kafka, persists them and rebuilds transaction state.

The event insert and the state rebuild share one DB transaction, and offsets
are committed only after it commits. A crash in between causes redelivery,
which the (tenant_id, event_id) unique key absorbs.
"""

import asyncio
import logging
import signal

from aiokafka import ConsumerRecord
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from sentinel.db.session import get_engine, get_sessionmaker
from sentinel.domain.events import EventIn
from sentinel.messaging.kafka import EVENTS_TOPIC, make_consumer
from sentinel.observability.logging import configure_logging
from sentinel.services.ingestion import store_event
from sentinel.services.transactions import rebuild_state

log = logging.getLogger("sentinel.event_consumer")

GROUP_ID = "sentinel-event-consumer"


async def handle(record: ConsumerRecord[bytes, bytes]) -> None:
    try:
        event = EventIn.model_validate_json(record.value)
    except ValidationError:
        # Dead-lettering comes in the hardening phase; for now, log and skip.
        log.warning("skipping malformed message offset=%s", record.offset)
        return
    try:
        async with get_sessionmaker()() as session, session.begin():
            inserted = await store_event(session, event)
            if inserted:
                state = await rebuild_state(session, event.tenant_id, event.transaction_id)
    except IntegrityError:
        log.error("rejected event_id=%s tenant_id=%s", event.event_id, event.tenant_id)
        return
    if not inserted:
        log.info("duplicate event_id=%s tenant_id=%s", event.event_id, event.tenant_id)
        return
    log.info(
        "stored event_id=%s tenant_id=%s transaction_id=%s state=%s",
        event.event_id,
        event.tenant_id,
        event.transaction_id,
        state.state,
    )


async def run() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    consumer = make_consumer(EVENTS_TOPIC, GROUP_ID)
    await consumer.start()
    log.info("consuming topic=%s group=%s", EVENTS_TOPIC, GROUP_ID)
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
    configure_logging()
    asyncio.run(run())


if __name__ == "__main__":
    main()
