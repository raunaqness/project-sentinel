"""transactions (materialized state)

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    money = sa.Numeric(18, 2)
    ts = sa.DateTime(timezone=True)
    op.create_table(
        "transactions",
        sa.Column("tenant_id", sa.Text, sa.ForeignKey("tenants.id"), primary_key=True),
        sa.Column("transaction_id", sa.Text, primary_key=True),
        sa.Column("payment_amount", money),
        sa.Column("payment_status", sa.Text),
        sa.Column("payment_captured_at", ts),
        sa.Column("capture_count", sa.Integer, nullable=False),
        sa.Column("ledger_amount", money),
        sa.Column("ledger_status", sa.Text),
        sa.Column("settlement_amount", money),
        sa.Column("settlement_status", sa.Text),
        sa.Column("internal_refund_amount", money),
        sa.Column("gateway_refund_amount", money),
        sa.Column("currency", sa.CHAR(3)),
        sa.Column("event_count", sa.Integer, nullable=False),
        sa.Column("first_event_at", ts, nullable=False),
        sa.Column("last_event_at", ts, nullable=False),
        sa.Column("state", sa.Text, nullable=False),
        sa.Column("updated_at", ts, nullable=False, server_default=sa.func.now()),
    )
    # Used later by reconciliation and investigation queries ("all discrepancies for a tenant").
    op.create_index("ix_transactions_tenant_state", "transactions", ["tenant_id", "state"])


def downgrade() -> None:
    op.drop_table("transactions")
