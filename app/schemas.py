from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, field_serializer


def _serialize_datetime(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


class ChatRequest(BaseModel):
    conversation_id: str | None = None
    message: str = Field(default="", max_length=10000)
    model: str | None = None
    reasoning_level: Literal["off", "standard", "deep"] | None = None
    mode: Literal["fast", "think"] | None = None


class LandingChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(..., min_length=1, max_length=4000)


class LandingChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    history: list[LandingChatMessage] = Field(default_factory=list)


class ConversationCreate(BaseModel):
    title: str = "\u65b0\u5bf9\u8bdd"


class ConversationUpdate(BaseModel):
    title: str | None = None
    pinned: bool | None = None


class RegisterRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=8, max_length=128)


class UserOut(BaseModel):
    id: str
    email: str
    created_at: datetime

    model_config = {"from_attributes": True}

    @field_serializer("created_at")
    def serialize_created_at(self, value: datetime) -> str:
        return _serialize_datetime(value)


class AuthResponse(BaseModel):
    token: str
    user: UserOut


class AttachmentOut(BaseModel):
    id: str
    name: str
    mime_type: str
    kind: str
    size_bytes: int
    content_url: str
    created_at: datetime

    model_config = {"from_attributes": True}

    @field_serializer("created_at")
    def serialize_created_at(self, value: datetime) -> str:
        return _serialize_datetime(value)


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    created_at: datetime
    attachments: list[AttachmentOut] = []

    model_config = {"from_attributes": True}

    @field_serializer("created_at")
    def serialize_created_at(self, value: datetime) -> str:
        return _serialize_datetime(value)


class ConversationOut(BaseModel):
    id: str
    title: str
    pinned: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @field_serializer("created_at", "updated_at")
    def serialize_datetimes(self, value: datetime) -> str:
        return _serialize_datetime(value)


class ConversationDetail(ConversationOut):
    messages: list[MessageOut] = []


class ModelOption(BaseModel):
    id: str
    label: str
    latency_hint: str | None = None
    reasoning_mode: Literal["none", "toggle", "budget", "always_budget"] = "none"
    experimental_reasoning: bool = False


class ModelCatalog(BaseModel):
    default_model: str
    models: list[ModelOption]
