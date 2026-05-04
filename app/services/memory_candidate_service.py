import json
import re

from sqlalchemy import select

from ..config import get_memory_model
from ..models import Conversation, Memory, MemoryCandidate, Project, _utcnow
from . import embedding_service, llm_service, memory_service


VALID_CANDIDATE_ACTIONS = {"create", "update", "archive", "none"}
VALID_CANDIDATE_SURFACES = {"inline", "settings"}


def _normalize_memory_text(content: str) -> str:
    text = re.sub(r"\s+", "", content.strip().lower())
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


def _memory_identity_key(content: str, kind: str) -> str:
    if kind == "preference":
        preference_key = _preference_topic_key(content)
        if preference_key:
            return preference_key
    return f"{kind}:{_normalize_memory_text(content)}"


def _active_memory_scope_filters(scope: str, project_id: str | None, conversation_id: str | None):
    if scope == "global":
        return (Memory.project_id.is_(None), Memory.conversation_id.is_(None))
    if scope == "project":
        return (Memory.project_id == project_id, Memory.conversation_id.is_(None))
    return (Memory.conversation_id == conversation_id,)


def find_existing_memory_match(
    db,
    user_id: str,
    scope: str,
    project_id: str | None,
    conversation_id: str | None,
    content: str,
    kind: str,
) -> tuple[str, Memory | None]:
    memory_service.validate_memory_scope(scope, project_id, conversation_id)
    candidate_exact_key = f"{kind}:{_normalize_memory_text(content)}"
    candidate_identity_key = _memory_identity_key(content, kind)
    stmt = (
        select(Memory)
        .where(
            Memory.user_id == user_id,
            Memory.scope == scope,
            Memory.kind == kind,
            Memory.enabled.is_(True),
            Memory.status == "active",
            Memory.archived_at.is_(None),
            *_active_memory_scope_filters(scope, project_id, conversation_id),
        )
        .order_by(Memory.updated_at.desc(), Memory.created_at.desc())
    )
    memories = list(db.execute(stmt).scalars().all())

    # Fast path: exact text matching
    for memory in memories:
        memory_exact_key = f"{memory.kind}:{_normalize_memory_text(memory.content)}"
        if memory_exact_key == candidate_exact_key:
            return "duplicate", memory
        if _memory_identity_key(memory.content, memory.kind) == candidate_identity_key:
            return "update", memory

    return "create", None, memories


def _extract_json_text(payload: str) -> str:
    text = payload.strip()
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()
    return text


async def _llm_semantic_match(
    candidate_content: str,
    candidate_kind: str,
    existing_memories: list[Memory],
) -> tuple[str, Memory | None]:
    """Use LLM to determine if candidate is a semantic duplicate/update of existing memories."""
    if not existing_memories:
        return "create", None

    memories_text = "\n".join(
        f"- id: {m.id} / kind: {m.kind} / content: {m.content}"
        for m in existing_memories
    )

    system_prompt = (
        "你是记忆去重判断器。判断候选记忆与已有记忆列表的语义关系。\n"
        "只返回一个 JSON 对象，不要返回其他内容。\n"
        "字段：relation（duplicate/update/create）、target_id。\n"
        "duplicate：候选记忆与某条已有记忆表达完全相同的信息，只是措辞不同。\n"
        "update：候选记忆是对某条已有记忆的更新、修正或否定（如偏好改变、技术栈更换）。\n"
        "create：候选记忆与已有记忆无关，是新信息。\n"
        "如果是 duplicate 或 update，target_id 设置为对应已有记忆的 id。\n"
        "如果是 create，target_id 设置为 null。\n"
        "注意区分：'我喜欢X'和'我不喜欢X'是 update 关系，不是 duplicate。"
    )
    user_prompt = (
        f"候选记忆：kind={candidate_kind} / content={candidate_content}\n\n"
        f"已有记忆列表：\n{memories_text}"
    )

    try:
        response = await llm_service.create_chat_completion(
            messages=[{"role": "user", "content": user_prompt}],
            model=get_memory_model(),
            system_prompt=system_prompt,
            max_tokens=200,
        )
        data = json.loads(_extract_json_text(response))
        relation = data.get("relation", "create")
        target_id = data.get("target_id")

        if relation in ("duplicate", "update") and target_id:
            target = next((m for m in existing_memories if m.id == target_id), None)
            if target:
                return relation, target

        return "create", None
    except Exception:
        return "create", None


SIMILARITY_TOP_K = 10


async def _embedding_prefilter(
    candidate_content: str,
    existing_memories: list[Memory],
    db,
) -> list[Memory]:
    """Use embedding similarity to narrow down candidates before LLM."""
    candidate_embedding = await embedding_service.compute_embedding(candidate_content)
    if not candidate_embedding:
        # Embedding unavailable, fall through to LLM with all memories
        return existing_memories

    # Lazy backfill: compute embeddings for memories that don't have one
    missing = [m for m in existing_memories if not m.embedding]
    if missing:
        texts = [m.content for m in missing]
        embeddings = await embedding_service.compute_embeddings(texts)
        for memory, embedding in zip(missing, embeddings):
            if embedding:
                memory.embedding = embedding_service.serialize(embedding)
        db.flush()

    # Score and rank by similarity
    scored: list[tuple[float, Memory]] = []
    for memory in existing_memories:
        mem_embedding = embedding_service.deserialize(memory.embedding)
        if not mem_embedding:
            continue
        score = embedding_service.cosine_similarity(candidate_embedding, mem_embedding)
        scored.append((score, memory))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [m for _, m in scored[:SIMILARITY_TOP_K]]


async def find_semantic_memory_match(
    db,
    user_id: str,
    scope: str,
    project_id: str | None,
    conversation_id: str | None,
    content: str,
    kind: str,
) -> tuple[str, Memory | None]:
    """Text-based fast path → embedding pre-filter → LLM semantic match."""
    text_result, memory, existing_memories = find_existing_memory_match(
        db, user_id, scope, project_id, conversation_id, content, kind,
    )

    # Fast path found a match
    if text_result != "create":
        return text_result, memory

    if not existing_memories:
        return "create", None

    # Embedding pre-filter → LLM precise match
    top_k = await _embedding_prefilter(content, existing_memories, db)
    return await _llm_semantic_match(content, kind, top_k)


def create_memory_candidate(
    db,
    user_id: str,
    scope: str,
    project_id: str | None,
    conversation_id: str | None,
    action: str,
    target_memory_id: str | None,
    content: str,
    kind: str,
    confidence: int,
    importance: int,
    reason: str,
    surface: str,
    source_message_id: str | None,
    extraction_model: str | None,
) -> MemoryCandidate:
    memory_service.validate_memory_scope(scope, project_id, conversation_id)
    if project_id is not None:
        project = db.get(Project, project_id)
        if project is None or project.user_id != user_id:
            raise ValueError("Project not found")
    if conversation_id is not None:
        conversation = db.get(Conversation, conversation_id)
        if conversation is None or conversation.user_id != user_id:
            raise ValueError("Conversation not found")
        memory_service.validate_conversation_project(project_id, conversation.project_id)
    if action not in VALID_CANDIDATE_ACTIONS:
        raise ValueError("Invalid memory candidate action")
    if action == "none":
        raise ValueError("Memory candidate action none should not be saved")
    if surface not in VALID_CANDIDATE_SURFACES:
        raise ValueError("Invalid memory candidate surface")

    candidate = MemoryCandidate(
        user_id=user_id,
        scope=scope,
        project_id=project_id,
        conversation_id=conversation_id,
        action=action,
        target_memory_id=target_memory_id,
        content=content,
        kind=kind,
        confidence=confidence,
        importance=importance,
        reason=reason,
        surface=surface,
        source_message_id=source_message_id,
        extraction_model=extraction_model,
        status="pending",
    )
    db.add(candidate)
    db.commit()
    db.refresh(candidate)
    return candidate


def _accept_candidate(
    db,
    candidate: MemoryCandidate,
    content: str,
) -> tuple[Memory | None, str | None]:
    now = _utcnow()
    memory = None
    archived_memory_id = None

    if candidate.action == "create":
        memory = Memory(
            user_id=candidate.user_id,
            scope=candidate.scope,
            project_id=candidate.project_id,
            conversation_id=candidate.conversation_id,
            content=content,
            kind=candidate.kind,
            importance=candidate.importance,
            source_message_id=candidate.source_message_id,
            source_candidate_id=candidate.id,
        )
        db.add(memory)
    elif candidate.action == "update":
        target = _get_valid_target(db, candidate)
        memory = Memory(
            user_id=candidate.user_id,
            scope=candidate.scope,
            project_id=candidate.project_id,
            conversation_id=candidate.conversation_id,
            content=content,
            kind=candidate.kind,
            importance=candidate.importance,
            source_message_id=candidate.source_message_id,
            source_candidate_id=candidate.id,
        )
        db.add(memory)
        db.flush()
        target.status = "archived"
        target.archived_at = now
        target.superseded_by_id = memory.id
        archived_memory_id = target.id
    elif candidate.action == "archive":
        target = _get_valid_target(db, candidate)
        target.status = "archived"
        target.archived_at = now
        archived_memory_id = target.id
    else:
        raise ValueError("Invalid memory candidate action")

    if memory is not None and memory.id is None:
        db.flush()
    candidate.status = "accepted"
    candidate.accepted_memory_id = memory.id if memory is not None else None
    candidate.reviewed_at = now
    return memory, archived_memory_id


def auto_accept_memory_candidate(
    db,
    user_id: str,
    scope: str,
    project_id: str | None,
    conversation_id: str | None,
    action: str,
    target_memory_id: str | None,
    content: str,
    kind: str,
    confidence: int,
    importance: int,
    reason: str,
    source_message_id: str | None,
    extraction_model: str | None,
) -> tuple[MemoryCandidate, Memory | None, str | None]:
    memory_service.validate_memory_scope(scope, project_id, conversation_id)
    if project_id is not None:
        project = db.get(Project, project_id)
        if project is None or project.user_id != user_id:
            raise ValueError("Project not found")
    if conversation_id is not None:
        conversation = db.get(Conversation, conversation_id)
        if conversation is None or conversation.user_id != user_id:
            raise ValueError("Conversation not found")
        memory_service.validate_conversation_project(project_id, conversation.project_id)
    if action not in VALID_CANDIDATE_ACTIONS:
        raise ValueError("Invalid memory candidate action")
    if action == "none":
        raise ValueError("Memory candidate action none should not be saved")

    candidate = MemoryCandidate(
        user_id=user_id,
        scope=scope,
        project_id=project_id,
        conversation_id=conversation_id,
        action=action,
        target_memory_id=target_memory_id,
        content=content,
        kind=kind,
        confidence=confidence,
        importance=importance,
        reason=reason,
        surface="settings",
        source_message_id=source_message_id,
        extraction_model=extraction_model,
        status="pending",
    )
    db.add(candidate)
    db.flush()
    memory, archived_memory_id = _accept_candidate(db, candidate, content)
    db.commit()
    db.refresh(candidate)
    if memory is not None:
        db.refresh(memory)
    return candidate, memory, archived_memory_id


def _get_user_candidate(db, user_id: str, candidate_id: str) -> MemoryCandidate:
    candidate = db.get(MemoryCandidate, candidate_id)
    if not candidate or candidate.user_id != user_id:
        raise ValueError("Memory candidate not found")
    return candidate


def validate_candidate_target(candidate: MemoryCandidate, target: Memory) -> None:
    if target.user_id != candidate.user_id:
        raise ValueError("Target memory not found")
    if target.scope != candidate.scope:
        raise ValueError("Target memory scope mismatch")
    if candidate.scope == "project" and target.project_id != candidate.project_id:
        raise ValueError("Target memory project mismatch")
    if candidate.scope == "conversation" and target.conversation_id != candidate.conversation_id:
        raise ValueError("Target memory conversation mismatch")


def _get_valid_target(db, candidate: MemoryCandidate) -> Memory:
    if candidate.target_memory_id is None:
        raise ValueError("Target memory is required")
    target = db.get(Memory, candidate.target_memory_id)
    if target is None:
        raise ValueError("Target memory not found")
    validate_candidate_target(candidate, target)
    return target


def accept_memory_candidate(
    db,
    user_id: str,
    candidate_id: str,
    content_override: str | None = None,
) -> tuple[MemoryCandidate, Memory | None, str | None]:
    candidate = _get_user_candidate(db, user_id, candidate_id)
    if candidate.status != "pending":
        raise ValueError("Only pending memory candidates can be accepted")

    content = content_override if content_override is not None else candidate.content
    memory, archived_memory_id = _accept_candidate(db, candidate, content)
    db.commit()
    db.refresh(candidate)
    if memory is not None:
        db.refresh(memory)
    return candidate, memory, archived_memory_id


def dismiss_memory_candidate(db, user_id: str, candidate_id: str) -> MemoryCandidate:
    candidate = _get_user_candidate(db, user_id, candidate_id)
    if candidate.status != "pending":
        raise ValueError("Only pending memory candidates can be dismissed")
    candidate.status = "dismissed"
    candidate.reviewed_at = _utcnow()
    db.commit()
    db.refresh(candidate)
    return candidate


def defer_memory_candidate(db, user_id: str, candidate_id: str) -> MemoryCandidate:
    candidate = _get_user_candidate(db, user_id, candidate_id)
    if candidate.status != "pending":
        raise ValueError("Only pending memory candidates can be deferred")
    candidate.surface = "settings"
    db.commit()
    db.refresh(candidate)
    return candidate
