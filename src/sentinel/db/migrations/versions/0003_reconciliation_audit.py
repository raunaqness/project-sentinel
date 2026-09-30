"""reconciliation_results and audit_logs

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    ts = sa.DateTime(timezone=True)
    # Arrival times drive the grace periods of time-based rules (see RuleContext).
    op.add_column("transactions", sa.Column("payment_received_at", ts))
    op.add_column("transactions", sa.Column("last_received_at", ts))

    op.create_table(
        "reconciliation_results",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("tenant_id", sa.Text, nullable=False),
        sa.Column("transaction_id", sa.Text, nullable=False),
        sa.Column("anomaly_type", sa.Text, nullable=False),
        sa.Column("severity", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("details", JSONB, nullable=False, server_default="{}"),
        sa.Column("first_detected_at", ts, nullable=False),
        sa.Column("last_evaluated_at", ts, nullable=False),
        sa.Column("resolved_at", ts),
        sa.UniqueConstraint(
            "tenant_id", "transaction_id", "anomaly_type", name="uq_recon_txn_anomaly"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "transaction_id"],
            ["transactions.tenant_id", "transactions.transaction_id"],
        ),
    )
    op.create_index("ix_recon_tenant_status", "reconciliation_results", ["tenant_id", "status"])

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("tenant_id", sa.Text, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("actor", sa.Text, nullable=False),
        sa.Column("action", sa.Text, nullable=False),
        sa.Column("entity_type", sa.Text, nullable=False),
        sa.Column("entity_id", sa.Text, nullable=False),
        sa.Column("details", JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", ts, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_audit_tenant_created", "audit_logs", ["tenant_id", "created_at"])
    op.create_index(
        "ix_audit_tenant_entity", "audit_logs", ["tenant_id", "entity_type", "entity_id"]
    )

    # The scheduler scans unfinished transactions across tenants, oldest-evaluated first.
    op.create_index("ix_transactions_state_updated", "transactions", ["state", "updated_at"])


def downgrade() -> None:
    op.drop_index("ix_transactions_state_updated", "transactions")
    op.drop_table("audit_logs")
    op.drop_table("reconciliation_results")
    op.drop_column("transactions", "last_received_at")
    op.drop_column("transactions", "payment_received_at")
