"""create projects and project memory scope

Revision ID: 20260427_0003
Revises: 20260427_0002
Create Date: 2026-04-27 00:03:00.000000
"""

from datetime import datetime, timezone
from typing import Sequence, Union
import uuid

from alembic import op
import sqlalchemy as sa


revision: str = "20260427_0003"
down_revision: Union[str, None] = "20260427_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _new_id() -> str:
    return uuid.uuid4().hex


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("default_model", sa.String(length=100), nullable=True),
        sa.Column("default_reasoning_level", sa.String(length=20), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_projects_user_id"), "projects", ["user_id"], unique=False)

    with op.batch_alter_table("conversations") as batch_op:
        batch_op.add_column(sa.Column("project_id", sa.String(length=32), nullable=True))
        batch_op.create_foreign_key(
            "fk_conversations_project_id_projects",
            "projects",
            ["project_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(op.f("ix_conversations_project_id"), ["project_id"])

    with op.batch_alter_table("memories") as batch_op:
        batch_op.add_column(sa.Column("project_id", sa.String(length=32), nullable=True))
        batch_op.add_column(
            sa.Column("scope", sa.String(length=20), nullable=False, server_default="global")
        )
        batch_op.add_column(
            sa.Column("status", sa.String(length=20), nullable=False, server_default="active")
        )
        batch_op.add_column(
            sa.Column("importance", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.add_column(sa.Column("superseded_by_id", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_foreign_key(
            "fk_memories_project_id_projects",
            "projects",
            ["project_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_memories_superseded_by_id_memories",
            "memories",
            ["superseded_by_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(op.f("ix_memories_project_id"), ["project_id"])

    bind = op.get_bind()
    now = datetime.now(timezone.utc)
    users = bind.execute(sa.text("SELECT id FROM users")).mappings().all()

    default_project_ids: dict[str, str] = {}
    for user in users:
        project_id = _new_id()
        default_project_ids[user["id"]] = project_id
        bind.execute(
            sa.text(
                """
                INSERT INTO projects (
                    id, user_id, name, description, default_model,
                    default_reasoning_level, is_default, archived_at,
                    created_at, updated_at
                )
                VALUES (
                    :id, :user_id, :name, NULL, NULL, NULL, :is_default,
                    NULL, :created_at, :updated_at
                )
                """
            ),
            {
                "id": project_id,
                "user_id": user["id"],
                "name": "个人空间",
                "is_default": True,
                "created_at": now,
                "updated_at": now,
            },
        )

    for user_id, project_id in default_project_ids.items():
        bind.execute(
            sa.text(
                """
                UPDATE conversations
                SET project_id = :project_id
                WHERE user_id = :user_id
                """
            ),
            {"project_id": project_id, "user_id": user_id},
        )
        bind.execute(
            sa.text(
                """
                UPDATE memories
                SET project_id = :project_id, scope = 'project'
                WHERE user_id = :user_id AND kind = 'project'
                """
            ),
            {"project_id": project_id, "user_id": user_id},
        )


def downgrade() -> None:
    with op.batch_alter_table("memories") as batch_op:
        batch_op.drop_index(op.f("ix_memories_project_id"))
        batch_op.drop_constraint("fk_memories_superseded_by_id_memories", type_="foreignkey")
        batch_op.drop_constraint("fk_memories_project_id_projects", type_="foreignkey")
        batch_op.drop_column("archived_at")
        batch_op.drop_column("superseded_by_id")
        batch_op.drop_column("importance")
        batch_op.drop_column("status")
        batch_op.drop_column("scope")
        batch_op.drop_column("project_id")

    with op.batch_alter_table("conversations") as batch_op:
        batch_op.drop_index(op.f("ix_conversations_project_id"))
        batch_op.drop_constraint("fk_conversations_project_id_projects", type_="foreignkey")
        batch_op.drop_column("project_id")

    op.drop_index(op.f("ix_projects_user_id"), table_name="projects")
    op.drop_table("projects")
