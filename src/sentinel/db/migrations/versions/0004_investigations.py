"""investigations

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    ts = sa.DateTime(timezone=True)
    op.create_table(
        "investigations",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column("tenant_id", sa.Text, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("transaction_id", sa.Text, nullable=False),
        sa.Column("anomaly_type", sa.Text, nullable=False),
        sa.Column("severity", sa.Text, nullable=False),
        sa.Column("priority", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column(
            "reconciliation_result_id",
            sa.BigInteger,
            sa.ForeignKey("reconciliation_results.id"),
            nullable=False,
        ),
        sa.Column("created_at", ts, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", ts, nullable=False, server_default=sa.func.now()),
        sa.Column("closed_at", ts),
    )
    # The concurrency guarantee: at most one *active* investigation per anomaly.
    # "Active" = not closed, so new workflow statuses never require changing this index.
    op.create_index(
        "uq_investigations_active",
        "investigations",
        ["tenant_id", "transaction_id", "anomaly_type"],
        unique=True,
        postgresql_where=sa.text("closed_at IS NULL"),
    )
    op.create_index("ix_investigations_tenant_status", "investigations", ["tenant_id", "status"])


def downgrade() -> None:
    op.drop_table("investigations")
