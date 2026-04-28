"""create memory documents

Revision ID: 20260428_0005
Revises: 20260427_0004
Create Date: 2026-04-28 00:05:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260428_0005"
down_revision: Union[str, None] = "20260427_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "memory_documents",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("project_id", sa.String(length=32), nullable=True),
        sa.Column("conversation_id", sa.String(length=32), nullable=True),
        sa.Column("scope", sa.String(length=20), nullable=False, server_default="global"),
        sa.Column("content_md", sa.Text(), nullable=False),
        sa.Column("source_memory_ids", sa.Text(), nullable=False, server_default=""),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_stale", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_memory_documents_user_id"), "memory_documents", ["user_id"])
    op.create_index(op.f("ix_memory_documents_project_id"), "memory_documents", ["project_id"])
    op.create_index(
        op.f("ix_memory_documents_conversation_id"),
        "memory_documents",
        ["conversation_id"],
    )
    op.create_index(op.f("ix_memory_documents_scope"), "memory_documents", ["scope"])


def downgrade() -> None:
    op.drop_index(op.f("ix_memory_documents_scope"), table_name="memory_documents")
    op.drop_index(op.f("ix_memory_documents_conversation_id"), table_name="memory_documents")
    op.drop_index(op.f("ix_memory_documents_project_id"), table_name="memory_documents")
    op.drop_index(op.f("ix_memory_documents_user_id"), table_name="memory_documents")
    op.drop_table("memory_documents")
