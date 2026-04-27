from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Memory, User
from ..schemas import MemoryCreate, MemoryOut, MemoryUpdate
from ..services.auth_service import get_current_user

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
    memory = Memory(
        user_id=current_user.id,
        content=_trim_required(body.content, "content"),
        kind=_trim_required(body.kind, "kind"),
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
    if body.content is None and body.kind is None and body.enabled is None:
        raise HTTPException(status_code=400, detail="No memory changes provided")

    if body.content is not None:
        memory.content = _trim_required(body.content, "content")
    if body.kind is not None:
        memory.kind = _trim_required(body.kind, "kind")
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
