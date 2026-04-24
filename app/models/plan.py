from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Plan(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "plans"

    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    monthly_price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(16), nullable=False)
    monthly_soft_token_limit: Mapped[int] = mapped_column(BigInteger, nullable=False)
    daily_soft_token_limit: Mapped[int] = mapped_column(BigInteger, nullable=False)
    max_concurrent_requests: Mapped[int] = mapped_column(Integer, nullable=False)
    max_input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    max_output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    max_context_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    priority_level: Mapped[int] = mapped_column(Integer, nullable=False)
    allowed_models_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    features_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    subscriptions = relationship("Subscription", back_populates="plan")
    payment_orders = relationship("PaymentOrder", back_populates="plan")
