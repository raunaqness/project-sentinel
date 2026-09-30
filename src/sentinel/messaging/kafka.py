"""Kafka (Redpanda) helpers: topic names, message keys, client factories."""

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

from sentinel.config import get_settings

EVENTS_TOPIC = "sentinel.events"


def event_key(tenant_id: str, transaction_id: str) -> bytes:
    """All events of one transaction share a partition, so they are consumed in order."""
    return f"{tenant_id}:{transaction_id}".encode()


def make_producer() -> AIOKafkaProducer:
    return AIOKafkaProducer(
        bootstrap_servers=get_settings().kafka_bootstrap_servers,
        acks="all",
        enable_idempotence=True,
        linger_ms=5,
    )


def make_consumer(topic: str, group_id: str) -> AIOKafkaConsumer:
    # Offsets are committed manually, only after the DB transaction commits
    # (at-least-once delivery; the DB unique key absorbs redeliveries).
    return AIOKafkaConsumer(
        topic,
        bootstrap_servers=get_settings().kafka_bootstrap_servers,
        group_id=group_id,
        enable_auto_commit=False,
        auto_offset_reset="earliest",
    )
