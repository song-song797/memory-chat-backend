from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_model_label, settings
from ..models import Conversation, Message


def store_message(
    db: Session,
    conversation_id: str,
    role: str,
    content: str,
    model: str | None = None,
) -> Message:
    """Persist a message and update conversation timestamp."""
    msg = Message(conversation_id=conversation_id, role=role, content=content, model=model)
    db.add(msg)

    # Update conversation's updated_at
    conv = db.get(Conversation, conversation_id)
    if conv:
        from datetime import datetime, timezone
        conv.updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(msg)
    return msg


def _format_context_message(message: Message, current_model: str | None) -> dict[str, str]:
    if message.role != "assistant":
        return {"role": message.role, "content": message.content}

    if message.model and message.model == current_model:
        return {"role": "assistant", "content": message.content}

    historical_model_label = get_model_label(message.model)
    return {
        "role": "system",
        "content": (
            f"以下是历史对话中另一模型的回答记录（模型：{historical_model_label}）。"
            "这些内容仅供上下文参考，不代表你自己的身份、经历或上一轮回答：\n"
            f"{message.content}"
        ),
    }


def get_context_messages(
    db: Session,
    conversation_id: str,
    current_model: str | None = None,
) -> list[dict[str, str]]:
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

    return [_format_context_message(message, current_model) for message in messages]


def get_conversation_messages(db: Session, conversation_id: str) -> list[Message]:
    """Get all messages for a conversation, ordered by time."""
    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
    )
    return list(db.execute(stmt).scalars().all())
