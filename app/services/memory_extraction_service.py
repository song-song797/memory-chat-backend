import json
import re
from dataclasses import dataclass
from typing import Any

from ..config import settings
from . import llm_service
from .memory_service import VALID_MEMORY_SCOPES

VALID_CANDIDATE_ACTIONS = {"create", "update", "archive", "none"}


@dataclass(frozen=True)
class ExtractedMemoryCandidate:
    content: str
    kind: str
    scope: str
    action: str
    confidence: int
    importance: int
    reason: str
    target_memory_id: str | None = None


def _extract_json_text(payload: str) -> str:
    text = payload.strip()
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()
    return text


def _to_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _clamped_int(value: Any) -> int:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        number = 0
    return max(0, min(100, number))


def parse_memory_candidate_payload(payload: str) -> ExtractedMemoryCandidate | None:
    try:
        data = json.loads(_extract_json_text(payload))
    except json.JSONDecodeError:
        return None

    if not isinstance(data, dict):
        return None
    if _to_bool(data.get("sensitive")):
        return None

    content = _to_text(data.get("content"))
    kind = _to_text(data.get("kind"))
    scope = _to_text(data.get("scope"))
    action = _to_text(data.get("action"))
    reason = _to_text(data.get("reason"))
    target_memory_id = _to_text(data.get("target_memory_id")) or None
    confidence = _clamped_int(data.get("confidence"))
    importance = _clamped_int(data.get("importance"))

    if not content:
        return None
    if scope not in VALID_MEMORY_SCOPES:
        return None
    if action not in VALID_CANDIDATE_ACTIONS:
        return None
    if action == "none":
        return None
    if confidence < settings.MEMORY_CANDIDATE_CONFIDENCE_THRESHOLD:
        return None

    return ExtractedMemoryCandidate(
        content=content,
        kind=kind,
        scope=scope,
        action=action,
        confidence=confidence,
        importance=importance,
        reason=reason,
        target_memory_id=target_memory_id,
    )


def resolve_candidate_scope(
    project_id: str | None,
    conversation_id: str | None,
    kind: str,
    suggested_scope: str,
) -> tuple[str | None, str | None, str | None]:
    if kind == "preference":
        return "global", None, None
    if kind in {"project", "tool"} and project_id is not None:
        return "project", project_id, None
    if kind == "decision":
        resolved_scope = "conversation"
    elif project_id is None:
        resolved_scope = "conversation"
    elif suggested_scope in VALID_MEMORY_SCOPES:
        resolved_scope = suggested_scope
    else:
        resolved_scope = "project"

    if resolved_scope == "global":
        return "global", None, None
    if resolved_scope == "project":
        if project_id is None:
            resolved_scope = "conversation"
        else:
            return "project", project_id, None
    if resolved_scope == "conversation":
        if conversation_id is None:
            return None, None, None
        return "conversation", None, conversation_id

    return None, None, None


def choose_candidate_surface(candidate: ExtractedMemoryCandidate) -> str:
    if candidate.action in {"update", "archive"}:
        return "inline"
    if (
        candidate.confidence >= settings.MEMORY_INLINE_CONFIDENCE_THRESHOLD
        and candidate.importance >= settings.MEMORY_INLINE_IMPORTANCE_THRESHOLD
    ):
        return "inline"
    return "settings"


def _memory_value(memory: Any, key: str) -> Any:
    if isinstance(memory, dict):
        return memory.get(key)
    return getattr(memory, key, None)


def _format_existing_memories(existing_memories: list[Any]) -> str:
    if not existing_memories:
        return "无"

    lines: list[str] = []
    for memory in existing_memories:
        memory_id = _to_text(_memory_value(memory, "id")) or "-"
        scope = _to_text(_memory_value(memory, "scope")) or "-"
        kind = _to_text(_memory_value(memory, "kind")) or "-"
        content = " ".join(_to_text(_memory_value(memory, "content")).split())
        lines.append(f"- id: {memory_id} / scope: {scope} / kind: {kind} / content: {content}")
    return "\n".join(lines)


async def extract_memory_candidate(
    user_message: str,
    project_id: str | None,
    conversation_id: str | None,
    existing_memories: list[Any],
    model: str | None = None,
) -> ExtractedMemoryCandidate | None:
    if not settings.MEMORY_AUTO_SUGGESTIONS_ENABLED:
        return None

    system_prompt = (
        "你是长期记忆候选提取器。请从用户最新消息中判断是否值得生成一条候选记忆。"
        "只返回一个 JSON 对象，不要返回 Markdown、解释或额外文本。"
        "字段必须包含：content、kind、scope、action、target_memory_id、confidence、"
        "importance、reason、sensitive。"
        "kind 可使用 preference、project、tool、decision、fact。"
        "scope 只能是 global、project、conversation。"
        "action 只能是 create、update、archive、none。"
        "如果内容涉及隐私、账号、密钥、身份证、手机号、地址等敏感信息，"
        "请设置 sensitive=true。"
        "如果没有明确、稳定、可复用的记忆价值，请设置 action=none。"
        "如果用户只是在重复已有记忆，请设置 action=none。"
        "如果用户修正、否定或替换了已有记忆，请设置 action=update，"
        "并把 target_memory_id 设置为被替换的已有记忆 id。"
        "confidence 和 importance 使用 0 到 100 的整数。"
    )
    user_prompt = (
        "用户最新消息：\n"
        f"{user_message}\n\n"
        "已有记忆列表（可用于判断 update/archive 的 target_memory_id）：\n"
        f"{_format_existing_memories(existing_memories)}"
    )

    payload = await llm_service.create_chat_completion(
        messages=[{"role": "user", "content": user_prompt}],
        model=model,
        system_prompt=system_prompt,
        max_tokens=800,
    )
    candidate = parse_memory_candidate_payload(payload)
    if candidate is None:
        return None

    scope, _, _ = resolve_candidate_scope(
        project_id=project_id,
        conversation_id=conversation_id,
        kind=candidate.kind,
        suggested_scope=candidate.scope,
    )
    if scope is None:
        return None

    return ExtractedMemoryCandidate(
        content=candidate.content,
        kind=candidate.kind,
        scope=scope,
        action=candidate.action,
        confidence=candidate.confidence,
        importance=candidate.importance,
        reason=candidate.reason,
        target_memory_id=candidate.target_memory_id,
    )
