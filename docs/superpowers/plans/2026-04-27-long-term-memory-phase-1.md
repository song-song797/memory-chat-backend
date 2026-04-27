# Long-Term Memory Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build PostgreSQL-backed, user-scoped long-term memory without embedding or pgvector in phase 1.

**Architecture:** Keep SQLAlchemy as the ORM, add Alembic for schema versioning, and introduce a plain `memories` table tied to users. Chat will keep its current short-term context and prepend a small, enabled set of user memories before each LLM call.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, PostgreSQL via `psycopg`, React, TypeScript, Vite.

---

## File Structure

Backend files:

- Modify `backend/requirements.txt`: add PostgreSQL and Alembic dependencies.
- Modify `backend/.env.example`: show PostgreSQL `DATABASE_URL`.
- Create `backend/alembic.ini`: Alembic CLI config.
- Create `backend/alembic/env.py`: load app metadata and database URL.
- Create `backend/alembic/versions/20260427_0001_create_initial_schema.py`: baseline schema for existing tables.
- Create `backend/alembic/versions/20260427_0002_create_memories.py`: `memories` table migration.
- Modify `backend/app/database.py`: stop mutating schema at app startup.
- Modify `backend/app/models.py`: add `Memory`.
- Modify `backend/app/schemas.py`: add memory request and response schemas.
- Modify `backend/app/services/memory_service.py`: add long-term memory helpers beside current short-term context helpers.
- Create `backend/app/routers/memories.py`: authenticated memory CRUD.
- Modify `backend/app/main.py`: include memory router.
- Modify `backend/app/routers/chat.py`: save explicit memories and inject enabled memories.
- Create `backend/tests/test_long_term_memory_service.py`: service-level memory tests.
- Create `backend/tests/test_memory_routes.py`: authenticated API tests.

Frontend files:

- Modify `fronted/src/types.ts`: add `Memory`.
- Modify `fronted/src/services/api.ts`: add memory CRUD client functions.
- Create `fronted/src/components/MemorySettingsSection.tsx`: focused memory management UI.
- Modify `fronted/src/components/SettingsDrawer.tsx`: render memory section.
- Modify `fronted/src/App.tsx`: own memory state and handlers.
- Modify `fronted/src/App.css`: add compact settings styles for memory controls.

---

### Task 1: PostgreSQL And Alembic Baseline

**Files:**
- Modify: `backend/requirements.txt`
- Modify: `backend/.env.example`
- Create: `backend/alembic.ini`
- Create: `backend/alembic/env.py`
- Create: `backend/alembic/versions/20260427_0001_create_initial_schema.py`
- Modify: `backend/app/database.py`

- [ ] **Step 1: Add database dependencies**

Modify `backend/requirements.txt` so it includes these new lines:

```text
alembic==1.13.3
psycopg[binary]==3.2.3
```

- [ ] **Step 2: Update example database configuration**

Change the database section in `backend/.env.example` to:

```env
# Database
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/llm_memory_chat
```

- [ ] **Step 3: Create Alembic config**

Create `backend/alembic.ini`:

```ini
[alembic]
script_location = alembic
prepend_sys_path = .
version_path_separator = os

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console
qualname =

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

- [ ] **Step 4: Create Alembic environment**

Create `backend/alembic/env.py`:

```python
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import settings
from app.models import Base

config = context.config
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings.DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

- [ ] **Step 5: Create baseline migration**

Create `backend/alembic/versions/20260427_0001_create_initial_schema.py`:

```python
from alembic import op
import sqlalchemy as sa

revision = "20260427_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)

    op.create_table(
        "conversations",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("pinned", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "messages",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("conversation_id", sa.String(length=32), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "attachments",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("message_id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("stored_name", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("stored_name"),
    )

    op.create_table(
        "user_sessions",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_user_sessions_token_hash"), "user_sessions", ["token_hash"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_user_sessions_token_hash"), table_name="user_sessions")
    op.drop_table("user_sessions")
    op.drop_table("attachments")
    op.drop_table("messages")
    op.drop_table("conversations")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")
```

- [ ] **Step 6: Stop app startup from changing schema**

Change `backend/app/database.py` so `init_db()` no longer calls `Base.metadata.create_all()` or manual `ALTER TABLE` statements:

```python
def init_db():
    """Schema is managed by Alembic migrations."""
    return None
```

Also remove unused imports from `backend/app/database.py`:

```python
from sqlalchemy import create_engine
```

Keep this import:

```python
from sqlalchemy.orm import DeclarativeBase, sessionmaker
```

- [ ] **Step 7: Install dependencies**

Run:

```bash
cd backend
python -m pip install -r requirements.txt
```

Expected: command exits successfully and installs `alembic` and `psycopg`.

- [ ] **Step 8: Verify Alembic can inspect the migration chain**

Run:

```bash
cd backend
alembic history
```

Expected output includes:

```text
20260427_0001 -> <base>, create initial schema
```

- [ ] **Step 9: Commit**

```bash
git -C backend add requirements.txt .env.example alembic.ini alembic app/database.py
git -C backend commit -m "chore: add postgres migration baseline"
```

---

### Task 2: Memory Model, Schemas, And Service

**Files:**
- Modify: `backend/app/models.py`
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/services/memory_service.py`
- Create: `backend/alembic/versions/20260427_0002_create_memories.py`
- Create: `backend/tests/test_long_term_memory_service.py`

- [ ] **Step 1: Write service tests first**

Create `backend/tests/test_long_term_memory_service.py`:

```python
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Conversation, Memory, Message, User
from app.services import memory_service


class LongTermMemoryServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def test_explicit_memory_intent_creates_user_memory(self) -> None:
        db = self.SessionLocal()
        try:
            user = User(email="memory@example.com", password_hash="hash")
            conversation = Conversation(user=user, title="memory")
            db.add_all([user, conversation])
            db.commit()
            db.refresh(user)
            db.refresh(conversation)

            message = Message(
                conversation_id=conversation.id,
                role="user",
                content="请记住我使用 PyCharm 开发 Python 项目",
            )
            db.add(message)
            db.commit()
            db.refresh(message)

            memory = memory_service.maybe_store_explicit_memory(db, user.id, message)

            self.assertIsNotNone(memory)
            self.assertEqual(memory.user_id, user.id)
            self.assertEqual(memory.source_message_id, message.id)
            self.assertEqual(memory.kind, "tool")
            self.assertIn("PyCharm", memory.content)
        finally:
            db.close()

    def test_non_explicit_message_does_not_create_memory(self) -> None:
        db = self.SessionLocal()
        try:
            user = User(email="quiet@example.com", password_hash="hash")
            conversation = Conversation(user=user, title="memory")
            db.add_all([user, conversation])
            db.commit()
            db.refresh(user)
            db.refresh(conversation)

            message = Message(
                conversation_id=conversation.id,
                role="user",
                content="这个数据库怎么打开",
            )
            db.add(message)
            db.commit()
            db.refresh(message)

            memory = memory_service.maybe_store_explicit_memory(db, user.id, message)

            self.assertIsNone(memory)
            self.assertEqual(db.query(Memory).count(), 0)
        finally:
            db.close()

    def test_disabled_memories_are_not_injected(self) -> None:
        db = self.SessionLocal()
        try:
            user = User(email="context@example.com", password_hash="hash")
            db.add(user)
            db.commit()
            db.refresh(user)

            enabled = Memory(user_id=user.id, content="用户喜欢简洁中文回答", kind="preference")
            disabled = Memory(
                user_id=user.id,
                content="用户喜欢英文回答",
                kind="preference",
                enabled=False,
            )
            db.add_all([enabled, disabled])
            db.commit()

            context = memory_service.get_long_term_memory_context(db, user.id)

            self.assertIsNotNone(context)
            self.assertEqual(context["role"], "system")
            self.assertIn("用户喜欢简洁中文回答", context["content"])
            self.assertNotIn("用户喜欢英文回答", context["content"])
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
cd backend
PYTHONPATH=. python -m unittest tests.test_long_term_memory_service -v
```

Expected: failure because `Memory` and new service functions do not exist yet.

- [ ] **Step 3: Add Memory model**

In `backend/app/models.py`, add `Memory` to the imports and relationships.

Add this relationship to `User`:

```python
    memories: Mapped[list["Memory"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        order_by="Memory.updated_at.desc()",
    )
```

Add this class after `Message`:

```python
class Memory(Base):
    __tablename__ = "memories"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    content: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(40), default="fact")
    source_message_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship(back_populates="memories")
    source_message: Mapped["Message | None"] = relationship()
```

- [ ] **Step 4: Add memory schemas**

In `backend/app/schemas.py`, add:

```python
class MemoryCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=1000)
    kind: str = Field(default="fact", max_length=40)


class MemoryUpdate(BaseModel):
    content: str | None = Field(default=None, min_length=1, max_length=1000)
    kind: str | None = Field(default=None, max_length=40)
    enabled: bool | None = None


class MemoryOut(BaseModel):
    id: str
    content: str
    kind: str
    enabled: bool
    created_at: datetime
    updated_at: datetime
    last_used_at: datetime | None = None

    model_config = {"from_attributes": True}

    @field_serializer("created_at", "updated_at", "last_used_at")
    def serialize_memory_datetimes(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        return _serialize_datetime(value)
```

- [ ] **Step 5: Add memory migration**

Create `backend/alembic/versions/20260427_0002_create_memories.py`:

```python
from alembic import op
import sqlalchemy as sa

revision = "20260427_0002"
down_revision = "20260427_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "memories",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("source_message_id", sa.String(length=32), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["source_message_id"], ["messages.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_memories_user_id"), "memories", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_memories_user_id"), table_name="memories")
    op.drop_table("memories")
```

- [ ] **Step 6: Add long-term memory service helpers**

Append these helpers to `backend/app/services/memory_service.py`:

```python
from datetime import datetime, timezone

MEMORY_INTENT_MARKERS = ("记住", "请记住", "以后你要记得", "以后回答我时")
MAX_MEMORY_CONTEXT_ITEMS = 12
MAX_MEMORY_CONTENT_LENGTH = 500


def has_explicit_memory_intent(content: str) -> bool:
    normalized = content.strip()
    return any(marker in normalized for marker in MEMORY_INTENT_MARKERS)


def _classify_memory(content: str) -> str:
    if any(token in content for token in ("PyCharm", "IDE", "Python", "FastAPI", "React", "PostgreSQL")):
        return "tool"
    if any(token in content for token in ("项目", "后端", "前端", "数据库", "接口")):
        return "project"
    if any(token in content for token in ("喜欢", "习惯", "偏好", "以后回答")):
        return "preference"
    return "fact"


def _normalize_memory_content(content: str) -> str:
    normalized = " ".join(content.strip().split())
    for marker in MEMORY_INTENT_MARKERS:
        normalized = normalized.replace(marker, "")
    normalized = normalized.strip(" ，。:：")
    return normalized[:MAX_MEMORY_CONTENT_LENGTH]


def maybe_store_explicit_memory(
    db: Session,
    user_id: str,
    message: Message,
) -> Memory | None:
    if message.role != "user" or not has_explicit_memory_intent(message.content):
        return None

    content = _normalize_memory_content(message.content)
    if not content:
        return None

    memory = Memory(
        user_id=user_id,
        content=content,
        kind=_classify_memory(content),
        source_message_id=message.id,
    )
    db.add(memory)
    db.commit()
    db.refresh(memory)
    return memory


def get_enabled_memories_for_context(
    db: Session,
    user_id: str,
    limit: int = MAX_MEMORY_CONTEXT_ITEMS,
) -> list[Memory]:
    stmt = (
        select(Memory)
        .where(Memory.user_id == user_id, Memory.enabled.is_(True))
        .order_by(Memory.last_used_at.desc().nullslast(), Memory.updated_at.desc())
        .limit(limit)
    )
    memories = list(db.execute(stmt).scalars().all())
    if memories:
        now = datetime.now(timezone.utc)
        for memory in memories:
            memory.last_used_at = now
        db.commit()
    return memories


def get_long_term_memory_context(db: Session, user_id: str) -> dict[str, str] | None:
    memories = get_enabled_memories_for_context(db, user_id)
    if not memories:
        return None

    lines = "\n".join(f"- {memory.content}" for memory in memories)
    return {
        "role": "system",
        "content": f"以下是关于当前用户的长期记忆。仅在与当前问题相关时使用：\n{lines}",
    }
```

Also update the existing model import at the top of `memory_service.py`:

```python
from ..models import Attachment, Conversation, Memory, Message
```

- [ ] **Step 7: Run service tests**

Run:

```bash
cd backend
PYTHONPATH=. python -m unittest tests.test_long_term_memory_service -v
```

Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git -C backend add app/models.py app/schemas.py app/services/memory_service.py alembic/versions/20260427_0002_create_memories.py tests/test_long_term_memory_service.py
git -C backend commit -m "feat: add long-term memory model"
```

---

### Task 3: Authenticated Memory API

**Files:**
- Create: `backend/app/routers/memories.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_memory_routes.py`

- [ ] **Step 1: Write route tests first**

Create `backend/tests/test_memory_routes.py`:

```python
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app


class MemoryRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "memory-routes.db"
        self.engine = create_engine(
            f"sqlite:///{database_path.as_posix()}",
            connect_args={"check_same_thread": False},
        )
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)

        def override_get_db():
            db = self.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.client.close()
        self.engine.dispose()
        self.temp_dir.cleanup()

    def _register(self, email: str) -> dict[str, str]:
        response = self.client.post(
            "/api/auth/register",
            json={"email": email, "password": "password123"},
        )
        self.assertEqual(response.status_code, 201)
        return {"Authorization": f"Bearer {response.json()['token']}"}

    def test_memory_crud(self) -> None:
        headers = self._register("owner@example.com")

        create_response = self.client.post(
            "/api/memories",
            json={"content": "用户使用 PyCharm 开发 Python 项目", "kind": "tool"},
            headers=headers,
        )
        self.assertEqual(create_response.status_code, 201)
        created = create_response.json()
        self.assertEqual(created["content"], "用户使用 PyCharm 开发 Python 项目")
        self.assertTrue(created["enabled"])

        list_response = self.client.get("/api/memories", headers=headers)
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(len(list_response.json()), 1)

        update_response = self.client.put(
            f"/api/memories/{created['id']}",
            json={"enabled": False},
            headers=headers,
        )
        self.assertEqual(update_response.status_code, 200)
        self.assertFalse(update_response.json()["enabled"])

        delete_response = self.client.delete(f"/api/memories/{created['id']}", headers=headers)
        self.assertEqual(delete_response.status_code, 204)

        final_list = self.client.get("/api/memories", headers=headers)
        self.assertEqual(final_list.json(), [])

    def test_memories_are_isolated_by_user(self) -> None:
        alice_headers = self._register("alice-memory@example.com")
        bob_headers = self._register("bob-memory@example.com")

        create_response = self.client.post(
            "/api/memories",
            json={"content": "Alice memory", "kind": "fact"},
            headers=alice_headers,
        )
        self.assertEqual(create_response.status_code, 201)
        memory_id = create_response.json()["id"]

        bob_update = self.client.put(
            f"/api/memories/{memory_id}",
            json={"enabled": False},
            headers=bob_headers,
        )
        self.assertEqual(bob_update.status_code, 404)

        bob_delete = self.client.delete(f"/api/memories/{memory_id}", headers=bob_headers)
        self.assertEqual(bob_delete.status_code, 404)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
cd backend
PYTHONPATH=. python -m unittest tests.test_memory_routes -v
```

Expected: failure because `/api/memories` routes do not exist yet.

- [ ] **Step 3: Add memory router**

Create `backend/app/routers/memories.py`:

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Memory, User
from ..schemas import MemoryCreate, MemoryOut, MemoryUpdate
from ..services.auth_service import get_current_user

router = APIRouter(prefix="/api/memories", tags=["memories"])


def _get_user_memory(db: Session, user_id: str, memory_id: str) -> Memory:
    memory = db.get(Memory, memory_id)
    if not memory or memory.user_id != user_id:
        raise HTTPException(status_code=404, detail="Memory not found")
    return memory


@router.get("", response_model=list[MemoryOut])
def list_memories(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = (
        select(Memory)
        .where(Memory.user_id == current_user.id)
        .order_by(Memory.updated_at.desc())
    )
    return list(db.execute(stmt).scalars().all())


@router.post("", response_model=MemoryOut, status_code=201)
def create_memory(
    body: MemoryCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    memory = Memory(user_id=current_user.id, content=body.content.strip(), kind=body.kind.strip())
    db.add(memory)
    db.commit()
    db.refresh(memory)
    return memory


@router.put("/{memory_id}", response_model=MemoryOut)
def update_memory(
    memory_id: str,
    body: MemoryUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    memory = _get_user_memory(db, current_user.id, memory_id)
    if body.content is None and body.kind is None and body.enabled is None:
        raise HTTPException(status_code=400, detail="No memory changes provided")

    if body.content is not None:
        memory.content = body.content.strip()
    if body.kind is not None:
        memory.kind = body.kind.strip()
    if body.enabled is not None:
        memory.enabled = body.enabled

    db.commit()
    db.refresh(memory)
    return memory


@router.delete("/{memory_id}", status_code=204)
def delete_memory(
    memory_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    memory = _get_user_memory(db, current_user.id, memory_id)
    db.delete(memory)
    db.commit()
```

- [ ] **Step 4: Register router**

Modify `backend/app/main.py` imports:

```python
from .routers import attachments, auth, chat, conversations, memories
```

Add this include after existing router includes:

```python
app.include_router(memories.router)
```

- [ ] **Step 5: Run route tests**

Run:

```bash
cd backend
PYTHONPATH=. python -m unittest tests.test_memory_routes -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git -C backend add app/routers/memories.py app/main.py tests/test_memory_routes.py
git -C backend commit -m "feat: add memory management api"
```

---

### Task 4: Chat Memory Save And Injection

**Files:**
- Modify: `backend/app/routers/chat.py`
- Modify: `backend/tests/test_long_term_memory_service.py`
- Modify: `backend/tests/test_memory_service.py`

- [ ] **Step 1: Add context composition test**

Append this test method to `LongTermMemoryServiceTests` in `backend/tests/test_long_term_memory_service.py`:

```python
    def test_compose_context_prepends_long_term_memory(self) -> None:
        db = self.SessionLocal()
        try:
            user = User(email="compose@example.com", password_hash="hash")
            conversation = Conversation(user=user, title="compose")
            db.add_all([user, conversation])
            db.commit()
            db.refresh(user)
            db.refresh(conversation)

            db.add(Memory(user_id=user.id, content="用户使用 PyCharm", kind="tool"))
            db.add(Message(conversation_id=conversation.id, role="user", content="怎么打开数据库"))
            db.commit()

            context = memory_service.get_chat_context_messages(
                db,
                user.id,
                conversation.id,
                current_model="MiniMax-M2.5",
            )

            self.assertEqual(context[0]["role"], "system")
            self.assertIn("用户使用 PyCharm", context[0]["content"])
            self.assertEqual(context[1], {"role": "user", "content": "怎么打开数据库"})
        finally:
            db.close()
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
cd backend
PYTHONPATH=. python -m unittest tests.test_long_term_memory_service -v
```

Expected: failure because `get_chat_context_messages` does not exist.

- [ ] **Step 3: Add composed context helper**

Add this function to `backend/app/services/memory_service.py`:

```python
def get_chat_context_messages(
    db: Session,
    user_id: str,
    conversation_id: str,
    current_model: str | None = None,
) -> list[dict[str, object]]:
    context: list[dict[str, object]] = []
    long_term_context = get_long_term_memory_context(db, user_id)
    if long_term_context:
        context.append(long_term_context)
    context.extend(get_context_messages(db, conversation_id, current_model=current_model))
    return context
```

- [ ] **Step 4: Use composed context and save explicit memories in chat**

In `backend/app/routers/chat.py`, after this line:

```python
user_message = memory_service.store_message(db, conv.id, "user", req.message.strip())
```

add:

```python
try:
    memory_service.maybe_store_explicit_memory(db, current_user.id, user_message)
except Exception as error:
    print(f"Failed to store long-term memory: {error}")
```

Replace:

```python
context = memory_service.get_context_messages(db, conv.id, current_model=chosen_model)
```

with:

```python
try:
    context = memory_service.get_chat_context_messages(
        db,
        current_user.id,
        conv.id,
        current_model=chosen_model,
    )
except Exception as error:
    print(f"Failed to load long-term memory context: {error}")
    context = memory_service.get_context_messages(db, conv.id, current_model=chosen_model)
```

- [ ] **Step 5: Run all backend unit tests**

Run:

```bash
cd backend
PYTHONPATH=. python -m unittest discover tests -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git -C backend add app/routers/chat.py app/services/memory_service.py tests/test_long_term_memory_service.py tests/test_memory_service.py
git -C backend commit -m "feat: use long-term memory in chat"
```

---

### Task 5: Frontend Memory Management

**Files:**
- Modify: `fronted/src/types.ts`
- Modify: `fronted/src/services/api.ts`
- Create: `fronted/src/components/MemorySettingsSection.tsx`
- Modify: `fronted/src/components/SettingsDrawer.tsx`
- Modify: `fronted/src/App.tsx`
- Modify: `fronted/src/App.css`

- [ ] **Step 1: Add frontend memory type**

Add to `fronted/src/types.ts`:

```ts
export interface Memory {
  id: string;
  content: string;
  kind: string;
  enabled: boolean;
  created_at: string;
  updated_at: string;
  last_used_at?: string | null;
}
```

- [ ] **Step 2: Add API client functions**

Add `Memory` to the type import in `fronted/src/services/api.ts`:

```ts
  Memory,
```

Add these functions before `sendMessage`:

```ts
export async function fetchMemories(): Promise<Memory[]> {
  const res = await apiFetch(`${API_BASE}/memories`);
  if (!res.ok) {
    const errorMessage = await getErrorMessage(res, 'Failed to fetch memories');
    throw new Error(errorMessage);
  }
  return res.json();
}

export async function createMemory(content: string, kind = 'fact'): Promise<Memory> {
  const res = await apiFetch(`${API_BASE}/memories`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content, kind }),
  });
  if (!res.ok) {
    const errorMessage = await getErrorMessage(res, 'Failed to create memory');
    throw new Error(errorMessage);
  }
  return res.json();
}

export async function updateMemory(
  memoryId: string,
  updates: { content?: string; kind?: string; enabled?: boolean }
): Promise<Memory> {
  const res = await apiFetch(`${API_BASE}/memories/${memoryId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(updates),
  });
  if (!res.ok) {
    const errorMessage = await getErrorMessage(res, 'Failed to update memory');
    throw new Error(errorMessage);
  }
  return res.json();
}

export async function deleteMemory(memoryId: string): Promise<void> {
  const res = await apiFetch(`${API_BASE}/memories/${memoryId}`, {
    method: 'DELETE',
  });
  if (!res.ok) {
    const errorMessage = await getErrorMessage(res, 'Failed to delete memory');
    throw new Error(errorMessage);
  }
}
```

- [ ] **Step 3: Create memory settings component**

Create `fronted/src/components/MemorySettingsSection.tsx`:

```tsx
import type { Memory } from '../types';

interface MemorySettingsSectionProps {
  memories: Memory[];
  draft: string;
  isLoading: boolean;
  onDraftChange: (value: string) => void;
  onCreate: () => void;
  onToggle: (memory: Memory) => void;
  onDelete: (memory: Memory) => void;
}

function getKindLabel(kind: string): string {
  switch (kind) {
    case 'preference':
      return 'Preference';
    case 'project':
      return 'Project';
    case 'tool':
      return 'Tool';
    default:
      return 'Fact';
  }
}

export default function MemorySettingsSection({
  memories,
  draft,
  isLoading,
  onDraftChange,
  onCreate,
  onToggle,
  onDelete,
}: MemorySettingsSectionProps) {
  return (
    <section className="settings-section">
      <div className="settings-section-head">
        <h3>Memory</h3>
        <span>{isLoading ? 'Loading' : `${memories.length} saved`}</span>
      </div>

      <div className="memory-create-row">
        <input
          value={draft}
          onChange={(event) => onDraftChange(event.target.value)}
          placeholder="Add a memory"
          aria-label="Add a memory"
        />
        <button type="button" onClick={onCreate} disabled={!draft.trim()}>
          Add
        </button>
      </div>

      {memories.length === 0 ? (
        <div className="settings-empty">No saved memories yet.</div>
      ) : (
        <div className="memory-list">
          {memories.map((memory) => (
            <div key={memory.id} className={`memory-item ${memory.enabled ? '' : 'is-disabled'}`}>
              <div className="memory-item-main">
                <strong>{getKindLabel(memory.kind)}</strong>
                <span>{memory.content}</span>
              </div>
              <div className="memory-item-actions">
                <button type="button" onClick={() => onToggle(memory)}>
                  {memory.enabled ? 'Disable' : 'Enable'}
                </button>
                <button type="button" onClick={() => onDelete(memory)}>
                  Delete
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
```

- [ ] **Step 4: Wire section into settings drawer**

In `fronted/src/components/SettingsDrawer.tsx`, import:

```tsx
import MemorySettingsSection from './MemorySettingsSection';
import type { Memory, ModelOption, ReasoningLevel } from '../types';
```

Extend `SettingsDrawerProps`:

```tsx
  memories: Memory[];
  memoryDraft: string;
  isMemoriesLoading: boolean;
  onMemoryDraftChange: (value: string) => void;
  onCreateMemory: () => void;
  onToggleMemory: (memory: Memory) => void;
  onDeleteMemory: (memory: Memory) => void;
```

Add those props to the component destructuring, then render this after the reasoning section:

```tsx
        <MemorySettingsSection
          memories={memories}
          draft={memoryDraft}
          isLoading={isMemoriesLoading}
          onDraftChange={onMemoryDraftChange}
          onCreate={onCreateMemory}
          onToggle={onToggleMemory}
          onDelete={onDeleteMemory}
        />
```

- [ ] **Step 5: Own memory state in App**

In `fronted/src/App.tsx`, add `Memory` to the type import:

```ts
  Memory,
```

Add state near the settings state:

```tsx
  const [memories, setMemories] = useState<Memory[]>([]);
  const [memoryDraft, setMemoryDraft] = useState('');
  const [isMemoriesLoading, setIsMemoriesLoading] = useState(false);
```

Add a loader:

```tsx
  const refreshMemories = useCallback(async () => {
    setIsMemoriesLoading(true);
    try {
      const data = await api.fetchMemories();
      setMemories(data);
    } catch (err) {
      console.error(err);
      const nextError = err instanceof Error ? err.message : 'Failed to fetch memories';
      setErrorMessage(nextError);
      toast.error({ content: nextError, placement: 'top' });
    } finally {
      setIsMemoriesLoading(false);
    }
  }, []);
```

Add an effect:

```tsx
  useEffect(() => {
    if (!currentUser || !isSettingsOpen) {
      return;
    }
    void refreshMemories();
  }, [currentUser, isSettingsOpen, refreshMemories]);
```

Add handlers:

```tsx
  const handleCreateMemory = useCallback(async () => {
    const content = memoryDraft.trim();
    if (!content) return;

    try {
      const created = await api.createMemory(content);
      setMemories((prev) => [created, ...prev]);
      setMemoryDraft('');
      toast.success({ content: 'Memory saved', placement: 'top' });
    } catch (err) {
      console.error(err);
      const nextError = err instanceof Error ? err.message : 'Failed to create memory';
      setErrorMessage(nextError);
      toast.error({ content: nextError, placement: 'top' });
    }
  }, [memoryDraft]);

  const handleToggleMemory = useCallback(async (memory: Memory) => {
    try {
      const updated = await api.updateMemory(memory.id, { enabled: !memory.enabled });
      setMemories((prev) => prev.map((item) => (item.id === updated.id ? updated : item)));
    } catch (err) {
      console.error(err);
      const nextError = err instanceof Error ? err.message : 'Failed to update memory';
      setErrorMessage(nextError);
      toast.error({ content: nextError, placement: 'top' });
    }
  }, []);

  const handleDeleteMemory = useCallback(async (memory: Memory) => {
    try {
      await api.deleteMemory(memory.id);
      setMemories((prev) => prev.filter((item) => item.id !== memory.id));
      toast.success({ content: 'Memory deleted', placement: 'top' });
    } catch (err) {
      console.error(err);
      const nextError = err instanceof Error ? err.message : 'Failed to delete memory';
      setErrorMessage(nextError);
      toast.error({ content: nextError, placement: 'top' });
    }
  }, []);
```

Pass props into `SettingsDrawer`:

```tsx
        memories={memories}
        memoryDraft={memoryDraft}
        isMemoriesLoading={isMemoriesLoading}
        onMemoryDraftChange={setMemoryDraft}
        onCreateMemory={handleCreateMemory}
        onToggleMemory={handleToggleMemory}
        onDeleteMemory={handleDeleteMemory}
```

- [ ] **Step 6: Add CSS**

Add to `fronted/src/App.css` after the existing settings styles:

```css
.memory-create-row {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 10px;
  margin-top: 14px;
}

.memory-create-row input {
  min-width: 0;
  height: 38px;
  padding: 0 12px;
  border: 1px solid rgba(43, 43, 48, 0.1);
  border-radius: 12px;
  background: rgba(246, 246, 248, 0.92);
  color: #26262b;
}

.memory-create-row button,
.memory-item-actions button {
  border: 1px solid rgba(43, 43, 48, 0.08);
  border-radius: 12px;
  background: rgba(246, 246, 248, 0.92);
  color: #26262b;
  font-size: 12px;
  font-weight: 600;
}

.memory-create-row button {
  height: 38px;
  padding: 0 14px;
}

.memory-create-row button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.memory-list {
  display: grid;
  gap: 10px;
  margin-top: 12px;
}

.memory-item {
  display: grid;
  gap: 10px;
  padding: 12px;
  border: 1px solid rgba(43, 43, 48, 0.08);
  border-radius: 14px;
  background: rgba(250, 250, 252, 0.88);
}

.memory-item.is-disabled {
  opacity: 0.58;
}

.memory-item-main {
  display: grid;
  gap: 4px;
}

.memory-item-main strong {
  color: #5b67ff;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.memory-item-main span {
  color: #26262b;
  font-size: 13px;
  line-height: 1.45;
}

.memory-item-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.memory-item-actions button {
  height: 30px;
  padding: 0 10px;
}
```

- [ ] **Step 7: Build frontend**

Run:

```bash
cd fronted
npm run build
```

Expected: build succeeds.

- [ ] **Step 8: Commit**

```bash
git -C fronted add src/types.ts src/services/api.ts src/components/MemorySettingsSection.tsx src/components/SettingsDrawer.tsx src/App.tsx src/App.css
git -C fronted commit -m "feat: add memory management settings"
```

---

### Task 6: Local PostgreSQL Verification

**Files:**
- No code files required.

- [ ] **Step 1: Create local PostgreSQL database**

Run using your local PostgreSQL setup:

```bash
createdb llm_memory_chat
```

Expected: database exists.

- [ ] **Step 2: Configure backend env**

Set `backend/.env` database line:

```env
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/llm_memory_chat
```

Keep existing model settings unchanged.

- [ ] **Step 3: Run migrations**

Run:

```bash
cd backend
alembic upgrade head
```

Expected: migration reaches `20260427_0002`.

- [ ] **Step 4: Run backend tests**

Run:

```bash
cd backend
PYTHONPATH=. python -m unittest discover tests -v
```

Expected: all tests pass.

- [ ] **Step 5: Run backend server**

Run:

```bash
cd backend
python run.py
```

Expected: server starts and `/api/health` returns `{"status":"ok"}`.

- [ ] **Step 6: Manual memory verification**

In the app:

1. Register or log in.
2. Open settings.
3. Add memory: `用户使用 PyCharm 开发 Python 项目`.
4. Send chat message: `我这个 IDE 里怎么打开数据库？`.
5. Confirm the assistant can use the PyCharm memory.
6. Disable the memory in settings.
7. Send a similar message again.
8. Confirm the disabled memory is not used.

- [ ] **Step 7: Final status check**

Run:

```bash
git -C backend status --short
git -C fronted status --short
```

Expected: both repositories show no unexpected uncommitted changes.

---

## Self-Review

Spec coverage:

- PostgreSQL: Task 1 and Task 6.
- Alembic: Task 1 and Task 6.
- `memories` table: Task 2.
- Memory injection before model call: Task 4.
- Explicit memory creation: Task 2 and Task 4.
- Authenticated CRUD API: Task 3.
- UI to view, disable, delete, and manually add memories: Task 5.
- No embedding or pgvector in phase 1: no task adds vector fields, embedding config, or similarity search.

Residual risk:

- Existing SQLite data is not automatically imported into PostgreSQL. This plan treats PostgreSQL as a fresh local database. Add a separate data migration plan if existing chat history must be preserved.
- The explicit-memory detector is intentionally conservative. It will not remember implicit preferences until a later phase adds safer extraction logic.
