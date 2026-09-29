"""dead letters, retry backoff and error history

Revision ID: 0008
Revises: 0007
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    ts = sa.DateTime(timezone=True)
    op.create_table(
        "dead_letters",
        sa.Column("id", sa.BigInteger, primary_key=True),
        # No FK: a malformed message may carry a tenant that does not exist.
        sa.Column("tenant_id", sa.Text),
        sa.Column("kind", sa.Text, nullable=False),  # EVENT | INVESTIGATION
        sa.Column("reference", sa.Text),  # event_id or investigation id
        sa.Column("error", sa.Text, nullable=False),
        sa.Column("payload", JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", ts, nullable=False, server_default=sa.func.now()),
        sa.Column("resolved_at", ts),
        sa.Column("resolved_by", sa.Text),
    )
    op.create_index("ix_dead_letters_tenant_open", "dead_letters", ["tenant_id", "resolved_at"])
    op.add_column("investigations", sa.Column("next_attempt_at", ts))
    op.add_column(
        "investigations",
        sa.Column("errors", JSONB, nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("investigations", "errors")
    op.drop_column("investigations", "next_attempt_at")
    op.drop_table("dead_letters")
