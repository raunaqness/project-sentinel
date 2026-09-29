"""users (API-key identities) and investigation review fields

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column("tenant_id", sa.Text, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("name", sa.Text, nullable=False, unique=True),
        sa.Column("role", sa.Text, nullable=False),
        # SHA-256 of the API key; the key itself is never stored.
        sa.Column("api_key_hash", sa.Text, nullable=False, unique=True),
        sa.Column("disabled", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "role IN ('VIEWER', 'INVESTIGATOR', 'ADMIN', 'SERVICE')", name="ck_users_role"
        ),
    )
    op.add_column(
        "investigations",
        sa.Column("reviewed_by", UUID(as_uuid=True), sa.ForeignKey("users.id")),
    )
    op.add_column("investigations", sa.Column("reviewed_at", sa.DateTime(timezone=True)))
    op.add_column("investigations", sa.Column("review_comment", sa.Text))


def downgrade() -> None:
    op.drop_column("investigations", "review_comment")
    op.drop_column("investigations", "reviewed_at")
    op.drop_column("investigations", "reviewed_by")
    op.drop_table("users")
