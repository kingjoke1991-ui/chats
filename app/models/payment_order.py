from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, TimestampMixin, UUIDPrimaryKeyMixin


class PaymentOrder(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "payment_orders"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("plans.id"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    merchant_order_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    provider_trade_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, unique=True, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(16), nullable=False)
    checkout_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    payment_token: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    redirect_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    canceled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_payload_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    user = relationship("User", back_populates="payment_orders")
    plan = relationship("Plan", back_populates="payment_orders")
