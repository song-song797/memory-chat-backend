# 长期记忆第一阶段实施计划

> **给执行代理的说明：** 必须使用子技能：推荐使用 `superpowers:subagent-driven-development`，也可以使用 `superpowers:executing-plans`，并按任务逐项执行。步骤使用复选框（`- [ ]`）跟踪进度。

**目标：** 构建基于 PostgreSQL 的用户级长期记忆；第一阶段不加入 embedding 或 pgvector。

**架构：** 保留 SQLAlchemy 作为 ORM，引入 Alembic 管理数据库结构版本，并新增一张普通的 `memories` 表关联用户。聊天流程继续使用当前短期上下文，同时在每次调用大模型前，把少量启用中的用户长期记忆放到上下文前面。

**技术栈：** FastAPI、SQLAlchemy、Alembic、PostgreSQL（通过 `psycopg`）、React、TypeScript、Vite。

---

## 文件结构

后端文件：

- 修改 `backend/requirements.txt`：添加 PostgreSQL 和 Alembic 依赖。
- 修改 `backend/.env.example`：展示 PostgreSQL 版 `DATABASE_URL`。
- 新建 `backend/alembic.ini`：Alembic 命令行配置。
- 新建 `backend/alembic/env.py`：加载应用 metadata 和数据库 URL。
- 新建 `backend/alembic/versions/20260427_0001_create_initial_schema.py`：现有表结构的基线迁移。
- 新建 `backend/alembic/versions/20260427_0002_create_memories.py`：`memories` 表迁移。
- 修改 `backend/app/database.py`：应用启动时不再自动改数据库结构。
- 修改 `backend/app/models.py`：新增 `Memory` 模型。
- 修改 `backend/app/schemas.py`：新增记忆相关请求和响应 schema。
- 修改 `backend/app/services/memory_service.py`：在现有短期上下文逻辑旁边新增长期记忆 helper。
- 新建 `backend/app/routers/memories.py`：需要登录的记忆 CRUD 接口。
- 修改 `backend/app/main.py`：注册记忆 router。
- 修改 `backend/app/routers/chat.py`：保存明确记忆，并注入启用的长期记忆。
- 新建 `backend/tests/test_long_term_memory_service.py`：长期记忆服务层测试。
- 新建 `backend/tests/test_memory_routes.py`：需要登录的记忆 API 测试。

前端文件：

- 修改 `fronted/src/types.ts`：新增 `Memory` 类型。
- 修改 `fronted/src/services/api.ts`：新增记忆 CRUD 请求函数。
- 新建 `fronted/src/components/MemorySettingsSection.tsx`：独立的记忆管理 UI。
- 修改 `fronted/src/components/SettingsDrawer.tsx`：渲染记忆管理区块。
- 修改 `fronted/src/App.tsx`：管理记忆状态和交互函数。
- 修改 `fronted/src/App.css`：添加紧凑的记忆设置样式。

---

### 任务 1：PostgreSQL 和 Alembic 基线

**文件：**
- 修改：`backend/requirements.txt`
- 修改：`backend/.env.example`
- 新建：`backend/alembic.ini`
- 新建：`backend/alembic/env.py`
- 新建：`backend/alembic/versions/20260427_0001_create_initial_schema.py`
- 修改：`backend/app/database.py`

- [ ] **步骤 1：添加数据库依赖**

修改 `backend/requirements.txt`，加入这些新依赖：

```text
alembic==1.13.3
psycopg[binary]==3.2.3
```

- [ ] **步骤 2：更新示例数据库配置**

将 `backend/.env.example` 的数据库配置改成：

```env
# Database
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/llm_memory_chat
```

- [ ] **步骤 3：创建 Alembic 配置**

新建 `backend/alembic.ini`：

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

- [ ] **步骤 4：创建 Alembic 运行环境文件**

新建 `backend/alembic/env.py`：

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

- [ ] **步骤 5：创建基线迁移**

新建 `backend/alembic/versions/20260427_0001_create_initial_schema.py`：

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

- [ ] **步骤 6：停止应用启动时自动修改表结构**

修改 `backend/app/database.py`，让 `init_db()` 不再调用 `Base.metadata.create_all()`，也不再执行手写 `ALTER TABLE`：

```python
def init_db():
    """Schema is managed by Alembic migrations."""
    return None
```

同时从 `backend/app/database.py` 删除不再使用的 import：

```python
from sqlalchemy import create_engine
```

保留这个 import：

```python
from sqlalchemy.orm import DeclarativeBase, sessionmaker
```

- [ ] **步骤 7：安装依赖**

运行：

```bash
cd backend
python -m pip install -r requirements.txt
```

预期：命令成功结束，并安装 `alembic` 和 `psycopg`。

- [ ] **步骤 8：确认 Alembic 能识别迁移链路**

运行：

```bash
cd backend
alembic history
```

预期输出包含：

```text
20260427_0001 -> <base>, create initial schema
```

- [ ] **步骤 9：提交**

```bash
git -C backend add requirements.txt .env.example alembic.ini alembic app/database.py
git -C backend commit -m "chore: add postgres migration baseline"
```

---

### 任务 2：记忆模型、Schema 和服务层

**文件：**
- 修改：`backend/app/models.py`
- 修改：`backend/app/schemas.py`
- 修改：`backend/app/services/memory_service.py`
- 新建：`backend/alembic/versions/20260427_0002_create_memories.py`
- 新建：`backend/tests/test_long_term_memory_service.py`

- [ ] **步骤 1：先写服务层测试**

新建 `backend/tests/test_long_term_memory_service.py`：

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

- [ ] **步骤 2：运行测试，确认当前会失败**

运行：

```bash
cd backend
PYTHONPATH=. python -m unittest tests.test_long_term_memory_service -v
```

预期：测试失败，因为 `Memory` 和新的服务函数还不存在。

- [ ] **步骤 3：添加 Memory 模型**

在 `backend/app/models.py` 中，把 `Memory` 加入模型和关系定义。

给 `User` 添加这个 relationship：

```python
    memories: Mapped[list["Memory"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        order_by="Memory.updated_at.desc()",
    )
```

在 `Message` 后面添加这个类：

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

- [ ] **步骤 4：添加记忆 schema**

在 `backend/app/schemas.py` 中添加：

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

- [ ] **步骤 5：添加记忆表迁移**

新建 `backend/alembic/versions/20260427_0002_create_memories.py`：

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

- [ ] **步骤 6：添加长期记忆服务 helper**

将这些 helper 追加到 `backend/app/services/memory_service.py`：

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

同时更新 `memory_service.py` 顶部现有的模型 import：

```python
from ..models import Attachment, Conversation, Memory, Message
```

- [ ] **步骤 7：运行服务层测试**

运行：

```bash
cd backend
PYTHONPATH=. python -m unittest tests.test_long_term_memory_service -v
```

预期：全部测试通过。

- [ ] **步骤 8：提交**

```bash
git -C backend add app/models.py app/schemas.py app/services/memory_service.py alembic/versions/20260427_0002_create_memories.py tests/test_long_term_memory_service.py
git -C backend commit -m "feat: add long-term memory model"
```

---

### 任务 3：需要登录的记忆 API

**文件：**
- 新建：`backend/app/routers/memories.py`
- 修改：`backend/app/main.py`
- 新建：`backend/tests/test_memory_routes.py`

- [ ] **步骤 1：先写路由测试**

新建 `backend/tests/test_memory_routes.py`：

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

- [ ] **步骤 2：运行测试，确认当前会失败**

运行：

```bash
cd backend
PYTHONPATH=. python -m unittest tests.test_memory_routes -v
```

预期：测试失败，因为 `/api/memories` 路由还不存在。

- [ ] **步骤 3：添加记忆 router**

新建 `backend/app/routers/memories.py`：

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

- [ ] **步骤 4：注册 router**

修改 `backend/app/main.py` 的 imports：

```python
from .routers import attachments, auth, chat, conversations, memories
```

在已有 router include 后添加：

```python
app.include_router(memories.router)
```

- [ ] **步骤 5：运行路由测试**

运行：

```bash
cd backend
PYTHONPATH=. python -m unittest tests.test_memory_routes -v
```

预期：全部测试通过。

- [ ] **步骤 6：提交**

```bash
git -C backend add app/routers/memories.py app/main.py tests/test_memory_routes.py
git -C backend commit -m "feat: add memory management api"
```

---

### 任务 4：聊天中的记忆保存和注入

**文件：**
- 修改：`backend/app/routers/chat.py`
- 修改：`backend/tests/test_long_term_memory_service.py`
- 修改：`backend/tests/test_memory_service.py`

- [ ] **步骤 1：添加上下文组合测试**

将这个测试方法追加到 `backend/tests/test_long_term_memory_service.py` 的 `LongTermMemoryServiceTests` 中：

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

- [ ] **步骤 2：运行测试，确认当前会失败**

运行：

```bash
cd backend
PYTHONPATH=. python -m unittest tests.test_long_term_memory_service -v
```

预期：测试失败，因为 `get_chat_context_messages` 还不存在。

- [ ] **步骤 3：添加组合上下文 helper**

将这个函数添加到 `backend/app/services/memory_service.py`：

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

- [ ] **步骤 4：在聊天流程中使用组合上下文并保存明确记忆**

在 `backend/app/routers/chat.py` 中，在这一行后面：

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

替换：

```python
context = memory_service.get_context_messages(db, conv.id, current_model=chosen_model)
```

为：

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

- [ ] **步骤 5：运行全部后端单元测试**

运行：

```bash
cd backend
PYTHONPATH=. python -m unittest discover tests -v
```

预期：全部测试通过。

- [ ] **步骤 6：提交**

```bash
git -C backend add app/routers/chat.py app/services/memory_service.py tests/test_long_term_memory_service.py tests/test_memory_service.py
git -C backend commit -m "feat: use long-term memory in chat"
```

---

### 任务 5：前端记忆管理

**文件：**
- 修改：`fronted/src/types.ts`
- 修改：`fronted/src/services/api.ts`
- 新建：`fronted/src/components/MemorySettingsSection.tsx`
- 修改：`fronted/src/components/SettingsDrawer.tsx`
- 修改：`fronted/src/App.tsx`
- 修改：`fronted/src/App.css`

- [ ] **步骤 1：添加前端记忆类型**

添加到 `fronted/src/types.ts`：

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

- [ ] **步骤 2：添加 API 请求函数**

在 `fronted/src/services/api.ts` 的类型 import 中加入 `Memory`：

```ts
  Memory,
```

在 `sendMessage` 前添加这些函数：

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

- [ ] **步骤 3：创建记忆设置组件**

新建 `fronted/src/components/MemorySettingsSection.tsx`：

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
      return '偏好';
    case 'project':
      return '项目';
    case 'tool':
      return '工具';
    default:
      return '事实';
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
        <h3>长期记忆</h3>
        <span>{isLoading ? '加载中' : `已保存 ${memories.length} 条`}</span>
      </div>

      <div className="memory-create-row">
        <input
          value={draft}
          onChange={(event) => onDraftChange(event.target.value)}
          placeholder="添加一条记忆"
          aria-label="添加一条记忆"
        />
        <button type="button" onClick={onCreate} disabled={!draft.trim()}>
          添加
        </button>
      </div>

      {memories.length === 0 ? (
        <div className="settings-empty">还没有保存的记忆。</div>
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
                  {memory.enabled ? '停用' : '启用'}
                </button>
                <button type="button" onClick={() => onDelete(memory)}>
                  删除
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

- [ ] **步骤 4：把记忆区块接入设置抽屉**

在 `fronted/src/components/SettingsDrawer.tsx` 中 import：

```tsx
import MemorySettingsSection from './MemorySettingsSection';
import type { Memory, ModelOption, ReasoningLevel } from '../types';
```

扩展 `SettingsDrawerProps`：

```tsx
  memories: Memory[];
  memoryDraft: string;
  isMemoriesLoading: boolean;
  onMemoryDraftChange: (value: string) => void;
  onCreateMemory: () => void;
  onToggleMemory: (memory: Memory) => void;
  onDeleteMemory: (memory: Memory) => void;
```

将这些 props 加入组件解构，然后在 reasoning 区块后渲染：

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

- [ ] **步骤 5：在 App 中管理记忆状态**

在 `fronted/src/App.tsx` 中，把 `Memory` 加到类型 import：

```ts
  Memory,
```

在设置相关 state 附近添加：

```tsx
  const [memories, setMemories] = useState<Memory[]>([]);
  const [memoryDraft, setMemoryDraft] = useState('');
  const [isMemoriesLoading, setIsMemoriesLoading] = useState(false);
```

添加加载函数：

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

添加 effect：

```tsx
  useEffect(() => {
    if (!currentUser || !isSettingsOpen) {
      return;
    }
    void refreshMemories();
  }, [currentUser, isSettingsOpen, refreshMemories]);
```

添加交互处理函数：

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

把这些 props 传给 `SettingsDrawer`：

```tsx
        memories={memories}
        memoryDraft={memoryDraft}
        isMemoriesLoading={isMemoriesLoading}
        onMemoryDraftChange={setMemoryDraft}
        onCreateMemory={handleCreateMemory}
        onToggleMemory={handleToggleMemory}
        onDeleteMemory={handleDeleteMemory}
```

- [ ] **步骤 6：添加 CSS**

添加到 `fronted/src/App.css` 中现有 settings 样式后面：

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

- [ ] **步骤 7：构建前端**

运行：

```bash
cd fronted
npm run build
```

预期：构建成功。

- [ ] **步骤 8：提交**

```bash
git -C fronted add src/types.ts src/services/api.ts src/components/MemorySettingsSection.tsx src/components/SettingsDrawer.tsx src/App.tsx src/App.css
git -C fronted commit -m "feat: add memory management settings"
```

---

### 任务 6：本地 PostgreSQL 验证

**文件：**
- 不需要修改代码文件。

- [ ] **步骤 1：创建本地 PostgreSQL 数据库**

使用本地 PostgreSQL 环境运行：

```bash
createdb llm_memory_chat
```

预期：数据库创建成功。

- [ ] **步骤 2：配置后端环境变量**

将 `backend/.env` 的数据库连接改为：

```env
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/llm_memory_chat
```

保留现有模型相关配置不变。

- [ ] **步骤 3：运行数据库迁移**

运行：

```bash
cd backend
alembic upgrade head
```

预期：迁移执行到 `20260427_0002`。

- [ ] **步骤 4：运行后端测试**

运行：

```bash
cd backend
PYTHONPATH=. python -m unittest discover tests -v
```

预期：全部测试通过。

- [ ] **步骤 5：启动后端服务**

运行：

```bash
cd backend
python run.py
```

预期：服务启动成功，并且 `/api/health` 返回 `{"status":"ok"}`。

- [ ] **步骤 6：手动验证记忆功能**

在应用里：

1. 注册或登录。
2. 打开设置。
3. 添加记忆：`用户使用 PyCharm 开发 Python 项目`。
4. 发送聊天消息：`我这个 IDE 里怎么打开数据库？`。
5. 确认助手能使用 PyCharm 这条记忆。
6. 在设置中停用这条记忆。
7. 再发送一条类似消息。
8. 确认已停用的记忆不会再被使用。

- [ ] **步骤 7：最终状态检查**

运行：

```bash
git -C backend status --short
git -C fronted status --short
```

预期：两个仓库都没有意外的未提交变更。

---

## 自检

设计覆盖情况：

- PostgreSQL：任务 1 和任务 6。
- Alembic：任务 1 和任务 6。
- `memories` 表：任务 2。
- 模型调用前注入记忆：任务 4。
- 明确记忆创建：任务 2 和任务 4。
- 需要登录的 CRUD API：任务 3。
- 查看、停用、删除、手动添加记忆的 UI：任务 5。
- 第一阶段不做 embedding 或 pgvector：没有任何任务添加向量字段、embedding 配置或相似度搜索。

剩余风险：

- 现有 SQLite 数据不会自动导入 PostgreSQL。本计划默认 PostgreSQL 是一个新的本地数据库。如果必须保留现有聊天历史，需要单独制定数据迁移计划。
- 明确记忆检测逻辑会故意保守。隐含偏好不会被自动记住，直到后续阶段加入更安全的抽取逻辑。
