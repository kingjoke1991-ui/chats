from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, JSON, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ModelNode(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "model_nodes"

    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    provider_type: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    api_key_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="healthy", index=True)
    weight: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    max_parallel_requests: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    current_parallel_requests: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    avg_ttft_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    avg_tps: Mapped[Optional[float]] = mapped_column(Numeric(10, 2), nullable=True)
    capability_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    last_healthcheck_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_healthy_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
