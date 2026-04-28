from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Conversation, User
from ..schemas import MemoryDocumentOut
from ..services import memory_document_service
from ..services.auth_service import get_current_user
from ..services.project_service import get_user_project

router = APIRouter(prefix="/api/memory-documents", tags=["memory-documents"])


def _validate_scope(scope: str) -> str:
    if scope not in memory_document_service.VALID_MEMORY_SCOPES:
        raise HTTPException(status_code=400, detail="Invalid memory document scope")
    return scope


def _get_user_conversation(db: Session, user_id: str, conversation_id: str) -> Conversation:
    conversation = db.get(Conversation, conversation_id)
    if not conversation or conversation.user_id != user_id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


def _validate_scope_ownership(
    db: Session,
    user_id: str,
    scope: str | None,
    project_id: str | None,
    conversation_id: str | None,
) -> None:
    if project_id is not None:
        get_user_project(db, user_id, project_id)
    if conversation_id is not None:
        _get_user_conversation(db, user_id, conversation_id)
    if scope is not None:
        try:
            memory_document_service.validate_document_scope(scope, project_id, conversation_id)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("", response_model=list[MemoryDocumentOut])
def list_memory_documents(
    scope: str | None = None,
    project_id: str | None = None,
    conversation_id: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if scope is not None:
        scope = _validate_scope(scope)
    _validate_scope_ownership(db, current_user.id, scope, project_id, conversation_id)
    return memory_document_service.list_memory_documents(
        db,
        current_user.id,
        scope=scope,
        project_id=project_id,
        conversation_id=conversation_id,
    )
