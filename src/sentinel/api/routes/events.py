"""Event ingestion and inspection endpoints."""

import asyncio
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from aiokafka.errors import KafkaError
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from sentinel.api.auth import Ingestor, Reader
from sentinel.api.deps import ProducerDep, SessionDep
from sentinel.config import get_settings
from sentinel.domain.events import EventIn
from sentinel.messaging.kafka import EVENTS_TOPIC, event_key
from sentinel.observability.logging import context_value
from sentinel.services import ingestion

router = APIRouter(tags=["events"])


class EventAccepted(BaseModel):
    event_id: str
    status: Literal["accepted"] = "accepted"


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    event_id: str
    tenant_id: str
    transaction_id: str
    source: str
    type: str
    amount: Decimal | None
    currency: str | None
    event_timestamp: datetime
    received_at: datetime
    metadata: dict[str, Any] = Field(validation_alias="metadata_")


@router.post("/events", status_code=status.HTTP_202_ACCEPTED)
async def ingest_event(event: EventIn, principal: Ingestor, producer: ProducerDep) -> EventAccepted:
    """Validate and enqueue an event. Persistence happens asynchronously in the consumer.

    A key may only submit events for its own tenant."""
    if event.tenant_id != principal.tenant_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "tenant_id does not match the API key")
    # Bounded wait for the broker's acknowledgement: during a broker outage callers get a
    # fast 503 and retry, instead of requests piling up inside the API. A message already
    # buffered may still be delivered after a 503; the caller's retry is then absorbed as
    # a duplicate by the (tenant_id, event_id) key.
    try:
        await asyncio.wait_for(
            producer.send_and_wait(
                EVENTS_TOPIC,
                key=event_key(event.tenant_id, event.transaction_id),
                value=event.model_dump_json().encode(),
                headers=[("request_id", (context_value("request_id") or "").encode())],
            ),
            timeout=get_settings().kafka_send_timeout_seconds,
        )
    except (KafkaError, TimeoutError) as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "event broker unavailable"
        ) from exc
    return EventAccepted(event_id=event.event_id)


@router.get("/events")
async def get_events(
    session: SessionDep, principal: Reader, transaction_id: str | None = None
) -> list[EventOut]:
    rows = await ingestion.list_events(session, principal.tenant_id, transaction_id)
    return [EventOut.model_validate(row) for row in rows]
