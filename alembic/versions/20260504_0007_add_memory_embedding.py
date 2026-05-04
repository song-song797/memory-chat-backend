"""Add embedding column to memories table.

Revision ID: 20260504_0007
"""

from alembic import op
import sqlalchemy as sa

revision = "20260504_0007"
down_revision = "20260428_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "memories",
        sa.Column("embedding", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("memories", "embedding")
