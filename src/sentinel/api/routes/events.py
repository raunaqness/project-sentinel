"""Event ingestion and inspection endpoints."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from aiokafka.errors import KafkaError
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from sentinel.api.auth import Ingestor, Reader
from sentinel.api.deps import ProducerDep, SessionDep
from sentinel.domain.events import EventIn
from sentinel.messaging.kafka import EVENTS_TOPIC, event_key
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
    try:
        await producer.send_and_wait(
            EVENTS_TOPIC,
            key=event_key(event.tenant_id, event.transaction_id),
            value=event.model_dump_json().encode(),
        )
    except KafkaError as exc:
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
