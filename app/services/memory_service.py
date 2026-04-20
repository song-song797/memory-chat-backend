from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Conversation, Message


def store_message(db: Session, conversation_id: str, role: str, content: str) -> Message:
    """Persist a message and update conversation timestamp."""
    msg = Message(conversation_id=conversation_id, role=role, content=content)
    db.add(msg)

    # Update conversation's updated_at
    conv = db.get(Conversation, conversation_id)
    if conv:
        from datetime import datetime, timezone
        conv.updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(msg)
    return msg


def get_context_messages(db: Session, conversation_id: str) -> list[dict[str, str]]:
    """Retrieve recent messages as LLM context.

    Returns the last N messages (configured by CONTEXT_WINDOW_SIZE)
    formatted as [{role, content}] dicts ready for the LLM API.
    """
    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc())
        .limit(settings.CONTEXT_WINDOW_SIZE)
    )
    messages = list(db.execute(stmt).scalars().all())
    messages.reverse()  # Oldest first

    return [{"role": m.role, "content": m.content} for m in messages]


def get_conversation_messages(db: Session, conversation_id: str) -> list[Message]:
    """Get all messages for a conversation, ordered by time."""
    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
    )
    return list(db.execute(stmt).scalars().all())
