"""tenants and events

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    tenants = op.create_table(
        "tenants",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.bulk_insert(
        tenants,
        [
            {"id": "merchant_123", "name": "Merchant 123"},
            {"id": "merchant_456", "name": "Merchant 456"},
        ],
    )

    op.create_table(
        "events",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("tenant_id", sa.Text, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("event_id", sa.Text, nullable=False),
        sa.Column("transaction_id", sa.Text, nullable=False),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("type", sa.Text, nullable=False),
        sa.Column("amount", sa.Numeric(18, 2)),
        sa.Column("currency", sa.CHAR(3)),
        sa.Column("event_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("metadata", JSONB, nullable=False, server_default="{}"),
        sa.UniqueConstraint("tenant_id", "event_id", name="uq_events_tenant_event"),
    )
    op.create_index("ix_events_tenant_txn", "events", ["tenant_id", "transaction_id"])


def downgrade() -> None:
    op.drop_table("events")
    op.drop_table("tenants")
