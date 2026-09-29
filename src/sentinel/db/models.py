"""SQLAlchemy models. Migrations in db/migrations are the source of truth for DDL."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CHAR,
    BigInteger,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        # Durable idempotency key: a redelivered event can never be stored twice.
        UniqueConstraint("tenant_id", "event_id", name="uq_events_tenant_event"),
        Index("ix_events_tenant_txn", "tenant_id", "transaction_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(Text, ForeignKey("tenants.id"))
    event_id: Mapped[str] = mapped_column(Text)
    transaction_id: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text)
    type: Mapped[str] = mapped_column(Text)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    currency: Mapped[str | None] = mapped_column(CHAR(3))
    event_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, server_default="{}")


class Transaction(Base):
    """Materialized state per (tenant, transaction); rebuilt from `events`."""

    __tablename__ = "transactions"

    tenant_id: Mapped[str] = mapped_column(Text, ForeignKey("tenants.id"), primary_key=True)
    transaction_id: Mapped[str] = mapped_column(Text, primary_key=True)
    payment_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    payment_status: Mapped[str | None] = mapped_column(Text)
    payment_captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payment_received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    capture_count: Mapped[int]
    ledger_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    ledger_status: Mapped[str | None] = mapped_column(Text)
    settlement_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    settlement_status: Mapped[str | None] = mapped_column(Text)
    internal_refund_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    gateway_refund_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    currency: Mapped[str | None] = mapped_column(CHAR(3))
    event_count: Mapped[int]
    first_event_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_event_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    state: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReconciliationResult(Base):
    """Current outcome of one rule for one transaction (OPEN or RESOLVED)."""

    __tablename__ = "reconciliation_results"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "transaction_id", "anomaly_type", name="uq_recon_txn_anomaly"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "transaction_id"],
            ["transactions.tenant_id", "transactions.transaction_id"],
        ),
        Index("ix_recon_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(Text)
    transaction_id: Mapped[str] = mapped_column(Text)
    anomaly_type: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)  # OPEN | RESOLVED
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    first_detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLog(Base):
    """Append-only record of every business action, written in the same DB
    transaction as the change it describes."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_tenant_created", "tenant_id", "created_at"),
        Index("ix_audit_tenant_entity", "tenant_id", "entity_type", "entity_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(Text, ForeignKey("tenants.id"))
    actor: Mapped[str] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text)
    entity_type: Mapped[str] = mapped_column(Text)
    entity_id: Mapped[str] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Investigation(Base):
    """One investigation per anomaly; at most one *active* (closed_at IS NULL) per
    tenant + transaction + anomaly type, enforced by a partial unique index."""

    __tablename__ = "investigations"
    __table_args__ = (
        Index(
            "uq_investigations_active",
            "tenant_id",
            "transaction_id",
            "anomaly_type",
            unique=True,
            postgresql_where=text("closed_at IS NULL"),
        ),
        Index("ix_investigations_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[str] = mapped_column(Text, ForeignKey("tenants.id"))
    transaction_id: Mapped[str] = mapped_column(Text)
    anomaly_type: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    reconciliation_result_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("reconciliation_results.id")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_step: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(server_default="0")
    llm_requests: Mapped[int] = mapped_column(server_default="0")
    lease_owner: Mapped[str | None] = mapped_column(Text)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    report: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class InvestigationStep(Base):
    """Checkpoint of one completed workflow step."""

    __tablename__ = "investigation_steps"
    __table_args__ = (
        UniqueConstraint("investigation_id", "step", name="uq_steps_investigation_step"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    investigation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("investigations.id")
    )
    step: Mapped[str] = mapped_column(Text)
    attempt: Mapped[int]
    output: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


EMBEDDING_DIM = 1536


class Document(Base):
    """A knowledge-base document. tenant_id NULL means global (visible to every tenant)."""

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    doc_key: Mapped[str] = mapped_column(Text, unique=True)
    tenant_id: Mapped[str | None] = mapped_column(Text, ForeignKey("tenants.id"))
    title: Mapped[str] = mapped_column(Text)
    document_type: Mapped[str] = mapped_column(Text)
    gateway: Mapped[str | None] = mapped_column(Text)
    effective_date: Mapped[date | None] = mapped_column(Date)
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(Text)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("documents.id", ondelete="CASCADE")
    )
    tenant_id: Mapped[str | None] = mapped_column(Text)
    document_type: Mapped[str] = mapped_column(Text)
    gateway: Mapped[str | None] = mapped_column(Text)
    effective_date: Mapped[date | None] = mapped_column(Date)
    chunk_index: Mapped[int]
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM))
    tsv: Mapped[str | None] = mapped_column(
        TSVECTOR, Computed("to_tsvector('english', content)", persisted=True)
    )
