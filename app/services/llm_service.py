from collections.abc import AsyncGenerator
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from openai import AsyncOpenAI

from ..config import get_model_label, get_model_option, settings

_client = AsyncOpenAI(
    api_key=settings.OPENAI_API_KEY,
    base_url=settings.OPENAI_BASE_URL,
)

_SYSTEM_PROMPT = (
    "\u4f60\u662f\u4e00\u4e2a\u5e26\u957f\u671f\u8bb0\u5fc6\u7684\u804a\u5929\u52a9\u624b\u3002"
    "\u8bf7\u7528\u81ea\u7136\u7684\u4e2d\u6587\u56de\u7b54\uff0c"
    "\u6982\u5ff5\u7b80\u5355\u65f6\u8bf7\u4fdd\u6301\u7b80\u6d01\uff0c"
    "\u6d89\u53ca\u6846\u67b6\u3001\u67b6\u6784\u6216\u590d\u6742\u6280\u672f\u4e3b\u9898\u65f6\uff0c"
    "\u8bf7\u4e3b\u52a8\u5206\u5c42\u5c55\u5f00\uff0c\u8bb2\u6e05\u6982\u5ff5\u3001\u4f5c\u7528\u3001"
    "\u5173\u952e\u7ec4\u6210\u90e8\u5206\u3001\u5e38\u89c1\u7528\u6cd5\u548c\u9002\u7528\u573a\u666f\u3002\n"
    "\u5f53\u524d\u65f6\u95f4\uff08{timezone_name}\uff09\uff1a{current_time}\n"
    "\u5982\u679c\u7528\u6237\u63d0\u5230\u4eca\u5929\u3001\u6628\u5929\u3001\u660e\u5929\u6216\u5f53\u524d\u65f6\u95f4\uff0c"
    "\u8bf7\u4ee5\u4e0a\u9762\u7684\u65f6\u95f4\u4e3a\u51c6\u3002"
)

REASONING_BUDGETS = {
    "standard": 32,
    "deep": 256,
}


def _build_system_prompt(model: str) -> str:
    timezone_name = settings.APP_TIMEZONE
    try:
        app_timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        if timezone_name == "Asia/Shanghai":
            app_timezone = timezone(timedelta(hours=8), name=timezone_name)
        else:
            app_timezone = timezone.utc

    now = datetime.now(app_timezone).strftime("%Y-%m-%d %H:%M:%S")
    model_label = get_model_label(model)
    identity_prompt = (
        f"\n当前这次回答使用的模型是：{model_label}。"
        "如果用户问你是什么模型，只能依据这条系统信息回答，"
        "不要根据历史对话里其他模型的自称来推断自己的身份。"
    )
    return (_SYSTEM_PROMPT + identity_prompt).format(
        current_time=now,
        timezone_name=timezone_name,
    )


def _normalize_reasoning_level(
    model: str,
    reasoning_level: str | None,
    legacy_mode: str | None,
) -> str:
    model_option = get_model_option(model)
    reasoning_mode = model_option["reasoning_mode"] if model_option else "none"

    normalized = reasoning_level
    if normalized not in {"off", "standard", "deep"}:
        normalized = "deep" if legacy_mode == "think" else "off"

    if reasoning_mode == "none":
        return "off"
    if reasoning_mode == "toggle":
        return "off" if normalized == "off" else "standard"
    if reasoning_mode == "always_budget":
        return "deep" if normalized == "deep" else "standard"
    return normalized


def _get_model_max_tokens(model: str) -> int:
    """Get the max output tokens for a model from config."""
    model_option = get_model_option(model)
    if model_option and "max_tokens" in model_option:
        return model_option["max_tokens"]
    return 4096  # Fallback default


def _build_model_controls(
    model: str,
    reasoning_level: str,
) -> tuple[dict[str, object], int]:
    model_option = get_model_option(model)
    reasoning_mode = model_option["reasoning_mode"] if model_option else "none"
    extra_body: dict[str, object] = {}
    model_max = _get_model_max_tokens(model)

    if reasoning_mode == "none":
        return extra_body, model_max

    if reasoning_mode == "toggle":
        extra_body["thinking"] = {
            "type": "disabled" if reasoning_level == "off" else "enabled",
        }
        return extra_body, model_max

    budget = REASONING_BUDGETS["deep" if reasoning_level == "deep" else "standard"]

    if model in {"qwen3.5-plus", "qwen3.6-plus"}:
        if reasoning_level == "off":
            extra_body["enable_thinking"] = False
            return extra_body, model_max

        extra_body["enable_thinking"] = True
        extra_body["thinking_budget"] = budget
        return extra_body, max(model_max, budget)

    if model == "glm-5":
        if reasoning_level == "off":
            extra_body["thinking"] = {"type": "disabled"}
            return extra_body, model_max

        extra_body["thinking"] = {
            "type": "enabled",
            "budget_tokens": budget,
        }
        return extra_body, max(model_max, budget)

    if model == "MiniMax-M2.5":
        extra_body["reasoning_split"] = True
        extra_body["thinking_budget"] = budget
        return extra_body, max(model_max, budget)

    return extra_body, model_max


async def stream_chat_completion(
    messages: list[dict[str, object]],
    model: str | None = None,
    reasoning_level: str | None = None,
    legacy_mode: str | None = None,
    system_prompt: str | None = None,
) -> AsyncGenerator[str, None]:
    chosen_model = model or settings.OPENAI_MODEL
    normalized_reasoning = _normalize_reasoning_level(
        chosen_model,
        reasoning_level,
        legacy_mode,
    )
    extra_body, max_tokens = _build_model_controls(chosen_model, normalized_reasoning)

    full_messages = [
        {
            "role": "system",
            "content": system_prompt or _build_system_prompt(chosen_model),
        }
    ]
    full_messages.extend(messages)

    stream = await _client.chat.completions.create(
        model=chosen_model,
        messages=full_messages,
        stream=True,
        max_tokens=max_tokens,
        extra_body=extra_body or None,
    )

    async for chunk in stream:
        delta = chunk.choices[0].delta
        if delta.content:
            yield delta.content
