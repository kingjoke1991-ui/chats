from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class ChatMessageInput(BaseModel):
    role: str
    content: str

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: str) -> str:
        if value not in {"system", "user", "assistant", "tool"}:
            raise ValueError("role must be one of system, user, assistant, tool")
        return value

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("content must not be empty")
        return value


class ChatCompletionRequest(BaseModel):
    conversation_id: str | None = None
    messages: list[ChatMessageInput] = Field(min_length=1)
    model: str | None = None
    stream: bool = False
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, gt=0, le=8192)
    metadata: dict[str, Any] | None = None
    idempotency_key: str | None = Field(default=None, max_length=128)


class ChatMessageOutput(BaseModel):
    role: str
    content: str


class ChatCompletionChoice(BaseModel):
    index: int
    message: ChatMessageOutput
    finish_reason: str | None = None


class ChatCompletionUsage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: list[ChatCompletionChoice]
    usage: ChatCompletionUsage
    conversation_id: str
    provider: str
    node_id: str
