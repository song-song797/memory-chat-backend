from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Conversation, Memory, User, _utcnow
from ..schemas import MemoryCreate, MemoryOut, MemoryUpdate
from ..services.auth_service import get_current_user
from ..services import memory_document_service, memory_service
from ..services.project_service import get_user_project

router = APIRouter(prefix="/api/memories", tags=["memories"])


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


def _get_user_conversation(db: Session, user_id: str, conversation_id: str) -> Conversation:
    conversation = db.get(Conversation, conversation_id)
    if not conversation or conversation.user_id != user_id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


def _validate_scope(scope: str) -> str:
    if scope not in memory_service.VALID_MEMORY_SCOPES:
        raise HTTPException(status_code=400, detail="Invalid memory scope")
    return scope


def _validate_status(status: str) -> str:
    if status not in memory_service.VALID_MEMORY_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid memory status")
    return status


def _validate_memory_scope(
    scope: str,
    project_id: str | None,
    conversation_id: str | None,
) -> None:
    try:
        memory_service.validate_memory_scope(scope, project_id, conversation_id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


def _validate_conversation_project(
    project_id: str | None,
    conversation: Conversation | None,
) -> None:
    if conversation is None:
        return
    try:
        memory_service.validate_conversation_project(project_id, conversation.project_id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


def _schedule_memory_document_refresh(
    background_tasks: BackgroundTasks,
    db: Session,
    user_id: str,
    scope: str,
    project_id: str | None,
    conversation_id: str | None,
) -> None:
    background_tasks.add_task(
        memory_document_service.rebuild_memory_document,
        db,
        user_id=user_id,
        scope=scope,
        project_id=project_id if scope == "project" else None,
        conversation_id=conversation_id if scope == "conversation" else None,
    )


@router.get("", response_model=list[MemoryOut])
def list_memories(
    scope: str | None = None,
    project_id: str | None = None,
    conversation_id: str | None = None,
    include_archived: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(Memory).where(Memory.user_id == current_user.id)
    conversation = None
    if scope is not None:
        scope = _validate_scope(scope)
        _validate_memory_scope(scope, project_id, conversation_id)
        stmt = stmt.where(Memory.scope == scope)
    if project_id is not None:
        get_user_project(db, current_user.id, project_id)
        stmt = stmt.where(Memory.project_id == project_id)
    if conversation_id is not None:
        conversation = _get_user_conversation(db, current_user.id, conversation_id)
        _validate_conversation_project(project_id, conversation)
        stmt = stmt.where(Memory.conversation_id == conversation_id)
    if not include_archived:
        stmt = stmt.where(Memory.archived_at.is_(None), Memory.status == "active")
    stmt = stmt.order_by(Memory.updated_at.desc())
    return list(db.execute(stmt).scalars().all())


@router.post("", response_model=MemoryOut, status_code=201)
def create_memory(
    body: MemoryCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    scope = _validate_scope(body.scope)
    status = _validate_status(body.status)
    _validate_memory_scope(scope, body.project_id, body.conversation_id)
    if body.project_id is not None:
        get_user_project(db, current_user.id, body.project_id)
    if body.conversation_id is not None:
        conversation = _get_user_conversation(db, current_user.id, body.conversation_id)
        _validate_conversation_project(body.project_id, conversation)
    if body.superseded_by_id is not None:
        _get_user_memory(db, current_user.id, body.superseded_by_id)

    memory = Memory(
        user_id=current_user.id,
        project_id=body.project_id,
        conversation_id=body.conversation_id,
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
    _schedule_memory_document_refresh(
        background_tasks,
        db,
        current_user.id,
        memory.scope,
        memory.project_id,
        memory.conversation_id,
    )
    return memory


@router.put("/{memory_id}", response_model=MemoryOut)
def update_memory(
    memory_id: str,
    body: MemoryUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    memory = _get_user_memory(db, current_user.id, memory_id)
    previous_scope = memory.scope
    previous_project_id = memory.project_id
    previous_conversation_id = memory.conversation_id
    submitted_fields = body.model_fields_set
    if not submitted_fields:
        raise HTTPException(status_code=400, detail="No memory changes provided")

    if "content" in submitted_fields:
        if body.content is None:
            raise HTTPException(status_code=400, detail="Memory content cannot be empty")
        memory.content = _trim_required(body.content, "content")
    if "kind" in submitted_fields:
        if body.kind is None:
            raise HTTPException(status_code=400, detail="Memory kind cannot be empty")
        memory.kind = _trim_required(body.kind, "kind")
    if "enabled" in submitted_fields:
        if body.enabled is None:
            raise HTTPException(status_code=400, detail="Memory enabled cannot be null")
        memory.enabled = body.enabled
    if "scope" in submitted_fields:
        if body.scope is None:
            raise HTTPException(status_code=400, detail="Invalid memory scope")
        memory.scope = _validate_scope(body.scope)
    if "project_id" in submitted_fields:
        memory.project_id = body.project_id
    if "conversation_id" in submitted_fields:
        memory.conversation_id = body.conversation_id
    if memory.project_id is not None:
        get_user_project(db, current_user.id, memory.project_id)
    conversation = None
    if memory.conversation_id is not None:
        conversation = _get_user_conversation(db, current_user.id, memory.conversation_id)
        _validate_conversation_project(memory.project_id, conversation)
    _validate_memory_scope(memory.scope, memory.project_id, memory.conversation_id)
    if "status" in submitted_fields:
        if body.status is None:
            raise HTTPException(status_code=400, detail="Invalid memory status")
        memory.status = _validate_status(body.status)
        memory.archived_at = _utcnow() if memory.status == "archived" else None
    if "importance" in submitted_fields:
        if body.importance is None:
            raise HTTPException(status_code=400, detail="Memory importance cannot be null")
        memory.importance = body.importance
    if "superseded_by_id" in submitted_fields:
        if body.superseded_by_id is not None:
            _get_user_memory(db, current_user.id, body.superseded_by_id)
        memory.superseded_by_id = body.superseded_by_id

    db.commit()
    db.refresh(memory)
    _schedule_memory_document_refresh(
        background_tasks,
        db,
        current_user.id,
        previous_scope,
        previous_project_id,
        previous_conversation_id,
    )
    if (
        previous_scope != memory.scope
        or previous_project_id != memory.project_id
        or previous_conversation_id != memory.conversation_id
    ):
        _schedule_memory_document_refresh(
            background_tasks,
            db,
            current_user.id,
            memory.scope,
            memory.project_id,
            memory.conversation_id,
        )
    return memory


@router.delete("/{memory_id}", status_code=204)
def delete_memory(
    memory_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    memory = _get_user_memory(db, current_user.id, memory_id)
    scope = memory.scope
    project_id = memory.project_id
    conversation_id = memory.conversation_id
    db.delete(memory)
    db.commit()
    _schedule_memory_document_refresh(
        background_tasks,
        db,
        current_user.id,
        scope,
        project_id,
        conversation_id,
    )
