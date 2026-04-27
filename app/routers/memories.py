from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Memory, User, _utcnow
from ..schemas import MemoryCreate, MemoryOut, MemoryUpdate
from ..services.auth_service import get_current_user
from ..services.project_service import get_user_project

router = APIRouter(prefix="/api/memories", tags=["memories"])

VALID_MEMORY_SCOPES = {"global", "project"}
VALID_MEMORY_STATUSES = {"active", "archived"}


def _trim_required(value: str, field_name: str) -> str:
    trimmed = value.strip()
    if not trimmed:
        raise HTTPException(status_code=400, detail=f"Memory {field_name} cannot be empty")
    return trimmed


def _get_user_memory(db: Session, user_id: str, memory_id: str) -> Memory:
    memory = db.get(Memory, memory_id)
    if not memory or memory.user_id != user_id:
        raise HTTPException(status_code=404, detail="Memory not found")
    return memory


def _validate_scope(scope: str) -> str:
    if scope not in VALID_MEMORY_SCOPES:
        raise HTTPException(status_code=400, detail="Invalid memory scope")
    return scope


def _validate_status(status: str) -> str:
    if status not in VALID_MEMORY_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid memory status")
    return status


@router.get("", response_model=list[MemoryOut])
def list_memories(
    scope: str | None = None,
    project_id: str | None = None,
    include_archived: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(Memory).where(Memory.user_id == current_user.id)
    if scope is not None:
        stmt = stmt.where(Memory.scope == _validate_scope(scope))
    if project_id is not None:
        get_user_project(db, current_user.id, project_id)
        stmt = stmt.where(Memory.project_id == project_id)
    if not include_archived:
        stmt = stmt.where(Memory.archived_at.is_(None), Memory.status == "active")
    stmt = stmt.order_by(Memory.updated_at.desc())
    return list(db.execute(stmt).scalars().all())


@router.post("", response_model=MemoryOut, status_code=201)
def create_memory(
    body: MemoryCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    scope = _validate_scope(body.scope)
    status = _validate_status(body.status)
    if scope == "global" and body.project_id is not None:
        raise HTTPException(status_code=400, detail="Global memories cannot set project_id")
    if scope == "project":
        if body.project_id is None:
            raise HTTPException(status_code=400, detail="Project memories require project_id")
        get_user_project(db, current_user.id, body.project_id)
    if body.superseded_by_id is not None:
        _get_user_memory(db, current_user.id, body.superseded_by_id)

    memory = Memory(
        user_id=current_user.id,
        project_id=body.project_id,
        content=_trim_required(body.content, "content"),
        kind=_trim_required(body.kind, "kind"),
        scope=scope,
        status=status,
        importance=body.importance,
        superseded_by_id=body.superseded_by_id,
        archived_at=_utcnow() if status == "archived" else None,
    )
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
    if (
        body.content is None
        and body.kind is None
        and body.enabled is None
        and body.scope is None
        and body.project_id is None
        and body.status is None
        and body.importance is None
        and body.superseded_by_id is None
    ):
        raise HTTPException(status_code=400, detail="No memory changes provided")

    if body.content is not None:
        memory.content = _trim_required(body.content, "content")
    if body.kind is not None:
        memory.kind = _trim_required(body.kind, "kind")
    if body.enabled is not None:
        memory.enabled = body.enabled
    if body.scope is not None:
        memory.scope = _validate_scope(body.scope)
    if body.project_id is not None:
        get_user_project(db, current_user.id, body.project_id)
        memory.project_id = body.project_id
    if memory.scope == "global" and memory.project_id is not None:
        raise HTTPException(status_code=400, detail="Global memories cannot set project_id")
    if memory.scope == "project" and memory.project_id is None:
        raise HTTPException(status_code=400, detail="Project memories require project_id")
    if body.status is not None:
        memory.status = _validate_status(body.status)
        memory.archived_at = _utcnow() if memory.status == "archived" else None
    if body.importance is not None:
        memory.importance = body.importance
    if body.superseded_by_id is not None:
        _get_user_memory(db, current_user.id, body.superseded_by_id)
        memory.superseded_by_id = body.superseded_by_id

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
