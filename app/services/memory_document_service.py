import re
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_memory_model, settings
from ..database import SessionLocal
from ..models import Memory, MemoryDocument
from . import llm_service

VALID_MEMORY_SCOPES = {"global", "project", "conversation"}
KIND_LABELS = {
    "preference": "偏好",
    "project": "项目信息",
    "tool": "工具与技术栈",
    "decision": "已确认结论",
    "fact": "事实",
}
MAX_GENERATION_ERROR_LENGTH = 500


@dataclass(frozen=True)
class GeneratedMemoryDocument:
    content_md: str
    generated_by: str
    generation_model: str | None = None
    generation_error: str | None = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def validate_document_scope(
    scope: str,
    project_id: str | None,
    conversation_id: str | None,
) -> None:
    if scope not in VALID_MEMORY_SCOPES:
        raise ValueError("Invalid memory document scope")
    if scope == "global" and (project_id is not None or conversation_id is not None):
        raise ValueError("Global memory document cannot set project_id or conversation_id")
    if scope == "project" and (project_id is None or conversation_id is not None):
        raise ValueError("Project memory document requires project_id and cannot set conversation_id")
    if scope == "conversation" and conversation_id is None:
        raise ValueError("Conversation memory document requires conversation_id")


def _document_filters(scope: str, project_id: str | None, conversation_id: str | None):
    if scope == "global":
        return (MemoryDocument.project_id.is_(None), MemoryDocument.conversation_id.is_(None))
    if scope == "project":
        return (MemoryDocument.project_id == project_id, MemoryDocument.conversation_id.is_(None))
    return (MemoryDocument.conversation_id == conversation_id,)


def _memory_filters(scope: str, project_id: str | None, conversation_id: str | None):
    if scope == "global":
        return (Memory.project_id.is_(None), Memory.conversation_id.is_(None))
    if scope == "project":
        return (Memory.project_id == project_id,)
    return (Memory.conversation_id == conversation_id,)


def get_memory_document(
    db: Session,
    user_id: str,
    scope: str,
    project_id: str | None = None,
    conversation_id: str | None = None,
) -> MemoryDocument | None:
    validate_document_scope(scope, project_id, conversation_id)
    stmt = select(MemoryDocument).where(
        MemoryDocument.user_id == user_id,
        MemoryDocument.scope == scope,
        *_document_filters(scope, project_id, conversation_id),
    )
    return db.execute(stmt).scalars().first()


def list_memory_documents(
    db: Session,
    user_id: str,
    scope: str | None = None,
    project_id: str | None = None,
    conversation_id: str | None = None,
) -> list[MemoryDocument]:
    stmt = select(MemoryDocument).where(MemoryDocument.user_id == user_id)
    if scope is not None:
        validate_document_scope(scope, project_id, conversation_id)
        stmt = stmt.where(
            MemoryDocument.scope == scope,
            *_document_filters(scope, project_id, conversation_id),
        )
    elif project_id is not None:
        stmt = stmt.where(MemoryDocument.project_id == project_id)
    elif conversation_id is not None:
        stmt = stmt.where(MemoryDocument.conversation_id == conversation_id)
    stmt = stmt.order_by(MemoryDocument.updated_at.desc())
    return list(db.execute(stmt).scalars().all())


def _load_source_memories(
    db: Session,
    user_id: str,
    scope: str,
    project_id: str | None,
    conversation_id: str | None,
) -> list[Memory]:
    stmt = (
        select(Memory)
        .where(
            Memory.user_id == user_id,
            Memory.scope == scope,
            Memory.enabled.is_(True),
            Memory.status == "active",
            Memory.archived_at.is_(None),
            *_memory_filters(scope, project_id, conversation_id),
        )
        .order_by(Memory.updated_at.desc(), Memory.created_at.desc())
    )
    return list(db.execute(stmt).scalars().all())


def _document_title(scope: str) -> str:
    if scope == "project":
        return "项目记忆"
    if scope == "conversation":
        return "会话记忆"
    return "全局记忆"


def _format_source_memories(memories: list[Memory]) -> str:
    if not memories:
        return "无已确认记忆"
    lines = []
    for memory in memories:
        updated_at = memory.updated_at.isoformat() if memory.updated_at else ""
        lines.append(
            f"- id={memory.id}; kind={memory.kind}; updated_at={updated_at}; content={memory.content}"
        )
    return "\n".join(lines)


def _normalize_memory_text(content: str) -> str:
    text = re.sub(r"\s+", "", content.strip().lower())
    text = re.sub(r"^[\-*•]+", "", text)
    text = text.strip(" ，。,.；;：:！!？?")
    text = re.sub(r"^(用户|我)", "", text)
    if len(text) > 2 and text.endswith("了"):
        text = text[:-1]
    return text


def _preference_topic_key(content: str) -> str | None:
    text = _normalize_memory_text(content)
    for marker in ("不喜欢", "喜欢", "偏好", "习惯"):
        if marker in text:
            topic = text.split(marker, 1)[1].strip(" ，。,.；;：:！!？?")
            if len(topic) > 1:
                return f"preference:{marker.lstrip('不')}:{topic}"
    return None


def _memory_document_key(memory: Memory) -> str:
    if (memory.kind or "") == "preference":
        preference_key = _preference_topic_key(memory.content)
        if preference_key:
            return preference_key
    return f"{memory.kind or 'fact'}:{_normalize_memory_text(memory.content)}"


def _dedupe_memories_for_document(memories: list[Memory]) -> list[Memory]:
    seen: set[str] = set()
    deduped: list[Memory] = []
    for memory in memories:
        key = _memory_document_key(memory)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(memory)
    return deduped


def build_fallback_markdown(scope: str, memories: list[Memory]) -> str:
    title = _document_title(scope)
    if not memories:
        return f"# {title}\n\n暂无已确认记忆。"

    grouped: dict[str, list[Memory]] = {}
    for memory in _dedupe_memories_for_document(memories):
        grouped.setdefault(memory.kind or "fact", []).append(memory)

    sections = [f"# {title}"]
    for kind, items in grouped.items():
        label = KIND_LABELS.get(kind, kind or "事实")
        lines = "\n".join(f"- {item.content}" for item in items)
        sections.append(f"## {label}\n{lines}")
    return "\n\n".join(sections)


async def _generate_markdown(scope: str, memories: list[Memory]) -> GeneratedMemoryDocument:
    fallback = build_fallback_markdown(scope, memories)
    if not settings.MEMORY_DOCUMENTS_AI_ENABLED or not memories:
        return GeneratedMemoryDocument(content_md=fallback, generated_by="fallback")
    memory_model = get_memory_model()

    system_prompt = (
        "你是长期记忆整理器，负责把数据库中已确认的长期记忆整理成可直接注入聊天上下文的 Markdown 文档。"
        "只输出 Markdown，不要解释，不要输出 JSON。"
        "你必须严格遵守这些规则："
        "1. 只使用输入列表里的信息，不要编造新事实。"
        "2. 同一主题出现重复或近义表达时，只保留一条最清晰的表达。"
        "3. 同一主题出现冲突时，以 updated_at 最新的 active 记忆为准，旧说法不要输出。"
        "4. 例如“喜欢 X”和“不喜欢 X”互相冲突，“不喜欢 X 了”和“不喜欢 X”属于重复，均只保留最新结论。"
        "5. 按主题分组，优先使用“偏好、项目信息、工具与技术栈、已确认结论、事实”这些二级标题。"
        "6. 每条记忆要短、明确、可执行，删除口语化废词。"
        "7. 不要输出记忆 id、时间戳、来源字段或置信度。"
    )
    user_prompt = (
        f"记忆文档标题：{_document_title(scope)}\n\n"
        "已确认记忆列表：\n"
        f"{_format_source_memories(memories)}"
    )
    try:
        content = await llm_service.create_chat_completion(
            messages=[{"role": "user", "content": user_prompt}],
            model=memory_model,
            system_prompt=system_prompt,
            max_tokens=1600,
        )
    except Exception as error:
        return GeneratedMemoryDocument(
            content_md=fallback,
            generated_by="fallback",
            generation_model=memory_model,
            generation_error=str(error)[:MAX_GENERATION_ERROR_LENGTH],
        )

    normalized = content.strip()
    if not normalized:
        return GeneratedMemoryDocument(
            content_md=fallback,
            generated_by="fallback",
            generation_model=memory_model,
            generation_error="AI returned empty memory document.",
        )
    return GeneratedMemoryDocument(
        content_md=normalized,
        generated_by="ai",
        generation_model=memory_model,
    )


async def rebuild_memory_document(
    db: Session,
    user_id: str,
    scope: str,
    project_id: str | None = None,
    conversation_id: str | None = None,
) -> MemoryDocument:
    validate_document_scope(scope, project_id, conversation_id)
    memories = _load_source_memories(db, user_id, scope, project_id, conversation_id)
    generated = await _generate_markdown(scope, memories)
    source_memory_ids = ",".join(memory.id for memory in memories)
    now = _utcnow()
    document = get_memory_document(
        db,
        user_id,
        scope,
        project_id=project_id,
        conversation_id=conversation_id,
    )
    if document is None:
        document = MemoryDocument(
            user_id=user_id,
            scope=scope,
            project_id=project_id,
            conversation_id=conversation_id,
            content_md=generated.content_md,
            source_memory_ids=source_memory_ids,
            revision=1,
            is_stale=False,
            generated_by=generated.generated_by,
            generation_model=generated.generation_model,
            generation_error=generated.generation_error,
            generated_at=now,
        )
        db.add(document)
    else:
        document.content_md = generated.content_md
        document.source_memory_ids = source_memory_ids
        document.revision += 1
        document.is_stale = False
        document.generated_by = generated.generated_by
        document.generation_model = generated.generation_model
        document.generation_error = generated.generation_error
        document.generated_at = now
    db.commit()
    db.refresh(document)
    return document


async def rebuild_memory_document_with_new_session(
    user_id: str,
    scope: str,
    project_id: str | None = None,
    conversation_id: str | None = None,
) -> None:
    db = SessionLocal()
    try:
        await rebuild_memory_document(
            db,
            user_id=user_id,
            scope=scope,
            project_id=project_id,
            conversation_id=conversation_id,
        )
    finally:
        db.close()
