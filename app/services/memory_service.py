import base64

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..config import get_model_label, settings
from ..models import Attachment, Conversation, Message
from .attachment_service import get_attachment_path


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


def _serialize_image_attachment(attachment: Attachment) -> dict[str, object] | None:
    path = get_attachment_path(attachment)
    if not path.exists():
        return None

    payload = base64.b64encode(path.read_bytes()).decode("ascii")
    return {
        "type": "image_url",
        "image_url": {"url": f"data:{attachment.mime_type};base64,{payload}"},
    }


def _build_user_content(message: Message) -> str | list[dict[str, object]]:
    attachments = list(message.attachments)
    if not attachments:
        return message.content

    text_segments: list[str] = []
    if message.content.strip():
        text_segments.append(message.content.strip())

    file_attachments = [attachment for attachment in attachments if attachment.kind != "image"]
    if file_attachments:
        file_lines = "\n".join(
            f"- {attachment.name} ({attachment.mime_type}, {attachment.size_bytes} bytes)"
            for attachment in file_attachments
        )
        text_segments.append(f"用户附带了这些文件：\n{file_lines}")

    if not text_segments:
        text_segments.append("用户发送了附件。")

    content_parts: list[dict[str, object]] = [
        {"type": "text", "text": "\n\n".join(text_segments)}
    ]

    for attachment in attachments:
        if attachment.kind != "image":
            continue

        image_part = _serialize_image_attachment(attachment)
        if image_part:
            content_parts.append(image_part)
        else:
            content_parts[0]["text"] += f"\n\n图片附件不可用：{attachment.name}"

    return content_parts


def _format_context_message(message: Message, current_model: str | None) -> dict[str, object]:
    if message.role != "assistant":
        return {"role": message.role, "content": _build_user_content(message)}

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
) -> list[dict[str, object]]:
    """Retrieve recent messages as LLM context.

    Returns the last N messages (configured by CONTEXT_WINDOW_SIZE)
    formatted as [{role, content}] dicts ready for the LLM API.
    """
    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .options(selectinload(Message.attachments))
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
        .options(selectinload(Message.attachments))
        .order_by(Message.created_at.asc())
    )
    return list(db.execute(stmt).scalars().all())
