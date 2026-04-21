from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]

AVAILABLE_MODEL_OPTIONS = [
    {
        "id": "qwen3-coder-next",
        "label": "Qwen 3 Coder Next",
        "latency_hint": "fast",
        "reasoning_mode": "none",
        "experimental_reasoning": False,
        "max_tokens": 16384,
    },
    {
        "id": "qwen3-coder-plus",
        "label": "Qwen 3 Coder Plus",
        "latency_hint": "fast",
        "reasoning_mode": "none",
        "experimental_reasoning": False,
        "max_tokens": 16384,
    },
    {
        "id": "kimi-k2.5",
        "label": "Kimi K2.5",
        "latency_hint": "fast",
        "reasoning_mode": "toggle",
        "experimental_reasoning": False,
        "max_tokens": 8192,
    },
    {
        "id": "MiniMax-M2.5",
        "label": "MiniMax M2.5",
        "latency_hint": "balanced",
        "reasoning_mode": "always_budget",
        "experimental_reasoning": True,
        "max_tokens": 16384,
    },
    {
        "id": "qwen3.5-plus",
        "label": "Qwen 3.5 Plus",
        "latency_hint": "balanced",
        "reasoning_mode": "budget",
        "experimental_reasoning": False,
        "max_tokens": 8192,
    },
    {
        "id": "qwen3.6-plus",
        "label": "Qwen 3.6 Plus",
        "latency_hint": "slower",
        "reasoning_mode": "budget",
        "experimental_reasoning": False,
        "max_tokens": 8192,
    },
    {
        "id": "glm-5",
        "label": "GLM-5",
        "latency_hint": "slower",
        "reasoning_mode": "budget",
        "experimental_reasoning": True,
        "max_tokens": 8192,
    },
]


def _default_database_url() -> str:
    return f"sqlite:///{(BACKEND_DIR / 'chat.db').as_posix()}"


def get_supported_model_ids() -> set[str]:
    return {item["id"] for item in AVAILABLE_MODEL_OPTIONS}


def get_default_model() -> str:
    if settings.OPENAI_MODEL in get_supported_model_ids():
        return settings.OPENAI_MODEL
    return AVAILABLE_MODEL_OPTIONS[0]["id"]


def get_model_option(model_id: str) -> dict[str, str | bool] | None:
    return next((item for item in AVAILABLE_MODEL_OPTIONS if item["id"] == model_id), None)


def get_model_label(model_id: str | None) -> str:
    if not model_id:
        return "未知模型"

    model_option = get_model_option(model_id)
    if model_option and isinstance(model_option.get("label"), str):
        return model_option["label"]

    return model_id


class Settings(BaseSettings):
    """Application configuration loaded from environment variables / .env file."""

    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    OPENAI_MODEL: str = "gpt-3.5-turbo"
    DATABASE_URL: str = _default_database_url()
    CONTEXT_WINDOW_SIZE: int = 20
    APP_TIMEZONE: str = "Asia/Shanghai"

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
    )


settings = Settings()
