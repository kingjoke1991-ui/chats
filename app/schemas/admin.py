from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class AdminUserRow(BaseModel):
    id: str
    email: str
    username: str | None
    status: str
    is_admin: bool
    last_login_at: datetime | None
    created_at: datetime
    subscription_status: str | None
    plan_code: str | None


class AdminUsersResponse(BaseModel):
    items: list[AdminUserRow]
    total: int


class AdminUserUpdateRequest(BaseModel):
    status: str | None = Field(default=None, pattern="^(active|suspended|deleted)$")
    is_admin: bool | None = None


class AdminMetricsOverview(BaseModel):
    total_users: int
    active_subscriptions: int
    total_conversations: int
    total_messages: int
    assistant_success_today: int
    assistant_failed_today: int
    tokens_today: int


class AdminNodeRead(BaseModel):
    id: str
    code: str
    provider_type: str
    provider_code: str
    base_url: str
    model_name: str
    enabled: bool
    status: str
    weight: int
    priority: int
    current_parallel_requests: int
    max_parallel_requests: int
    last_healthcheck_at: datetime | None
    last_healthy_at: datetime | None


class AdminNodeUpdateRequest(BaseModel):
    enabled: bool | None = None
    status: str | None = Field(default=None, pattern="^(healthy|degraded|unhealthy|draining)$")
    weight: int | None = Field(default=None, ge=0, le=10000)
    priority: int | None = Field(default=None, ge=0, le=10000)


class AdminConversationRow(BaseModel):
    id: str
    user_id: str
    user_email: str
    title: str | None
    latest_model: str | None
    latest_message_at: datetime
    message_count: int
    archived: bool
    pinned: bool


class AdminConversationsResponse(BaseModel):
    items: list[AdminConversationRow]


class AdminFailedMessageRow(BaseModel):
    id: str
    conversation_id: str
    user_id: str
    content_text: str
    error_code: str | None
    error_message: str | None
    created_at: datetime


class AdminFailedMessagesResponse(BaseModel):
    items: list[AdminFailedMessageRow]


class AdminPlanRow(BaseModel):
    id: str
    code: str
    name: str
    monthly_price_cents: int
    currency: str
    monthly_soft_token_limit: int
    daily_soft_token_limit: int
    max_concurrent_requests: int
    max_input_tokens: int
    max_output_tokens: int
    max_context_tokens: int
    priority_level: int
    allowed_models_json: list[str]
    features_json: dict
    is_active: bool


class AdminPlansResponse(BaseModel):
    items: list[AdminPlanRow]


class AdminPlanCreateRequest(BaseModel):
    code: str = Field(min_length=2, max_length=64)
    name: str = Field(min_length=2, max_length=128)
    monthly_price_cents: int = Field(ge=0, le=10_000_000)
    currency: str = Field(min_length=3, max_length=16)
    monthly_soft_token_limit: int = Field(ge=0)
    daily_soft_token_limit: int = Field(ge=0)
    max_concurrent_requests: int = Field(ge=1, le=64)
    max_input_tokens: int = Field(ge=1, le=1_000_000)
    max_output_tokens: int = Field(ge=1, le=1_000_000)
    max_context_tokens: int = Field(ge=1, le=1_000_000)
    priority_level: int = Field(ge=0, le=10_000)
    allowed_models_json: list[str] = Field(default_factory=list)
    features_json: dict = Field(default_factory=dict)
    is_active: bool = True


class AdminPlanUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=128)
    monthly_price_cents: int | None = Field(default=None, ge=0, le=10_000_000)
    currency: str | None = Field(default=None, min_length=3, max_length=16)
    monthly_soft_token_limit: int | None = Field(default=None, ge=0)
    daily_soft_token_limit: int | None = Field(default=None, ge=0)
    max_concurrent_requests: int | None = Field(default=None, ge=1, le=64)
    max_input_tokens: int | None = Field(default=None, ge=1, le=1_000_000)
    max_output_tokens: int | None = Field(default=None, ge=1, le=1_000_000)
    max_context_tokens: int | None = Field(default=None, ge=1, le=1_000_000)
    priority_level: int | None = Field(default=None, ge=0, le=10_000)
    allowed_models_json: list[str] | None = None
    features_json: dict | None = None
    is_active: bool | None = None


class AdminPaymentOrderRow(BaseModel):
    id: str
    user_email: str
    plan_code: str
    plan_name: str
    provider: str
    status: str
    merchant_order_id: str
    provider_trade_id: str | None
    amount_cents: int
    currency: str
    checkout_url: str | None
    expires_at: datetime | None
    paid_at: datetime | None
    created_at: datetime


class AdminPaymentOrdersResponse(BaseModel):
    items: list[AdminPaymentOrderRow]
