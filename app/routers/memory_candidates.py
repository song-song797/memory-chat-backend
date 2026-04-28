from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Conversation, MemoryCandidate, User
from ..schemas import MemoryCandidateAccept, MemoryCandidateOut, MemoryCandidateReviewOut
from ..services import memory_candidate_service, memory_document_service, memory_service
from ..services.auth_service import get_current_user
from ..services.project_service import get_user_project

router = APIRouter(prefix="/api/memory-candidates", tags=["memory-candidates"])


def _get_user_conversation(db: Session, user_id: str, conversation_id: str) -> Conversation:
    conversation = db.get(Conversation, conversation_id)
    if not conversation or conversation.user_id != user_id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


def _raise_candidate_error(error: ValueError) -> None:
    detail = str(error)
    if "not found" in detail:
        raise HTTPException(status_code=404, detail=detail) from error
    raise HTTPException(status_code=400, detail=detail) from error


def _validate_scope(scope: str) -> str:
    if scope not in memory_service.VALID_MEMORY_SCOPES:
        raise HTTPException(status_code=400, detail="Invalid memory scope")
    return scope


def _validate_status(status: str) -> str:
    if status not in {"pending", "accepted", "dismissed"}:
        raise HTTPException(status_code=400, detail="Invalid memory candidate status")
    return status


def _validate_surface(surface: str) -> str:
    if surface not in memory_candidate_service.VALID_CANDIDATE_SURFACES:
        raise HTTPException(status_code=400, detail="Invalid memory candidate surface")
    return surface


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


@router.get("", response_model=list[MemoryCandidateOut])
def list_memory_candidates(
    status: str | None = None,
    surface: str | None = None,
    scope: str | None = None,
    project_id: str | None = None,
    conversation_id: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(MemoryCandidate).where(MemoryCandidate.user_id == current_user.id)
    conversation = None
    if status is not None:
        stmt = stmt.where(MemoryCandidate.status == _validate_status(status))
    if surface is not None:
        stmt = stmt.where(MemoryCandidate.surface == _validate_surface(surface))
    if scope is not None:
        stmt = stmt.where(MemoryCandidate.scope == _validate_scope(scope))
    if project_id is not None:
        get_user_project(db, current_user.id, project_id)
        stmt = stmt.where(MemoryCandidate.project_id == project_id)
    if conversation_id is not None:
        conversation = _get_user_conversation(db, current_user.id, conversation_id)
        try:
            memory_service.validate_conversation_project(project_id, conversation.project_id)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        stmt = stmt.where(MemoryCandidate.conversation_id == conversation_id)
    stmt = stmt.order_by(MemoryCandidate.created_at.desc())
    return list(db.execute(stmt).scalars().all())


@router.post("/{candidate_id}/accept", response_model=MemoryCandidateReviewOut)
def accept_memory_candidate(
    candidate_id: str,
    body: MemoryCandidateAccept,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        candidate, memory, archived_memory_id = memory_candidate_service.accept_memory_candidate(
            db,
            current_user.id,
            candidate_id,
            content_override=body.content,
        )
    except ValueError as error:
        _raise_candidate_error(error)
    _schedule_memory_document_refresh(
        background_tasks,
        db,
        current_user.id,
        candidate.scope,
        candidate.project_id,
        candidate.conversation_id,
    )
    return {
        "candidate": candidate,
        "memory": memory,
        "archived_memory_id": archived_memory_id,
    }


@router.post("/{candidate_id}/dismiss", response_model=MemoryCandidateOut)
def dismiss_memory_candidate(
    candidate_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return memory_candidate_service.dismiss_memory_candidate(db, current_user.id, candidate_id)
    except ValueError as error:
        _raise_candidate_error(error)


@router.post("/{candidate_id}/defer", response_model=MemoryCandidateOut)
def defer_memory_candidate(
    candidate_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return memory_candidate_service.defer_memory_candidate(db, current_user.id, candidate_id)
    except ValueError as error:
        _raise_candidate_error(error)
