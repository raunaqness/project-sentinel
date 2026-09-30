"""knowledge base: documents and embedded chunks

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import TSVECTOR

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

EMBEDDING_DIM = 1536


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "documents",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("doc_key", sa.Text, nullable=False, unique=True),
        sa.Column("tenant_id", sa.Text, sa.ForeignKey("tenants.id")),  # NULL = global
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("document_type", sa.Text, nullable=False),
        sa.Column("gateway", sa.Text),
        sa.Column("effective_date", sa.Date),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("content_hash", sa.Text, nullable=False),
        sa.Column(
            "ingested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_table(
        "document_chunks",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column(
            "document_id",
            sa.BigInteger,
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Filter fields copied from the document so search never needs a join.
        sa.Column("tenant_id", sa.Text),
        sa.Column("document_type", sa.Text, nullable=False),
        sa.Column("gateway", sa.Text),
        sa.Column("effective_date", sa.Date),
        sa.Column("chunk_index", sa.Integer, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=False),
        sa.Column(
            "tsv",
            TSVECTOR,
            sa.Computed("to_tsvector('english', content)", persisted=True),
        ),
    )
    op.create_index("ix_chunks_tenant", "document_chunks", ["tenant_id"])
    op.create_index("ix_chunks_tsv", "document_chunks", ["tsv"], postgresql_using="gin")
    op.execute(
        "CREATE INDEX ix_chunks_embedding ON document_chunks "
        "USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.drop_table("document_chunks")
    op.drop_table("documents")
