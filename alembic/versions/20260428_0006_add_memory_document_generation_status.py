"""add memory document generation status

Revision ID: 20260428_0006
Revises: 20260428_0005
Create Date: 2026-04-28 00:06:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260428_0006"
down_revision: Union[str, None] = "20260428_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "memory_documents",
        sa.Column(
            "generated_by",
            sa.String(length=20),
            nullable=False,
            server_default="fallback",
        ),
    )
    op.add_column(
        "memory_documents",
        sa.Column("generation_model", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "memory_documents",
        sa.Column("generation_error", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("memory_documents", "generation_error")
    op.drop_column("memory_documents", "generation_model")
    op.drop_column("memory_documents", "generated_by")
