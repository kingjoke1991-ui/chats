from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class CheckoutSessionRequest(BaseModel):
    plan_code: str = Field(min_length=1, max_length=64)


class PaymentOrderRead(BaseModel):
    id: str
    provider: str
    status: str
    merchant_order_id: str
    provider_trade_id: str | None
    amount_cents: int
    currency: str
    actual_amount: float | None
    payment_address: str | None
    block_transaction_id: str | None
    checkout_url: str | None
    payment_token: str | None
    expires_at: datetime | None
    paid_at: datetime | None
    created_at: datetime
    plan_code: str
    plan_name: str


class PaymentOrdersResponse(BaseModel):
    items: list[PaymentOrderRead]


class CheckoutSessionResponse(BaseModel):
    status: str
    provider: str
    checkout_url: str | None
    detail: str
    order: PaymentOrderRead
