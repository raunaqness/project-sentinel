"""investigation workflow: leases, checkpoints, report

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    ts = sa.DateTime(timezone=True)
    op.add_column("investigations", sa.Column("current_step", sa.Text))
    op.add_column(
        "investigations", sa.Column("attempts", sa.Integer, nullable=False, server_default="0")
    )
    op.add_column(
        "investigations", sa.Column("llm_requests", sa.Integer, nullable=False, server_default="0")
    )
    op.add_column("investigations", sa.Column("lease_owner", sa.Text))
    op.add_column("investigations", sa.Column("lease_expires_at", ts))
    op.add_column("investigations", sa.Column("last_error", sa.Text))
    op.add_column("investigations", sa.Column("report", JSONB))
    # Workers claim from this small set; the partial index keeps the claim query cheap.
    op.create_index(
        "ix_investigations_claimable",
        "investigations",
        ["created_at"],
        postgresql_where=sa.text("status IN ('OPEN', 'IN_PROGRESS')"),
    )

    op.create_table(
        "investigation_steps",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column(
            "investigation_id",
            UUID(as_uuid=True),
            sa.ForeignKey("investigations.id"),
            nullable=False,
        ),
        sa.Column("step", sa.Text, nullable=False),
        sa.Column("attempt", sa.Integer, nullable=False),
        sa.Column("output", JSONB, nullable=False, server_default="{}"),
        sa.Column("completed_at", ts, nullable=False, server_default=sa.func.now()),
        # A step's checkpoint is written once; a resumed run reuses it instead of redoing work.
        sa.UniqueConstraint("investigation_id", "step", name="uq_steps_investigation_step"),
    )


def downgrade() -> None:
    op.drop_table("investigation_steps")
    op.drop_index("ix_investigations_claimable", "investigations")
    for column in (
        "report",
        "last_error",
        "lease_expires_at",
        "lease_owner",
        "llm_requests",
        "attempts",
        "current_step",
    ):
        op.drop_column("investigations", column)
