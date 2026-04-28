from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_memory_model, settings
from ..models import Memory
from . import llm_service


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _load_active_conversation_memories(
    db: Session,
    user_id: str,
    conversation_id: str,
) -> list[Memory]:
    stmt = (
        select(Memory)
        .where(
            Memory.user_id == user_id,
            Memory.scope == "conversation",
            Memory.conversation_id == conversation_id,
            Memory.enabled.is_(True),
            Memory.status == "active",
            Memory.archived_at.is_(None),
        )
        .order_by(Memory.updated_at.asc(), Memory.created_at.asc())
    )
    return list(db.execute(stmt).scalars().all())


def _should_compact(memories: list[Memory]) -> bool:
    threshold = settings.MEMORY_CONVERSATION_COMPACT_THRESHOLD
    max_chars = settings.MEMORY_CONVERSATION_COMPACT_MAX_CHARS
    too_many = threshold > 0 and len(memories) > threshold
    too_long = max_chars > 0 and sum(len(memory.content) for memory in memories) > max_chars
    return too_many or too_long


def _format_memories(memories: list[Memory]) -> str:
    lines = []
    for memory in memories:
        updated_at = memory.updated_at.isoformat() if memory.updated_at else ""
        lines.append(f"- kind={memory.kind}; updated_at={updated_at}; content={memory.content}")
    return "\n".join(lines)


def _fallback_summary(memories: list[Memory]) -> str:
    recent = memories[-8:]
    lines = [memory.content.strip() for memory in recent if memory.content.strip()]
    if not lines:
        return "当前会话暂无可压缩的有效记忆。"
    return "当前会话要点：\n" + "\n".join(f"- {line}" for line in lines)


async def _generate_compacted_summary(memories: list[Memory]) -> str:
    memory_model = get_memory_model()
    system_prompt = (
        "你是会话记忆压缩器。请把当前会话里的多条短期记忆压缩成一段简洁、可继续使用的会话状态。"
        "只输出压缩后的中文文本，不要解释，不要输出 JSON。"
        "保留当前任务、重要决策、用户在本会话中的明确要求、仍需继续处理的问题。"
        "删除闲聊、重复、过期或对后续回答帮助不大的内容。"
        "如果多条记忆冲突，以 updated_at 更新的内容为准。"
    )
    user_prompt = "当前会话记忆列表：\n" f"{_format_memories(memories)}"
    try:
        summary = await llm_service.create_chat_completion(
            messages=[{"role": "user", "content": user_prompt}],
            model=memory_model,
            system_prompt=system_prompt,
            max_tokens=1000,
        )
    except Exception:
        return _fallback_summary(memories)

    return summary.strip() or _fallback_summary(memories)


async def compact_conversation_memories(
    db: Session,
    user_id: str,
    conversation_id: str,
) -> bool:
    memories = _load_active_conversation_memories(db, user_id, conversation_id)
    if not memories or not _should_compact(memories):
        return False

    summary = await _generate_compacted_summary(memories)
    now = _utcnow()
    importance = max((memory.importance for memory in memories), default=0)
    for memory in memories:
        memory.status = "archived"
        memory.archived_at = now

    compacted = Memory(
        user_id=user_id,
        conversation_id=conversation_id,
        scope="conversation",
        content=summary,
        kind="decision",
        importance=importance,
    )
    db.add(compacted)
    db.commit()
    return True
