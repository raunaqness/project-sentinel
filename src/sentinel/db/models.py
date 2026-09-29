"""SQLAlchemy models. Migrations in db/migrations are the source of truth for DDL."""

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CHAR,
    BigInteger,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
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
