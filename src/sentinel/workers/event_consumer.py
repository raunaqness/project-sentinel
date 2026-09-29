"""Consumes events from Kafka, persists them and reconciles the transaction.

The event insert, state rebuild, rule findings and audit rows share one DB
transaction, and offsets are committed only after it commits. A crash in between
causes redelivery, which the (tenant_id, event_id) unique key absorbs.
"""

import asyncio
import json
import logging
import os
from typing import Any

from aiokafka import ConsumerRecord
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from sentinel.config import get_settings
from sentinel.db.session import get_engine, get_sessionmaker
from sentinel.domain.events import EventIn
from sentinel.messaging.kafka import EVENTS_TOPIC, make_consumer
from sentinel.observability import metrics
from sentinel.observability.logging import configure_logging, log_context
from sentinel.services import audit, dead_letters
from sentinel.services.ingestion import store_event
from sentinel.services.transactions import reconcile, record_outcome_metrics
from sentinel.workers.base import stop_on_signals, worker_id

log = logging.getLogger("sentinel.event_consumer")

GROUP_ID = "sentinel-event-consumer"
ACTOR = "system:event-consumer"


async def handle(record: ConsumerRecord[bytes, bytes]) -> None:
    try:
        event = EventIn.model_validate_json(record.value)
    except ValidationError as error:
        await _dead_letter(record, f"validation failed: {error.errors(include_url=False)}")
        return

    headers = dict(record.headers or ())
    request_id = headers.get("request_id", b"").decode() or None
    with log_context(
        tenant_id=event.tenant_id,
        transaction_id=event.transaction_id,
        event_id=event.event_id,
        request_id=request_id,
    ):
        try:
            async with get_sessionmaker()() as session, session.begin():
                if not await store_event(session, event):
                    log.info("duplicate event ignored")
                    metrics.EVENTS_PROCESSED.labels(outcome="duplicate").inc()
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
        except IntegrityError as error:
            await _dead_letter(record, f"rejected by database constraints: {error.orig}")
            return
        _crash_after_commit_if_requested(event)
        record_outcome_metrics(outcome)
        metrics.EVENTS_PROCESSED.labels(outcome="stored").inc()
        log.info(
            "event stored",
            extra={
                "state": outcome.state,
                "opened": outcome.opened,
                "resolved": outcome.resolved,
                "investigations_opened": outcome.investigations_opened,
            },
        )


async def _dead_letter(record: ConsumerRecord[bytes, bytes], error: str) -> None:
    """Park an unprocessable message where an admin can inspect it, then move on
    (its offset is committed, so it does not block the partition)."""
    raw = (record.value or b"").decode(errors="replace")
    try:
        parsed: Any = json.loads(raw)
    except json.JSONDecodeError:
        parsed = None
    payload = parsed if isinstance(parsed, dict) else {"raw": raw[:10_000]}
    tenant = payload.get("tenant_id") if isinstance(payload.get("tenant_id"), str) else None
    async with get_sessionmaker()() as session, session.begin():
        dead_letters.record(
            session,
            kind=dead_letters.EVENT,
            tenant_id=tenant,
            reference=payload.get("event_id") if isinstance(payload.get("event_id"), str) else None,
            error=error[:2000],
            payload=payload | {"_offset": record.offset, "_partition": record.partition},
        )
    metrics.EVENTS_FAILED.labels(reason="dead_lettered").inc()
    log.warning("message dead-lettered", extra={"offset": record.offset, "error": error[:200]})


def _crash_after_commit_if_requested(event: EventIn) -> None:
    """Dev/test only (spec §15): die after the DB commit but before the offset commit.
    The broker redelivers the event and the (tenant_id, event_id) key absorbs it."""
    if get_settings().allow_fault_injection and event.metadata.get("fail_after_commit"):
        log.warning("injected crash after DB commit, before offset commit")
        logging.shutdown()
        os._exit(1)


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
            lag = 0
            for tp in consumer.assignment():
                lag += max(0, (consumer.highwater(tp) or 0) - await consumer.position(tp))
            metrics.QUEUE_DEPTH.labels(queue="events").set(lag)  # consumer lag
    finally:
        await consumer.stop()
        await get_engine().dispose()
        log.info("stopped")


def main() -> None:
    configure_logging("event-consumer")
    metrics.serve_worker_metrics()
    with log_context(worker_id=worker_id()):
        asyncio.run(run())


if __name__ == "__main__":
    main()
