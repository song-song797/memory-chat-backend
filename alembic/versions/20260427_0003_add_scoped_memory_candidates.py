"""add scoped memory candidates

Revision ID: 20260427_0004
Revises: 20260427_0003
Create Date: 2026-04-27 00:04:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260427_0004"
down_revision: Union[str, None] = "20260427_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "memory_candidates",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("project_id", sa.String(length=32), nullable=True),
        sa.Column("conversation_id", sa.String(length=32), nullable=True),
        sa.Column("target_memory_id", sa.String(length=32), nullable=True),
        sa.Column("accepted_memory_id", sa.String(length=32), nullable=True),
        sa.Column("source_message_id", sa.String(length=32), nullable=True),
        sa.Column("scope", sa.String(length=20), nullable=False, server_default="global"),
        sa.Column("action", sa.String(length=20), nullable=False, server_default="create"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("confidence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("importance", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("surface", sa.String(length=40), nullable=False, server_default="settings"),
        sa.Column("extraction_model", sa.String(length=100), nullable=True),
        sa.Column("presented_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["accepted_memory_id"], ["memories.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_message_id"], ["messages.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["target_memory_id"], ["memories.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_memory_candidates_user_id"), "memory_candidates", ["user_id"])
    op.create_index(op.f("ix_memory_candidates_project_id"), "memory_candidates", ["project_id"])
    op.create_index(
        op.f("ix_memory_candidates_conversation_id"), "memory_candidates", ["conversation_id"]
    )
    op.create_index(op.f("ix_memory_candidates_scope"), "memory_candidates", ["scope"])
    op.create_index(op.f("ix_memory_candidates_action"), "memory_candidates", ["action"])
    op.create_index(op.f("ix_memory_candidates_status"), "memory_candidates", ["status"])
    op.create_index(op.f("ix_memory_candidates_surface"), "memory_candidates", ["surface"])

    with op.batch_alter_table("memories") as batch_op:
        batch_op.add_column(sa.Column("conversation_id", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("source_candidate_id", sa.String(length=32), nullable=True))
        batch_op.create_foreign_key(
            "fk_memories_conversation_id_conversations",
            "conversations",
            ["conversation_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_foreign_key(
            "fk_memories_source_candidate_id_memory_candidates",
            "memory_candidates",
            ["source_candidate_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(op.f("ix_memories_conversation_id"), ["conversation_id"])


def downgrade() -> None:
    with op.batch_alter_table("memories") as batch_op:
        batch_op.drop_index(op.f("ix_memories_conversation_id"))
        batch_op.drop_constraint(
            "fk_memories_source_candidate_id_memory_candidates", type_="foreignkey"
        )
        batch_op.drop_constraint("fk_memories_conversation_id_conversations", type_="foreignkey")
        batch_op.drop_column("source_candidate_id")
        batch_op.drop_column("conversation_id")

    op.drop_index(op.f("ix_memory_candidates_surface"), table_name="memory_candidates")
    op.drop_index(op.f("ix_memory_candidates_status"), table_name="memory_candidates")
    op.drop_index(op.f("ix_memory_candidates_action"), table_name="memory_candidates")
    op.drop_index(op.f("ix_memory_candidates_scope"), table_name="memory_candidates")
    op.drop_index(op.f("ix_memory_candidates_conversation_id"), table_name="memory_candidates")
    op.drop_index(op.f("ix_memory_candidates_project_id"), table_name="memory_candidates")
    op.drop_index(op.f("ix_memory_candidates_user_id"), table_name="memory_candidates")
    op.drop_table("memory_candidates")
