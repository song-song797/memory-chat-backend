"""Add message_embeddings table.

Revision ID: 20260504_0008
"""

from alembic import op
import sqlalchemy as sa

revision = "20260504_0008"
down_revision = "20260504_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "message_embeddings",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("user_id", sa.String(32), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("conversation_id", sa.String(32), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("turn_start_id", sa.String(32), sa.ForeignKey("messages.id", ondelete="SET NULL"), nullable=True),
        sa.Column("turn_end_id", sa.String(32), sa.ForeignKey("messages.id", ondelete="SET NULL"), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("message_embeddings")
