# Project Workspaces Memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add project workspaces while preserving ordinary chats and global memories, so project chats get project-scoped history and memory without losing cross-project user preferences.

**Architecture:** The backend adds `projects` as a first-class user-owned resource, keeps ordinary chats as `conversations.project_id = null`, and keeps global memories as `memories.scope = "global"` with `project_id = null`. The frontend keeps the sidebar as an all-chat entry point, grouping ordinary chats and project chats without hiding unrelated conversations.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, Pydantic, pytest/unittest, React, TypeScript, Vite.

---

## Source Spec

Implement the approved design in:

- `backend/docs/superpowers/specs/2026-04-27-project-workspaces-memory-design.md`

Important product constraints:

- Ordinary chats must continue to exist.
- A project is a workspace, not a tag.
- Global memories are narrow, stable, cross-project preferences.
- Project memories can override global memories.
- Automatic cleanup archives/supersedes memory; it does not hard-delete by default.
- Sidebar shows all chats, grouped by ordinary/project ownership.

## File Structure

Backend files:

- Modify `backend/app/models.py`: add `Project`, relationships, `Conversation.project_id`, and memory scope/status fields.
- Modify `backend/app/schemas.py`: add project schemas and expose project/memory scope fields.
- Create `backend/app/services/project_service.py`: shared project ownership helpers.
- Create `backend/app/routers/projects.py`: project list/create/update/archive API.
- Modify `backend/app/routers/conversations.py`: validate project ownership, support `project_id`, preserve all-chat listing.
- Modify `backend/app/routers/memories.py`: add global/project memory filters and validation.
- Modify `backend/app/routers/chat.py`: parse `project_id`, create project chats, reject conversation/project conflicts.
- Modify `backend/app/services/memory_service.py`: inject global memory plus current-project memory.
- Modify `backend/app/main.py`: include the projects router.
- Create `backend/alembic/versions/20260427_0003_create_projects_and_project_memory_scope.py`: schema and backfill.
- Create `backend/tests/test_project_routes.py`: project API tests.
- Create `backend/tests/test_conversation_project_routes.py`: conversation project tests.
- Modify `backend/tests/test_memory_routes.py`: scoped memory route tests.
- Modify `backend/tests/test_long_term_memory_service.py`: memory injection and chat routing tests.
- Create `backend/tests/test_project_workspace_migration.py`: schema smoke tests for project workspace metadata.

Frontend files:

- Modify `fronted/src/types.ts`: add `Project`; extend `Conversation` and `Memory`.
- Modify `fronted/src/services/api.ts`: add project APIs and scoped memory/project chat parameters.
- Modify `fronted/src/App.tsx`: own project state, active/draft project context, scoped memory loading, project handlers.
- Modify `fronted/src/components/Sidebar.tsx`: group ordinary chats and project chats; add project create/edit/archive controls.
- Create `fronted/src/components/ProjectFormDialog.tsx`: small create/edit project dialog.
- Create `fronted/src/components/ProjectGroup.tsx`: focused project group renderer.
- Modify `fronted/src/components/SettingsDrawer.tsx`: pass active project and split memory props.
- Modify `fronted/src/components/MemorySettingsSection.tsx`: render global and current-project sections.
- Modify `fronted/src/App.css`: style project groups, project controls, source badges, and split memory sections.

## Commit Strategy

Commit after each task with the repository convention:

- Backend commits run in `/Users/Zhuanz/github.com/llm-memory-chat/backend`.
- Frontend commits run in `/Users/Zhuanz/github.com/llm-memory-chat/fronted`.
- Do not commit the workspace root repository.
- Do not stage the unrelated untracked files already present in `backend/docs/superpowers/plans/2026-04-27-ai-memory-candidates-phase-2.md` or `backend/docs/superpowers/specs/2026-04-27-ai-memory-candidates-phase-2-design.md`.

## Subagent Execution Notes

Use fresh worker subagents per task. Give each worker ownership of only the files listed for that task. Workers are not alone in the codebase; they must not revert edits made by others and must adapt to already-merged task output.

Recommended execution order:

1. Backend Tasks 1-6 sequentially.
2. Frontend Tasks 7-10 sequentially after Backend Task 4 has fixed API shapes.
3. Final verification in Task 11.

Do not run frontend workers in parallel with backend API-shape workers unless the backend contract has already landed.

---

### Task 1: Backend Data Model And Migration

**Files:**

- Modify: `backend/app/models.py`
- Create: `backend/alembic/versions/20260427_0003_create_projects_and_project_memory_scope.py`
- Test: `backend/tests/test_project_workspace_migration.py`

- [ ] **Step 1: Add failing model tests through SQLAlchemy metadata**

Create `backend/tests/test_project_workspace_migration.py` with this smoke test:

```python
import unittest

from sqlalchemy import create_engine, inspect

from app.database import Base


class ProjectWorkspaceModelTests(unittest.TestCase):
    def test_workspace_columns_exist_in_metadata(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        inspector = inspect(engine)

        self.assertIn("projects", inspector.get_table_names())
        conversation_columns = {column["name"] for column in inspector.get_columns("conversations")}
        memory_columns = {column["name"] for column in inspector.get_columns("memories")}

        self.assertIn("project_id", conversation_columns)
        self.assertIn("project_id", memory_columns)
        self.assertIn("scope", memory_columns)
        self.assertIn("status", memory_columns)
        self.assertIn("importance", memory_columns)
        self.assertIn("superseded_by_id", memory_columns)
        self.assertIn("archived_at", memory_columns)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the model test and verify it fails**

Run:

```bash
cd /Users/Zhuanz/github.com/llm-memory-chat/backend
.venv/bin/python -m pytest tests/test_project_workspace_migration.py -q
```

Expected: fail because `projects` or the new columns do not exist.

- [ ] **Step 3: Implement the SQLAlchemy model changes**

In `backend/app/models.py`, add `Project` and relationships. Keep existing style and `_new_id()` defaults.

```python
class User(Base):
    projects: Mapped[list["Project"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        order_by="Project.updated_at.desc()",
    )
```

```python
class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    default_reasoning_level: Mapped[str | None] = mapped_column(String(20), nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    user: Mapped["User"] = relationship(back_populates="projects")
    conversations: Mapped[list["Conversation"]] = relationship(
        back_populates="project",
        order_by="Conversation.updated_at.desc()",
    )
    memories: Mapped[list["Memory"]] = relationship(
        back_populates="project",
        order_by="Memory.updated_at.desc()",
    )
```

Extend `Conversation`:

```python
project_id: Mapped[str | None] = mapped_column(
    String(32), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
)
project: Mapped["Project | None"] = relationship(back_populates="conversations")
```

Extend `Memory`:

```python
project_id: Mapped[str | None] = mapped_column(
    String(32), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
)
scope: Mapped[str] = mapped_column(String(20), default="global")
status: Mapped[str] = mapped_column(String(20), default="active")
importance: Mapped[int] = mapped_column(Integer, default=0)
superseded_by_id: Mapped[str | None] = mapped_column(
    String(32), ForeignKey("memories.id", ondelete="SET NULL"), nullable=True
)
archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

project: Mapped["Project | None"] = relationship(back_populates="memories")
superseded_by: Mapped["Memory | None"] = relationship(remote_side="Memory.id")
```

- [ ] **Step 4: Add Alembic migration and backfill**

Create `backend/alembic/versions/20260427_0003_create_projects_and_project_memory_scope.py`.

Migration rules:

- Create `projects`.
- Add nullable `conversations.project_id`.
- Add nullable `memories.project_id`, `scope`, `status`, `importance`, `superseded_by_id`, `archived_at`.
- Backfill one default project named `个人空间` per existing user.
- Assign old conversations to that user's default project.
- Keep `preference`, `tool`, and `fact` memories global.
- Move old `kind = "project"` memories into the user's default project and set `scope = "project"`.

Use Alembic operations, not raw model imports. The migration may use SQL text for data backfill.

- [ ] **Step 5: Run the focused test**

Run:

```bash
cd /Users/Zhuanz/github.com/llm-memory-chat/backend
.venv/bin/python -m pytest tests/test_project_workspace_migration.py -q
```

Expected: pass.

- [ ] **Step 6: Run existing memory service tests**

Run:

```bash
cd /Users/Zhuanz/github.com/llm-memory-chat/backend
.venv/bin/python -m pytest tests/test_long_term_memory_service.py tests/test_memory_routes.py -q
```

Expected: pass, proving the added fields preserved current behavior.

- [ ] **Step 7: Commit**

```bash
cd /Users/Zhuanz/github.com/llm-memory-chat/backend
git add app/models.py alembic/versions/20260427_0003_create_projects_and_project_memory_scope.py tests/test_project_workspace_migration.py
git commit -m "feat: add project workspace data model"
```

---

### Task 2: Backend Projects API

**Files:**

- Create: `backend/app/services/project_service.py`
- Create: `backend/app/routers/projects.py`
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_project_routes.py`

- [ ] **Step 1: Write failing project route tests**

Create `backend/tests/test_project_routes.py` using the same temp SQLite pattern from `tests/test_memory_routes.py`.

Required test methods:

```python
def test_project_crud_and_archive_filtering(self) -> None:
    headers = self._register("projects@example.com")

    create_response = self.client.post(
        "/api/projects",
        json={
            "name": "Memory App",
            "description": "Project workspace test",
            "default_model": "MiniMax-M2.5",
            "default_reasoning_level": "standard",
        },
        headers=headers,
    )
    self.assertEqual(create_response.status_code, 201)
    created = create_response.json()
    self.assertEqual(created["name"], "Memory App")
    self.assertFalse(created["is_default"])
    self.assertIsNone(created["archived_at"])

    list_response = self.client.get("/api/projects", headers=headers)
    self.assertEqual(list_response.status_code, 200)
    self.assertEqual([item["id"] for item in list_response.json()], [created["id"]])

    archive_response = self.client.put(
        f"/api/projects/{created['id']}",
        json={"archived": True},
        headers=headers,
    )
    self.assertEqual(archive_response.status_code, 200)
    self.assertIsNotNone(archive_response.json()["archived_at"])

    active_list = self.client.get("/api/projects", headers=headers)
    self.assertEqual(active_list.json(), [])

    all_list = self.client.get("/api/projects?include_archived=true", headers=headers)
    self.assertEqual(len(all_list.json()), 1)
```

```python
def test_projects_are_isolated_by_user(self) -> None:
    alice_headers = self._register("alice-project@example.com")
    bob_headers = self._register("bob-project@example.com")

    create_response = self.client.post(
        "/api/projects",
        json={"name": "Alice Project"},
        headers=alice_headers,
    )
    self.assertEqual(create_response.status_code, 201)
    project_id = create_response.json()["id"]

    bob_list = self.client.get("/api/projects", headers=bob_headers)
    self.assertEqual(bob_list.status_code, 200)
    self.assertEqual(bob_list.json(), [])

    bob_update = self.client.put(
        f"/api/projects/{project_id}",
        json={"name": "Stolen"},
        headers=bob_headers,
    )
    self.assertEqual(bob_update.status_code, 404)
```

Add tests for blank project names and unsupported default reasoning values:

```python
def test_project_name_cannot_be_blank(self) -> None:
    headers = self._register("blank-project@example.com")
    response = self.client.post("/api/projects", json={"name": "   "}, headers=headers)
    self.assertEqual(response.status_code, 400)
    self.assertEqual(response.json()["detail"], "Project name cannot be empty")
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
cd /Users/Zhuanz/github.com/llm-memory-chat/backend
.venv/bin/python -m pytest tests/test_project_routes.py -q
```

Expected: fail because `/api/projects` is not registered.

- [ ] **Step 3: Add project schemas**

In `backend/app/schemas.py`, add:

```python
class ProjectCreate(BaseModel):
    name: str = Field(..., max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    default_model: str | None = Field(default=None, max_length=100)
    default_reasoning_level: Literal["off", "standard", "deep"] | None = None


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    default_model: str | None = Field(default=None, max_length=100)
    default_reasoning_level: Literal["off", "standard", "deep"] | None = None
    archived: bool | None = None


class ProjectOut(BaseModel):
    id: str
    name: str
    description: str | None = None
    default_model: str | None = None
    default_reasoning_level: str | None = None
    is_default: bool
    archived_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @field_serializer("created_at", "updated_at", "archived_at")
    def serialize_project_datetimes(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        return _serialize_datetime(value)
```

- [ ] **Step 4: Add shared project service helpers**

Create `backend/app/services/project_service.py`:

```python
from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..models import Project


def trim_project_name(value: str) -> str:
    trimmed = value.strip()
    if not trimmed:
        raise HTTPException(status_code=400, detail="Project name cannot be empty")
    return trimmed


def get_user_project(db: Session, user_id: str, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if not project or project.user_id != user_id:
        raise HTTPException(status_code=404, detail="Project not found")
    return project
```

- [ ] **Step 5: Add projects router**

Create `backend/app/routers/projects.py`:

```python
from datetime import timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Project, User, _utcnow
from ..schemas import ProjectCreate, ProjectOut, ProjectUpdate
from ..services.auth_service import get_current_user
from ..services.project_service import get_user_project, trim_project_name

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("", response_model=list[ProjectOut])
def list_projects(
    include_archived: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(Project).where(Project.user_id == current_user.id)
    if not include_archived:
        stmt = stmt.where(Project.archived_at.is_(None))
    stmt = stmt.order_by(Project.is_default.desc(), Project.updated_at.desc())
    return list(db.execute(stmt).scalars().all())


@router.post("", response_model=ProjectOut, status_code=201)
def create_project(
    body: ProjectCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = Project(
        user_id=current_user.id,
        name=trim_project_name(body.name),
        description=body.description.strip() if body.description else None,
        default_model=body.default_model,
        default_reasoning_level=body.default_reasoning_level,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.put("/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: str,
    body: ProjectUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_user_project(db, current_user.id, project_id)
    if (
        body.name is None
        and body.description is None
        and body.default_model is None
        and body.default_reasoning_level is None
        and body.archived is None
    ):
        raise HTTPException(status_code=400, detail="No project changes provided")

    if body.name is not None:
        project.name = trim_project_name(body.name)
    if body.description is not None:
        project.description = body.description.strip() or None
    if body.default_model is not None:
        project.default_model = body.default_model
    if body.default_reasoning_level is not None:
        project.default_reasoning_level = body.default_reasoning_level
    if body.archived is not None:
        project.archived_at = _utcnow() if body.archived else None

    db.commit()
    db.refresh(project)
    return project
```

- [ ] **Step 6: Register projects router**

In `backend/app/main.py`, include `projects` next to the existing routers:

```python
from .routers import attachments, auth, chat, conversations, memories, projects

app.include_router(projects.router)
```

- [ ] **Step 7: Run project route tests**

Run:

```bash
cd /Users/Zhuanz/github.com/llm-memory-chat/backend
.venv/bin/python -m pytest tests/test_project_routes.py -q
```

Expected: pass.

- [ ] **Step 8: Commit**

```bash
cd /Users/Zhuanz/github.com/llm-memory-chat/backend
git add app/schemas.py app/services/project_service.py app/routers/projects.py app/main.py tests/test_project_routes.py
git commit -m "feat: add project workspace API"
```

---

### Task 3: Backend Conversations Project Support

**Files:**

- Modify: `backend/app/schemas.py`
- Modify: `backend/app/routers/conversations.py`
- Test: `backend/tests/test_conversation_project_routes.py`
- Test regression: `backend/tests/test_auth_routes.py`

- [ ] **Step 1: Write failing conversation project route tests**

Create `backend/tests/test_conversation_project_routes.py` with the temp SQLite pattern.

Required tests:

```python
def test_create_ordinary_and_project_conversations(self) -> None:
    headers = self._register("conversation-project@example.com")
    project = self.client.post("/api/projects", json={"name": "App"}, headers=headers).json()

    ordinary = self.client.post(
        "/api/conversations",
        json={"title": "Ordinary"},
        headers=headers,
    )
    self.assertEqual(ordinary.status_code, 201)
    self.assertIsNone(ordinary.json()["project_id"])

    project_chat = self.client.post(
        "/api/conversations",
        json={"title": "Project chat", "project_id": project["id"]},
        headers=headers,
    )
    self.assertEqual(project_chat.status_code, 201)
    self.assertEqual(project_chat.json()["project_id"], project["id"])
```

```python
def test_list_all_and_filter_by_project(self) -> None:
    headers = self._register("list-project-conversations@example.com")
    project = self.client.post("/api/projects", json={"name": "Scoped"}, headers=headers).json()

    self.client.post("/api/conversations", json={"title": "Ordinary"}, headers=headers)
    self.client.post(
        "/api/conversations",
        json={"title": "Scoped", "project_id": project["id"]},
        headers=headers,
    )

    all_response = self.client.get("/api/conversations", headers=headers)
    self.assertEqual(all_response.status_code, 200)
    self.assertEqual(len(all_response.json()), 2)

    filtered = self.client.get(
        f"/api/conversations?project_id={project['id']}",
        headers=headers,
    )
    self.assertEqual(filtered.status_code, 200)
    self.assertEqual(len(filtered.json()), 1)
    self.assertEqual(filtered.json()[0]["project_id"], project["id"])
```

```python
def test_cross_user_project_cannot_be_used_for_conversation(self) -> None:
    alice_headers = self._register("alice-conv-project@example.com")
    bob_headers = self._register("bob-conv-project@example.com")
    project = self.client.post("/api/projects", json={"name": "Alice"}, headers=alice_headers).json()

    response = self.client.post(
        "/api/conversations",
        json={"title": "Wrong", "project_id": project["id"]},
        headers=bob_headers,
    )
    self.assertEqual(response.status_code, 404)
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
cd /Users/Zhuanz/github.com/llm-memory-chat/backend
.venv/bin/python -m pytest tests/test_conversation_project_routes.py -q
```

Expected: fail because conversation schemas/routes do not accept or return `project_id`.

- [ ] **Step 3: Extend conversation schemas**

In `backend/app/schemas.py`:

```python
class ConversationCreate(BaseModel):
    title: str = "\u65b0\u5bf9\u8bdd"
    project_id: str | None = None
```

```python
class ConversationOut(BaseModel):
    id: str
    title: str
    pinned: bool
    project_id: str | None = None
    created_at: datetime
    updated_at: datetime
```

- [ ] **Step 4: Update conversation router**

In `backend/app/routers/conversations.py`, import `Project` helper:

```python
from ..services.project_service import get_user_project
```

Update `create_conversation`:

```python
project_id = None
if body.project_id:
    project = get_user_project(db, current_user.id, body.project_id)
    project_id = project.id

conversation = Conversation(title=body.title, user_id=current_user.id, project_id=project_id)
```

Update `list_conversations` signature and query:

```python
def list_conversations(
    project_id: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(Conversation).where(Conversation.user_id == current_user.id)
    if project_id is not None:
        get_user_project(db, current_user.id, project_id)
        stmt = stmt.where(Conversation.project_id == project_id)
    stmt = stmt.order_by(Conversation.pinned.desc(), Conversation.updated_at.desc())
    return list(db.execute(stmt).scalars().all())
```

- [ ] **Step 5: Run conversation project tests**

Run:

```bash
cd /Users/Zhuanz/github.com/llm-memory-chat/backend
.venv/bin/python -m pytest tests/test_conversation_project_routes.py tests/test_auth_routes.py -q
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
cd /Users/Zhuanz/github.com/llm-memory-chat/backend
git add app/schemas.py app/routers/conversations.py tests/test_conversation_project_routes.py tests/test_auth_routes.py
git commit -m "feat: support project conversations"
```

---

### Task 4: Backend Scoped Memories

**Files:**

- Modify: `backend/app/schemas.py`
- Modify: `backend/app/routers/memories.py`
- Test: `backend/tests/test_memory_routes.py`

- [ ] **Step 1: Add failing scoped memory route tests**

Append tests to `backend/tests/test_memory_routes.py`.

```python
def test_global_and_project_memory_filters(self) -> None:
    headers = self._register("scoped-memory@example.com")
    project = self.client.post("/api/projects", json={"name": "Memory Project"}, headers=headers).json()

    global_create = self.client.post(
        "/api/memories",
        json={"content": "用户喜欢中文回答", "kind": "preference", "scope": "global"},
        headers=headers,
    )
    self.assertEqual(global_create.status_code, 201)
    self.assertEqual(global_create.json()["scope"], "global")
    self.assertIsNone(global_create.json()["project_id"])

    project_create = self.client.post(
        "/api/memories",
        json={
            "content": "本项目使用 TypeScript",
            "kind": "tech_stack",
            "scope": "project",
            "project_id": project["id"],
        },
        headers=headers,
    )
    self.assertEqual(project_create.status_code, 201)
    self.assertEqual(project_create.json()["scope"], "project")
    self.assertEqual(project_create.json()["project_id"], project["id"])

    global_list = self.client.get("/api/memories?scope=global", headers=headers)
    self.assertEqual([item["id"] for item in global_list.json()], [global_create.json()["id"]])

    project_list = self.client.get(
        f"/api/memories?scope=project&project_id={project['id']}",
        headers=headers,
    )
    self.assertEqual([item["id"] for item in project_list.json()], [project_create.json()["id"]])
```

```python
def test_project_memory_requires_project_id(self) -> None:
    headers = self._register("project-memory-validation@example.com")
    response = self.client.post(
        "/api/memories",
        json={"content": "Project fact", "kind": "fact", "scope": "project"},
        headers=headers,
    )
    self.assertEqual(response.status_code, 400)
    self.assertEqual(response.json()["detail"], "Project memory requires project_id")
```

```python
def test_global_memory_rejects_project_id(self) -> None:
    headers = self._register("global-memory-validation@example.com")
    project = self.client.post("/api/projects", json={"name": "Project"}, headers=headers).json()
    response = self.client.post(
        "/api/memories",
        json={
            "content": "Global fact",
            "kind": "fact",
            "scope": "global",
            "project_id": project["id"],
        },
        headers=headers,
    )
    self.assertEqual(response.status_code, 400)
    self.assertEqual(response.json()["detail"], "Global memory cannot have project_id")
```

```python
def test_memory_can_be_archived_without_hard_delete(self) -> None:
    headers = self._register("archive-memory@example.com")
    create_response = self.client.post(
        "/api/memories",
        json={"content": "Old preference", "kind": "preference", "scope": "global"},
        headers=headers,
    )
    memory_id = create_response.json()["id"]

    update_response = self.client.put(
        f"/api/memories/{memory_id}",
        json={"status": "archived"},
        headers=headers,
    )
    self.assertEqual(update_response.status_code, 200)
    self.assertEqual(update_response.json()["status"], "archived")
    self.assertIsNotNone(update_response.json()["archived_at"])
```

- [ ] **Step 2: Run memory route tests and verify they fail**

Run:

```bash
cd /Users/Zhuanz/github.com/llm-memory-chat/backend
.venv/bin/python -m pytest tests/test_memory_routes.py -q
```

Expected: fail because schemas/routes do not support scope/status/project fields.

- [ ] **Step 3: Extend memory schemas**

In `backend/app/schemas.py`:

```python
class MemoryCreate(BaseModel):
    content: str = Field(..., max_length=1000)
    kind: str = Field(default="fact", max_length=40)
    scope: Literal["global", "project"] = "global"
    project_id: str | None = None
    importance: int = 0
```

```python
class MemoryUpdate(BaseModel):
    content: str | None = Field(default=None, max_length=1000)
    kind: str | None = Field(default=None, max_length=40)
    enabled: bool | None = None
    status: Literal["active", "archived"] | None = None
    importance: int | None = None
    superseded_by_id: str | None = None
```

```python
class MemoryOut(BaseModel):
    id: str
    content: str
    kind: str
    scope: str
    project_id: str | None = None
    status: str
    importance: int
    enabled: bool
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None
    last_used_at: datetime | None = None
    superseded_by_id: str | None = None
```

Update the serializer to include `archived_at`.

- [ ] **Step 4: Update memories router validation**

In `backend/app/routers/memories.py`, import `_utcnow` and project helper:

```python
from ..models import Memory, User, _utcnow
from ..services.project_service import get_user_project
```

Add helper:

```python
def _validate_memory_scope(
    db: Session,
    user_id: str,
    scope: str,
    project_id: str | None,
) -> str | None:
    if scope == "global":
        if project_id is not None:
            raise HTTPException(status_code=400, detail="Global memory cannot have project_id")
        return None

    if project_id is None:
        raise HTTPException(status_code=400, detail="Project memory requires project_id")

    project = get_user_project(db, user_id, project_id)
    return project.id
```

Update `list_memories`:

```python
def list_memories(
    scope: str | None = None,
    project_id: str | None = None,
    include_archived: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(Memory).where(Memory.user_id == current_user.id)
    if scope is not None:
        if scope not in {"global", "project"}:
            raise HTTPException(status_code=400, detail="Invalid memory scope")
        stmt = stmt.where(Memory.scope == scope)
    if project_id is not None:
        get_user_project(db, current_user.id, project_id)
        stmt = stmt.where(Memory.project_id == project_id)
    if not include_archived:
        stmt = stmt.where(Memory.status == "active")
    stmt = stmt.order_by(Memory.updated_at.desc())
    return list(db.execute(stmt).scalars().all())
```

Update `create_memory`:

```python
project_id = _validate_memory_scope(db, current_user.id, body.scope, body.project_id)
memory = Memory(
    user_id=current_user.id,
    project_id=project_id,
    scope=body.scope,
    content=_trim_required(body.content, "content"),
    kind=_trim_required(body.kind, "kind"),
    importance=body.importance,
)
```

Update `update_memory` no-change check and status:

```python
if (
    body.content is None
    and body.kind is None
    and body.enabled is None
    and body.status is None
    and body.importance is None
    and body.superseded_by_id is None
):
    raise HTTPException(status_code=400, detail="No memory changes provided")

if body.status is not None:
    memory.status = body.status
    memory.archived_at = _utcnow() if body.status == "archived" else None
```

- [ ] **Step 5: Run memory route tests**

Run:

```bash
cd /Users/Zhuanz/github.com/llm-memory-chat/backend
.venv/bin/python -m pytest tests/test_memory_routes.py -q
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
cd /Users/Zhuanz/github.com/llm-memory-chat/backend
git add app/schemas.py app/routers/memories.py tests/test_memory_routes.py
git commit -m "feat: add scoped memory management"
```

---

### Task 5: Backend Chat Project Routing

**Files:**

- Modify: `backend/app/schemas.py`
- Modify: `backend/app/routers/chat.py`
- Test: `backend/tests/test_long_term_memory_service.py`

- [ ] **Step 1: Add failing chat project tests**

In `backend/tests/test_long_term_memory_service.py`, add route tests in `ChatMemoryRouteTests`.

Patch `llm_service.stream_chat_completion` to avoid external calls:

```python
async def fake_stream(*args, **kwargs):
    yield "ok"
```

Required tests:

```python
def test_chat_can_create_project_conversation(self) -> None:
    app.dependency_overrides[get_db] = self._override_get_db()
    chat_router.SessionLocal = self.SessionLocal

    with TestClient(app) as client:
        register = client.post(
            "/api/auth/register",
            json={"email": "project-chat@example.com", "password": "password123"},
        )
        headers = {"Authorization": f"Bearer {register.json()['token']}"}
        project = client.post("/api/projects", json={"name": "Chat Project"}, headers=headers).json()

        with unittest.mock.patch.object(chat_router.llm_service, "stream_chat_completion", fake_stream):
            response = client.post(
                "/api/chat",
                json={"message": "hello", "project_id": project["id"]},
                headers=headers,
            )

    self.assertEqual(response.status_code, 200)
    db = self.SessionLocal()
    try:
        conversation = db.query(Conversation).one()
        self.assertEqual(conversation.project_id, project["id"])
    finally:
        db.close()
```

```python
def test_chat_rejects_conversation_project_conflict(self) -> None:
    app.dependency_overrides[get_db] = self._override_get_db()
    chat_router.SessionLocal = self.SessionLocal

    with TestClient(app) as client:
        register = client.post(
            "/api/auth/register",
            json={"email": "project-conflict@example.com", "password": "password123"},
        )
        headers = {"Authorization": f"Bearer {register.json()['token']}"}
        first = client.post("/api/projects", json={"name": "First"}, headers=headers).json()
        second = client.post("/api/projects", json={"name": "Second"}, headers=headers).json()
        conversation = client.post(
            "/api/conversations",
            json={"title": "Scoped", "project_id": first["id"]},
            headers=headers,
        ).json()

        response = client.post(
            "/api/chat",
            json={
                "conversation_id": conversation["id"],
                "project_id": second["id"],
                "message": "wrong",
            },
            headers=headers,
        )

    self.assertEqual(response.status_code, 400)
    self.assertEqual(response.json()["detail"], "Conversation project mismatch")
```

If `_override_get_db()` does not exist, add a small helper method to `ChatMemoryRouteTests`.

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
cd /Users/Zhuanz/github.com/llm-memory-chat/backend
.venv/bin/python -m pytest tests/test_long_term_memory_service.py -q
```

Expected: fail because `ChatRequest` and `/api/chat` do not handle `project_id`.

- [ ] **Step 3: Extend chat schema and parser**

In `backend/app/schemas.py`:

```python
class ChatRequest(BaseModel):
    conversation_id: str | None = None
    project_id: str | None = None
    message: str = Field(default="", max_length=10000)
    model: str | None = None
    reasoning_level: Literal["off", "standard", "deep"] | None = None
    mode: Literal["fast", "think"] | None = None
```

In `backend/app/routers/chat.py`, include multipart `project_id`:

```python
project_id=form.get("project_id") or None,
```

- [ ] **Step 4: Validate project and create scoped conversations**

In `backend/app/routers/chat.py`, import:

```python
from ..services.project_service import get_user_project
```

Update conversation resolution:

```python
request_project_id = req.project_id

if req.conversation_id:
    conv = db.get(Conversation, req.conversation_id)
    if not conv or conv.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if request_project_id and conv.project_id != request_project_id:
        raise HTTPException(status_code=400, detail="Conversation project mismatch")
else:
    project_id = None
    if request_project_id:
        project = get_user_project(db, current_user.id, request_project_id)
        project_id = project.id
    conv = Conversation(user_id=current_user.id, project_id=project_id)
    db.add(conv)
    db.commit()
    db.refresh(conv)
```

- [ ] **Step 5: Pass project context to memory storage and injection**

Leave the function call ready for Task 6:

```python
memory_service.maybe_store_explicit_memory(
    db,
    current_user.id,
    user_message,
    project_id=conv.project_id,
)
```

```python
context = memory_service.get_chat_context_messages(
    db,
    current_user.id,
    conv.id,
    current_model=chosen_model,
    project_id=conv.project_id,
)
```

Task 6 will update these service signatures. If tests fail here because signatures do not exist, update Task 6 immediately before committing Task 5, or merge Tasks 5 and 6 in one commit.

- [ ] **Step 6: Run chat route tests**

Run:

```bash
cd /Users/Zhuanz/github.com/llm-memory-chat/backend
.venv/bin/python -m pytest tests/test_long_term_memory_service.py -q
```

Expected: pass after Task 6 service signatures are available.

- [ ] **Step 7: Commit**

```bash
cd /Users/Zhuanz/github.com/llm-memory-chat/backend
git add app/schemas.py app/routers/chat.py tests/test_long_term_memory_service.py
git commit -m "feat: route chats through project context"
```

---

### Task 6: Backend Memory Context Layering

**Files:**

- Modify: `backend/app/services/memory_service.py`
- Modify: `backend/tests/test_long_term_memory_service.py`
- Modify if Task 5 not yet updated: `backend/app/routers/chat.py`

- [ ] **Step 1: Add failing memory context layering tests**

In `backend/tests/test_long_term_memory_service.py`, add service tests.

```python
def test_ordinary_chat_injects_global_memories_only(self) -> None:
    db = self.SessionLocal()
    try:
        user = User(email="ordinary-context@example.com", password_hash="hash")
        project = Project(user=user, name="Scoped")
        ordinary = Conversation(user=user, title="ordinary")
        project_conversation = Conversation(user=user, project=project, title="project")
        db.add_all([user, project, ordinary, project_conversation])
        db.commit()
        db.refresh(user)
        db.refresh(project)
        db.refresh(ordinary)

        db.add(Memory(user_id=user.id, content="用户喜欢中文回答", kind="preference", scope="global"))
        db.add(
            Memory(
                user_id=user.id,
                project_id=project.id,
                content="本项目使用 TypeScript",
                kind="tech_stack",
                scope="project",
            )
        )
        db.add(Message(conversation_id=ordinary.id, role="user", content="hello"))
        db.commit()

        context = memory_service.get_chat_context_messages(db, user.id, ordinary.id)

        self.assertIn("用户喜欢中文回答", context[0]["content"])
        self.assertNotIn("TypeScript", context[0]["content"])
    finally:
        db.close()
```

```python
def test_project_chat_injects_global_and_same_project_memories(self) -> None:
    db = self.SessionLocal()
    try:
        user = User(email="project-context@example.com", password_hash="hash")
        current_project = Project(user=user, name="Current")
        other_project = Project(user=user, name="Other")
        conversation = Conversation(user=user, project=current_project, title="project")
        db.add_all([user, current_project, other_project, conversation])
        db.commit()
        db.refresh(user)
        db.refresh(current_project)
        db.refresh(other_project)
        db.refresh(conversation)

        db.add(Memory(user_id=user.id, content="用户喜欢简洁回答", kind="preference", scope="global"))
        db.add(
            Memory(
                user_id=user.id,
                project_id=current_project.id,
                content="当前项目使用 TypeScript",
                kind="tech_stack",
                scope="project",
            )
        )
        db.add(
            Memory(
                user_id=user.id,
                project_id=other_project.id,
                content="其他项目使用 Python",
                kind="tech_stack",
                scope="project",
            )
        )
        db.add(Message(conversation_id=conversation.id, role="user", content="hello"))
        db.commit()

        context = memory_service.get_chat_context_messages(
            db,
            user.id,
            conversation.id,
            project_id=current_project.id,
        )

        self.assertIn("全局记忆", context[0]["content"])
        self.assertIn("项目记忆优先", context[0]["content"])
        self.assertIn("用户喜欢简洁回答", context[0]["content"])
        self.assertIn("当前项目使用 TypeScript", context[0]["content"])
        self.assertNotIn("其他项目使用 Python", context[0]["content"])
    finally:
        db.close()
```

Add imports:

```python
from app.models import Conversation, Memory, Message, Project, User
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
cd /Users/Zhuanz/github.com/llm-memory-chat/backend
.venv/bin/python -m pytest tests/test_long_term_memory_service.py -q
```

Expected: fail because memory service still injects every enabled memory.

- [ ] **Step 3: Update explicit memory storage scope**

Change signature:

```python
def maybe_store_explicit_memory(
    db: Session,
    user_id: str,
    message: Message,
    project_id: str | None = None,
) -> Memory | None:
```

Add conservative scope selection:

```python
kind = _classify_memory(content)
scope = "project" if project_id and kind in {"project", "fact", "tool"} else "global"
memory = Memory(
    user_id=user_id,
    project_id=project_id if scope == "project" else None,
    scope=scope,
    content=content,
    kind="project_overview" if kind == "project" and scope == "project" else kind,
    source_message_id=message.id,
)
```

Keep ordinary chat conservative: if `project_id is None`, no project facts become project memory.

- [ ] **Step 4: Rewrite context memory queries**

Replace `get_enabled_memories_for_context` with a scoped version:

```python
def get_enabled_memories_for_context(
    db: Session,
    user_id: str,
    project_id: str | None = None,
    limit: int = MAX_MEMORY_CONTEXT_ITEMS,
) -> list[Memory]:
    stmt = (
        select(Memory)
        .where(
            Memory.user_id == user_id,
            Memory.enabled.is_(True),
            Memory.status == "active",
        )
        .order_by(Memory.last_used_at.desc().nullslast(), Memory.updated_at.desc())
        .limit(limit)
    )

    if project_id is None:
        stmt = stmt.where(Memory.scope == "global", Memory.project_id.is_(None))
    else:
        stmt = stmt.where(
            (Memory.scope == "global") | (Memory.project_id == project_id)
        )

    return list(db.execute(stmt).scalars().all())
```

If SQLAlchemy complains about Python `|`, import `or_` and use:

```python
from sqlalchemy import or_

stmt = stmt.where(or_(Memory.scope == "global", Memory.project_id == project_id))
```

- [ ] **Step 5: Format layered context**

Replace `get_long_term_memory_context` with a project-aware version:

```python
def get_long_term_memory_context(
    db: Session,
    user_id: str,
    project_id: str | None = None,
) -> dict[str, str] | None:
    memories = get_enabled_memories_for_context(db, user_id, project_id=project_id)
    if not memories:
        return None

    global_lines = [f"- {memory.content}" for memory in memories if memory.scope == "global"]
    project_lines = [f"- {memory.content}" for memory in memories if memory.scope == "project"]
    sections: list[str] = []

    if global_lines:
        sections.append("全局记忆：\n" + "\n".join(global_lines))
    if project_lines:
        sections.append(
            "当前项目记忆（当它与全局记忆冲突时，项目记忆优先）：\n"
            + "\n".join(project_lines)
        )

    return {
        "role": "system",
        "content": "以下是长期记忆。仅在与当前问题相关时使用。\n" + "\n\n".join(sections),
    }
```

Update `get_chat_context_messages`:

```python
def get_chat_context_messages(
    db: Session,
    user_id: str,
    conversation_id: str,
    current_model: str | None = None,
    project_id: str | None = None,
) -> list[dict[str, object]]:
    context: list[dict[str, object]] = []
    long_term_context = get_long_term_memory_context(db, user_id, project_id=project_id)
    if long_term_context:
        context.append(long_term_context)
    context.extend(get_context_messages(db, conversation_id, current_model=current_model))
    return context
```

- [ ] **Step 6: Run memory service tests**

Run:

```bash
cd /Users/Zhuanz/github.com/llm-memory-chat/backend
.venv/bin/python -m pytest tests/test_long_term_memory_service.py tests/test_memory_service.py -q
```

Expected: pass.

- [ ] **Step 7: Run backend regression tests**

Run:

```bash
cd /Users/Zhuanz/github.com/llm-memory-chat/backend
.venv/bin/python -m pytest -q
```

Expected: pass.

- [ ] **Step 8: Commit**

```bash
cd /Users/Zhuanz/github.com/llm-memory-chat/backend
git add app/services/memory_service.py app/routers/chat.py tests/test_long_term_memory_service.py
git commit -m "feat: layer global and project memories"
```

---

### Task 7: Frontend Types And API Foundation

**Files:**

- Modify: `fronted/src/types.ts`
- Modify: `fronted/src/services/api.ts`

- [ ] **Step 1: Add project and scoped memory types**

In `fronted/src/types.ts`, add:

```ts
export interface Project {
  id: string;
  name: string;
  description?: string | null;
  default_model?: string | null;
  default_reasoning_level?: ReasoningLevel | null;
  is_default: boolean;
  archived_at?: string | null;
  created_at: string;
  updated_at: string;
}
```

Extend `Conversation`:

```ts
export interface Conversation {
  id: string;
  title: string;
  pinned: boolean;
  project_id?: string | null;
  created_at: string;
  updated_at: string;
}
```

Extend `Memory`:

```ts
export interface Memory {
  id: string;
  content: string;
  kind: string;
  scope?: 'global' | 'project';
  project_id?: string | null;
  status?: 'active' | 'archived';
  importance?: number;
  enabled: boolean;
  created_at: string;
  updated_at: string;
  archived_at?: string | null;
  last_used_at?: string | null;
  superseded_by_id?: string | null;
}
```

- [ ] **Step 2: Add project APIs**

In `fronted/src/services/api.ts`, import `Project`, then add:

```ts
export async function fetchProjects(includeArchived = false): Promise<Project[]> {
  const query = includeArchived ? '?include_archived=true' : '';
  const res = await apiFetch(`${API_BASE}/projects${query}`);
  if (!res.ok) {
    const errorMessage = await getErrorMessage(res, 'Failed to fetch projects');
    throw new Error(errorMessage);
  }
  return res.json();
}

export async function createProject(input: {
  name: string;
  description?: string | null;
  default_model?: string | null;
  default_reasoning_level?: ReasoningLevel | null;
}): Promise<Project> {
  const res = await apiFetch(`${API_BASE}/projects`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  });
  if (!res.ok) {
    const errorMessage = await getErrorMessage(res, 'Failed to create project');
    throw new Error(errorMessage);
  }
  return res.json();
}

export async function updateProject(
  projectId: string,
  updates: {
    name?: string;
    description?: string | null;
    default_model?: string | null;
    default_reasoning_level?: ReasoningLevel | null;
    archived?: boolean;
  }
): Promise<Project> {
  const res = await apiFetch(`${API_BASE}/projects/${projectId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(updates),
  });
  if (!res.ok) {
    const errorMessage = await getErrorMessage(res, 'Failed to update project');
    throw new Error(errorMessage);
  }
  return res.json();
}
```

- [ ] **Step 3: Add scoped memory APIs**

Replace current `fetchMemories` and `createMemory` signatures with backward-compatible object forms:

```ts
export async function fetchMemories(options: {
  scope?: 'global' | 'project';
  projectId?: string | null;
  includeArchived?: boolean;
} = {}): Promise<Memory[]> {
  const params = new URLSearchParams();
  if (options.scope) params.set('scope', options.scope);
  if (options.projectId) params.set('project_id', options.projectId);
  if (options.includeArchived) params.set('include_archived', 'true');
  const query = params.toString() ? `?${params.toString()}` : '';

  const res = await apiFetch(`${API_BASE}/memories${query}`);
  if (!res.ok) {
    const errorMessage = await getErrorMessage(res, 'Failed to fetch memories');
    throw new Error(errorMessage);
  }
  return res.json();
}

export async function createMemory(input: {
  content: string;
  kind?: string;
  scope?: 'global' | 'project';
  projectId?: string | null;
}): Promise<Memory> {
  const res = await apiFetch(`${API_BASE}/memories`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      content: input.content,
      kind: input.kind ?? 'fact',
      scope: input.scope ?? 'global',
      project_id: input.projectId ?? null,
    }),
  });
  if (!res.ok) {
    const errorMessage = await getErrorMessage(res, 'Failed to create memory');
    throw new Error(errorMessage);
  }
  return res.json();
}
```

Extend `updateMemory` updates:

```ts
updates: { content?: string; kind?: string; enabled?: boolean; status?: 'active' | 'archived' }
```

- [ ] **Step 4: Add project_id to sendMessage**

Update signature:

```ts
export async function sendMessage(
  message: string,
  attachments: File[],
  conversationId: string | null,
  projectId: string | null,
  model: string | null,
  reasoningLevel: ReasoningLevel,
  onChunk: (content: string) => void,
  onConversationId: (id: string) => void,
  onError: (error: string) => void,
  signal?: AbortSignal
): Promise<void> {
```

Append form data:

```ts
if (projectId) {
  formData.append('project_id', projectId);
}
```

- [ ] **Step 5: Run frontend type/build checks**

Run:

```bash
cd /Users/Zhuanz/github.com/llm-memory-chat/fronted
npm run build
```

Expected: fail until App call sites are updated in Task 8, or pass if call sites are adjusted in this task.

- [ ] **Step 6: Commit after call sites compile**

After Task 8 updates call sites:

```bash
cd /Users/Zhuanz/github.com/llm-memory-chat/fronted
git add src/types.ts src/services/api.ts
git commit -m "feat: add project workspace API client"
```

---

### Task 8: Frontend App Project State And Chat Context

**Files:**

- Modify: `fronted/src/App.tsx`
- Modify: `fronted/src/services/api.ts`

- [ ] **Step 1: Add project and memory state**

In `fronted/src/App.tsx`, import `Project`. Add state near conversations:

```tsx
const [projects, setProjects] = useState<Project[]>([]);
const [draftProjectId, setDraftProjectId] = useState<string | null>(null);
const [globalMemories, setGlobalMemories] = useState<Memory[]>([]);
const [projectMemories, setProjectMemories] = useState<Memory[]>([]);
```

Remove the existing single `memories` state after adding `globalMemories` and `projectMemories`.

Compute active project:

```tsx
const activeConversation = useMemo(
  () => conversations.find((conversation) => conversation.id === activeConvId) ?? null,
  [activeConvId, conversations]
);
const activeProjectId = activeConversation?.project_id ?? draftProjectId;
const activeProject = useMemo(
  () => projects.find((project) => project.id === activeProjectId) ?? null,
  [activeProjectId, projects]
);
```

- [ ] **Step 2: Fetch projects with conversations**

When `currentUser` changes, fetch both:

```tsx
Promise.all([api.fetchConversations(), api.fetchProjects()])
  .then(([conversationData, projectData]) => {
    setConversations(conversationData);
    setProjects(projectData);
    setErrorMessage('');
  })
  .catch((err: Error) => {
    console.error(err);
    setErrorMessage(err.message);
  });
```

- [ ] **Step 3: Add new chat handlers**

Preserve ordinary chat:

```tsx
const handleNewChat = useCallback(() => {
  setActiveConvId(null);
  setDraftProjectId(null);
  setMessages([]);
  setStreamingContent('');
  setErrorMessage('');
}, []);
```

Add project chat:

```tsx
const handleNewProjectChat = useCallback((projectId: string) => {
  setActiveConvId(null);
  setDraftProjectId(projectId);
  setMessages([]);
  setStreamingContent('');
  setErrorMessage('');
}, []);
```

When selecting an existing conversation:

```tsx
setDraftProjectId(null);
```

- [ ] **Step 4: Pass project context to sendMessage**

Update `handleSend` call:

```tsx
await api.sendMessage(
  text,
  files,
  activeConvId,
  activeProjectId ?? null,
  selectedModel,
  reasoningLevel,
  handleChunk,
  handleConversationId,
  handleError,
  controller.signal
);
```

When `onConversationId` returns a new id, fetch conversations and clear `draftProjectId` only after the new conversation is in state.

- [ ] **Step 5: Load scoped memories**

Replace single memory fetch with:

```tsx
const loadMemories = useCallback(async () => {
  if (!activeUserId || !isSettingsOpenRef.current) return;

  const requestSeq = memoryRequestSeqRef.current + 1;
  memoryRequestSeqRef.current = requestSeq;
  setIsMemoriesLoading(true);

  try {
    const [nextGlobal, nextProject] = await Promise.all([
      api.fetchMemories({ scope: 'global' }),
      activeProjectId
        ? api.fetchMemories({ scope: 'project', projectId: activeProjectId })
        : Promise.resolve([]),
    ]);
    if (memoryRequestSeqRef.current !== requestSeq || currentUserIdRef.current !== activeUserId) {
      return;
    }
    setGlobalMemories(nextGlobal);
    setProjectMemories(nextProject);
  } catch (err) {
    const nextError = err instanceof Error ? err.message : 'Failed to fetch memories';
    setErrorMessage(nextError);
  } finally {
    if (memoryRequestSeqRef.current === requestSeq) {
      setIsMemoriesLoading(false);
    }
  }
}, [activeProjectId, activeUserId]);
```

- [ ] **Step 6: Add project CRUD handlers**

Add:

```tsx
const handleCreateProject = useCallback(async (name: string) => {
  const project = await api.createProject({ name });
  setProjects((prev) => [project, ...prev]);
  handleNewProjectChat(project.id);
}, [handleNewProjectChat]);

const handleUpdateProject = useCallback(async (projectId: string, updates: { name?: string; archived?: boolean }) => {
  const updated = await api.updateProject(projectId, updates);
  setProjects((prev) =>
    updates.archived
      ? prev.filter((project) => project.id !== projectId)
      : prev.map((project) => (project.id === projectId ? updated : project))
  );
  if (updates.archived && activeProjectId === projectId) {
    handleNewChat();
  }
}, [activeProjectId, handleNewChat]);
```

- [ ] **Step 7: Run build**

Run:

```bash
cd /Users/Zhuanz/github.com/llm-memory-chat/fronted
npm run build
```

Expected: pass after all call sites are updated.

- [ ] **Step 8: Commit**

```bash
cd /Users/Zhuanz/github.com/llm-memory-chat/fronted
git add src/App.tsx src/services/api.ts src/types.ts
git commit -m "feat: track project workspace state"
```

---

### Task 9: Frontend Sidebar Project Grouping

**Files:**

- Modify: `fronted/src/components/Sidebar.tsx`
- Create: `fronted/src/components/ProjectFormDialog.tsx`
- Optional create: `fronted/src/components/ProjectGroup.tsx`
- Modify: `fronted/src/App.css`
- Modify call site: `fronted/src/App.tsx`

- [ ] **Step 1: Extend Sidebar props**

In `Sidebar.tsx`, add props:

```tsx
projects: Project[];
activeProjectId: string | null;
onNewProject: (name: string) => void;
onNewProjectChat: (projectId: string) => void;
onRenameProject: (projectId: string, name: string) => void;
onArchiveProject: (projectId: string) => void;
```

Import `Project`.

- [ ] **Step 2: Group conversations**

Inside `Sidebar`, derive:

```tsx
const ordinaryConversations = filteredConversations.filter(
  (conversation) => !conversation.project_id
);

const conversationsByProject = useMemo(() => {
  const groups = new Map<string, Conversation[]>();
  for (const project of projects) {
    groups.set(project.id, []);
  }
  for (const conversation of filteredConversations) {
    if (!conversation.project_id) continue;
    groups.get(conversation.project_id)?.push(conversation);
  }
  return groups;
}, [filteredConversations, projects]);
```

Keep search as all-chat search; when searching, still show grouped results.

- [ ] **Step 3: Add project create dialog**

Create `ProjectFormDialog.tsx`:

```tsx
import { useState } from 'react';

interface ProjectFormDialogProps {
  title: string;
  initialName?: string;
  onSubmit: (name: string) => void;
  onClose: () => void;
}

export default function ProjectFormDialog({
  title,
  initialName = '',
  onSubmit,
  onClose,
}: ProjectFormDialogProps) {
  const [name, setName] = useState(initialName);
  const trimmed = name.trim();

  return (
    <div className="project-dialog-backdrop" role="presentation" onMouseDown={onClose}>
      <div
        className="project-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="project-dialog-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <h2 id="project-dialog-title">{title}</h2>
        <input
          value={name}
          autoFocus
          onChange={(event) => setName(event.target.value)}
          placeholder="Project name"
        />
        <div className="project-dialog-actions">
          <button type="button" onClick={onClose}>Cancel</button>
          <button type="button" onClick={() => onSubmit(trimmed)} disabled={!trimmed}>
            Save
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Render ordinary and project groups**

Replace the old primary/recent-only structure with:

```tsx
<div className="shell-section-label">普通聊天</div>
<ConversationList
  conversations={ordinaryConversations}
  activeId={activeId}
  openConversationMenuId={openConversationMenuId}
  editingConversationId={editingConversationId}
  editingTitle={editingTitle}
  onSelect={onSelect}
  onToggleMenu={(id) => setOpenConversationMenuId((prev) => (prev === id ? null : id))}
  onRename={handleConversationRename}
  onTogglePin={handleConversationPinToggle}
  onDelete={handleConversationDelete}
  onEditingTitleChange={setEditingTitle}
  onEditingSubmit={handleRenameSubmit}
  onEditingCancel={handleRenameCancel}
/>

<div className="shell-section-head shell-section-head--projects">
  <span>Projects</span>
  <button type="button" className="shell-project-add" onClick={() => setIsProjectDialogOpen(true)}>
    +
  </button>
</div>

{projects.map((project) => (
  <ProjectGroup
    key={project.id}
    project={project}
    conversations={conversationsByProject.get(project.id) ?? []}
    activeId={activeId}
    activeProjectId={activeProjectId}
    onNewChat={() => onNewProjectChat(project.id)}
    onRenameProject={onRenameProject}
    onArchiveProject={onArchiveProject}
    openConversationMenuId={openConversationMenuId}
    editingConversationId={editingConversationId}
    editingTitle={editingTitle}
    onSelect={onSelect}
    onToggleMenu={(id) => setOpenConversationMenuId((prev) => (prev === id ? null : id))}
    onRename={handleConversationRename}
    onTogglePin={handleConversationPinToggle}
    onDelete={handleConversationDelete}
    onEditingTitleChange={setEditingTitle}
    onEditingSubmit={handleRenameSubmit}
    onEditingCancel={handleRenameCancel}
  />
))}
```

Create `ProjectGroup.tsx` with props that exactly match the values above and render a project header plus the existing `ConversationList` for its `conversations`.

- [ ] **Step 5: Update App call site**

In `App.tsx`, pass the new props:

```tsx
<Sidebar
  conversations={conversations}
  activeId={activeConvId}
  onSelect={handleSelectConversation}
  onNew={handleNewChat}
  onDelete={handleDeleteConversation}
  onRename={handleRenameConversation}
  onTogglePin={handleTogglePinConversation}
  onClearAll={handleClearAllConversations}
  onOpenSettings={() => {
    setIsMobileSidebarOpen(false);
    setIsSettingsOpen(true);
  }}
  onLogout={handleLogout}
  currentUser={currentUser}
  isMobileOpen={isMobileSidebarOpen}
  onCloseMobile={() => setIsMobileSidebarOpen(false)}
  isCollapsed={isSidebarCollapsed}
  onToggleCollapsed={() => setIsSidebarCollapsed((prev) => !prev)}
  isClearingAll={isClearingConversations}
  projects={projects}
  activeProjectId={activeProjectId ?? null}
  onNewProject={handleCreateProject}
  onNewProjectChat={handleNewProjectChat}
  onRenameProject={(projectId, name) => handleUpdateProject(projectId, { name })}
  onArchiveProject={(projectId) => handleUpdateProject(projectId, { archived: true })}
/>
```

- [ ] **Step 6: Add CSS**

In `App.css`, add restrained styles using existing naming:

```css
.shell-project-add,
.shell-project-action {
  border: 0;
  background: transparent;
  color: inherit;
  cursor: pointer;
}

.shell-project-group {
  display: grid;
  gap: 4px;
}

.shell-project-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 32px;
}

.shell-project-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.project-dialog-backdrop {
  position: fixed;
  inset: 0;
  display: grid;
  place-items: center;
  background: rgba(0, 0, 0, 0.28);
  z-index: 50;
}

.project-dialog {
  width: min(360px, calc(100vw - 32px));
  border-radius: 8px;
  background: var(--surface, #fff);
  padding: 16px;
}
```

Adjust tokens to match actual CSS variables after reading nearby styles.

- [ ] **Step 7: Run frontend checks**

Run:

```bash
cd /Users/Zhuanz/github.com/llm-memory-chat/fronted
npm run lint
npm run build
```

Expected: pass.

- [ ] **Step 8: Commit**

```bash
cd /Users/Zhuanz/github.com/llm-memory-chat/fronted
git add src/App.tsx src/components/Sidebar.tsx src/components/ProjectFormDialog.tsx src/components/ProjectGroup.tsx src/App.css
git commit -m "feat: group chats by project"
```

---

### Task 10: Frontend Split Memory Management

**Files:**

- Modify: `fronted/src/components/SettingsDrawer.tsx`
- Modify: `fronted/src/components/MemorySettingsSection.tsx`
- Modify: `fronted/src/App.tsx`
- Modify: `fronted/src/App.css`

- [ ] **Step 1: Split memory props**

In `SettingsDrawer.tsx`, replace single memory props with:

```tsx
globalMemories: Memory[];
projectMemories: Memory[];
activeProjectName: string | null;
globalMemoryDraft: string;
projectMemoryDraft: string;
onGlobalMemoryDraftChange: (value: string) => void;
onProjectMemoryDraftChange: (value: string) => void;
onCreateGlobalMemory: () => void;
onCreateProjectMemory: () => void;
```

- [ ] **Step 2: Make MemorySettingsSection reusable by scope**

In `MemorySettingsSection.tsx`, add props:

```tsx
title: string;
subtitle?: string;
emptyText: string;
createPlaceholder: string;
canCreate: boolean;
```

Render `title` instead of hard-coded `长期记忆`, and use `createPlaceholder`.

When `canCreate` is false, hide the create row and show the empty/ordinary-chat note.

- [ ] **Step 3: Add App memory drafts and scoped create handlers**

In `App.tsx`, replace `memoryDraft` with:

```tsx
const [globalMemoryDraft, setGlobalMemoryDraft] = useState('');
const [projectMemoryDraft, setProjectMemoryDraft] = useState('');
```

Create global memory:

```tsx
const handleCreateGlobalMemory = useCallback(async () => {
  const content = globalMemoryDraft.trim();
  if (!content || !activeUserId || isMemoryMutating) return;
  setIsMemoryMutating(true);
  try {
    const memory = await api.createMemory({ content, scope: 'global' });
    setGlobalMemories((prev) => [memory, ...prev]);
    setGlobalMemoryDraft('');
  } catch (err) {
    setErrorMessage(err instanceof Error ? err.message : 'Failed to create memory');
  } finally {
    setIsMemoryMutating(false);
  }
}, [activeUserId, globalMemoryDraft, isMemoryMutating]);
```

Create project memory:

```tsx
const handleCreateProjectMemory = useCallback(async () => {
  const content = projectMemoryDraft.trim();
  if (!content || !activeUserId || !activeProjectId || isMemoryMutating) return;
  setIsMemoryMutating(true);
  try {
    const memory = await api.createMemory({
      content,
      scope: 'project',
      projectId: activeProjectId,
    });
    setProjectMemories((prev) => [memory, ...prev]);
    setProjectMemoryDraft('');
  } catch (err) {
    setErrorMessage(err instanceof Error ? err.message : 'Failed to create memory');
  } finally {
    setIsMemoryMutating(false);
  }
}, [activeProjectId, activeUserId, isMemoryMutating, projectMemoryDraft]);
```

Add a helper so toggle/delete update the correct list by memory scope:

```tsx
const replaceMemoryInScope = useCallback((memory: Memory) => {
  if (memory.scope === 'project' || memory.project_id) {
    setProjectMemories((prev) => prev.map((item) => (item.id === memory.id ? memory : item)));
    return;
  }
  setGlobalMemories((prev) => prev.map((item) => (item.id === memory.id ? memory : item)));
}, []);

const removeMemoryFromScope = useCallback((memory: Memory) => {
  if (memory.scope === 'project' || memory.project_id) {
    setProjectMemories((prev) => prev.filter((item) => item.id !== memory.id));
    return;
  }
  setGlobalMemories((prev) => prev.filter((item) => item.id !== memory.id));
}, []);
```

Use `replaceMemoryInScope(updatedMemory)` in `handleToggleMemory` and `removeMemoryFromScope(memory)` in `handleDeleteMemory`.

- [ ] **Step 4: Render split sections**

In `SettingsDrawer.tsx`:

```tsx
<MemorySettingsSection
  title="全局记忆"
  subtitle="跨所有普通聊天和项目生效，只适合稳定偏好。"
  memories={globalMemories}
  draft={globalMemoryDraft}
  isLoading={isMemoriesLoading}
  isMutating={isMemoryMutating}
  createPlaceholder="添加稳定的全局偏好"
  emptyText="还没有全局记忆。"
  canCreate
  onDraftChange={onGlobalMemoryDraftChange}
  onCreate={onCreateGlobalMemory}
  onToggle={onToggleMemory}
  onDelete={onDeleteMemory}
/>

<MemorySettingsSection
  title={activeProjectName ? `当前项目记忆：${activeProjectName}` : '当前项目记忆'}
  subtitle={activeProjectName ? '只在当前项目聊天中生效。' : '普通聊天没有项目记忆。'}
  memories={projectMemories}
  draft={projectMemoryDraft}
  isLoading={isMemoriesLoading}
  isMutating={isMemoryMutating}
  createPlaceholder="添加当前项目记忆"
  emptyText={activeProjectName ? '这个项目还没有记忆。' : '打开或新建项目聊天后，可以管理项目记忆。'}
  canCreate={Boolean(activeProjectName)}
  onDraftChange={onProjectMemoryDraftChange}
  onCreate={onCreateProjectMemory}
  onToggle={onToggleMemory}
  onDelete={onDeleteMemory}
/>
```

- [ ] **Step 5: Run frontend checks**

Run:

```bash
cd /Users/Zhuanz/github.com/llm-memory-chat/fronted
npm run lint
npm run build
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
cd /Users/Zhuanz/github.com/llm-memory-chat/fronted
git add src/App.tsx src/components/SettingsDrawer.tsx src/components/MemorySettingsSection.tsx src/App.css
git commit -m "feat: split global and project memories"
```

---

### Task 11: Full Verification And Manual QA

**Files:**

- No planned source edits unless verification finds bugs.

- [ ] **Step 1: Run backend full test suite**

Run:

```bash
cd /Users/Zhuanz/github.com/llm-memory-chat/backend
.venv/bin/python -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 2: Run frontend lint and build**

Run:

```bash
cd /Users/Zhuanz/github.com/llm-memory-chat/fronted
npm run lint
npm run build
```

Expected: both pass.

- [ ] **Step 3: Run local dev servers**

Use existing project startup commands. If the backend uses `run.py`, run:

```bash
cd /Users/Zhuanz/github.com/llm-memory-chat/backend
.venv/bin/python run.py
```

In another terminal:

```bash
cd /Users/Zhuanz/github.com/llm-memory-chat/fronted
npm run dev
```

Expected: backend starts on its configured port and Vite prints a local URL.

- [ ] **Step 4: Manual QA checklist**

Verify in browser:

- Register or log in.
- Ordinary chat can be created without a project.
- Project can be created.
- Project chat can be created from the project group.
- Sidebar still shows all chats, with ordinary chats and project chats grouped.
- Selecting ordinary chat sends `/api/chat` without `project_id`.
- Selecting project chat sends `/api/chat` with matching `project_id` for new project chats.
- Existing project conversation rejects mismatched `project_id` at the API level.
- Settings in ordinary chat shows global memory only.
- Settings in project chat shows global memory and current project memory.
- Project memory does not appear in ordinary chat context.
- Other-project memory does not appear in current project context.

- [ ] **Step 5: Inspect git status in both publishable repos**

Run:

```bash
cd /Users/Zhuanz/github.com/llm-memory-chat/backend
git status --short
```

Run:

```bash
cd /Users/Zhuanz/github.com/llm-memory-chat/fronted
git status --short
```

Expected: only intentional changes remain. Existing unrelated untracked docs may still appear in backend if they were present before this work.

- [ ] **Step 6: Final review with subagents**

Dispatch one reviewer subagent for backend and one for frontend:

- Backend reviewer scope: data ownership, project/memory isolation, chat conflict handling, migration risk.
- Frontend reviewer scope: project chat state, ordinary chat preservation, memory scope UI, no hidden chats.

Fix only actionable issues that violate the spec or break verification.
