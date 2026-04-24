from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class PlanRead(BaseModel):
    id: str
    code: str
    name: str
    monthly_price_cents: int
    currency: str
    max_concurrent_requests: int
    max_input_tokens: int
    max_output_tokens: int
    max_context_tokens: int
    priority_level: int
    allowed_models_json: list[str]
    features_json: dict
    is_active: bool


class SubscriptionRead(BaseModel):
    id: str
    user_id: str
    plan_id: str
    provider: str
    status: str
    start_at: datetime
    end_at: datetime
    cancel_at_period_end: bool


class CurrentSubscriptionResponse(BaseModel):
    subscription: SubscriptionRead
    plan: PlanRead


class PlanListResponse(BaseModel):
    items: list[PlanRead]
