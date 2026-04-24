from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ConversationRead(BaseModel):
    id: str
    user_id: str
    title: str | None
    summary: str | None
    pinned: bool
    archived: bool
    latest_model: str | None
    latest_message_at: datetime
    message_count: int
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class ConversationListResponse(BaseModel):
    items: list[ConversationRead]
    total: int


class ConversationCreateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=255)


class ConversationUpdateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    pinned: bool | None = None
    archived: bool | None = None


class MessageRead(BaseModel):
    id: str
    conversation_id: str
    user_id: str
    role: str
    content_text: str
    model: str | None
    status: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    finish_reason: str | None
    error_code: str | None
    error_message: str | None
    request_id: str | None
    created_at: datetime
    updated_at: datetime


class ConversationMessagesResponse(BaseModel):
    conversation: ConversationRead
    messages: list[MessageRead]
