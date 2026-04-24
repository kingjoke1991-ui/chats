from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.constants import PAYMENT_STATUS_PENDING
from app.models.payment_order import PaymentOrder
from app.models.plan import Plan
from app.models.user import User


class PaymentOrderRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, order: PaymentOrder) -> PaymentOrder:
        self.session.add(order)
        await self.session.flush()
        await self.session.refresh(order)
        return order

    async def update(self, order: PaymentOrder) -> PaymentOrder:
        await self.session.flush()
        await self.session.refresh(order)
        return order

    async def get_by_id(self, order_id: str) -> PaymentOrder | None:
        result = await self.session.execute(
            select(PaymentOrder)
            .options(selectinload(PaymentOrder.plan), selectinload(PaymentOrder.user))
            .where(PaymentOrder.id == order_id)
        )
        return result.scalar_one_or_none()

    async def get_by_merchant_order_id(self, merchant_order_id: str) -> PaymentOrder | None:
        result = await self.session.execute(
            select(PaymentOrder)
            .options(selectinload(PaymentOrder.plan), selectinload(PaymentOrder.user))
            .where(PaymentOrder.merchant_order_id == merchant_order_id)
        )
        return result.scalar_one_or_none()

    async def get_by_provider_trade_id(self, provider_trade_id: str) -> PaymentOrder | None:
        result = await self.session.execute(
            select(PaymentOrder)
            .options(selectinload(PaymentOrder.plan), selectinload(PaymentOrder.user))
            .where(PaymentOrder.provider_trade_id == provider_trade_id)
        )
        return result.scalar_one_or_none()

    async def get_latest_pending_for_user_plan(self, user_id: str, plan_id: str) -> PaymentOrder | None:
        now = datetime.now(UTC)
        result = await self.session.execute(
            select(PaymentOrder)
            .options(selectinload(PaymentOrder.plan))
            .where(
                PaymentOrder.user_id == user_id,
                PaymentOrder.plan_id == plan_id,
                PaymentOrder.status == PAYMENT_STATUS_PENDING,
                or_(PaymentOrder.expires_at.is_(None), PaymentOrder.expires_at > now),
            )
            .order_by(desc(PaymentOrder.created_at))
        )
        return result.scalars().first()

    async def list_for_user(self, user_id: str, *, limit: int = 20) -> list[PaymentOrder]:
        result = await self.session.execute(
            select(PaymentOrder)
            .options(selectinload(PaymentOrder.plan))
            .where(PaymentOrder.user_id == user_id)
            .order_by(desc(PaymentOrder.created_at))
            .limit(limit)
        )
        return result.scalars().all()

    async def list_syncable_pending_for_user(self, user_id: str, *, limit: int = 10) -> list[PaymentOrder]:
        result = await self.session.execute(
            select(PaymentOrder)
            .options(selectinload(PaymentOrder.plan))
            .where(
                PaymentOrder.user_id == user_id,
                PaymentOrder.status == PAYMENT_STATUS_PENDING,
                PaymentOrder.provider_trade_id.is_not(None),
            )
            .order_by(desc(PaymentOrder.created_at))
            .limit(limit)
        )
        return result.scalars().all()

    async def list_admin(self, *, search: str | None = None, limit: int = 50, offset: int = 0) -> list[PaymentOrder]:
        stmt = (
            select(PaymentOrder)
            .options(selectinload(PaymentOrder.plan), selectinload(PaymentOrder.user))
            .join(User, User.id == PaymentOrder.user_id)
            .join(Plan, Plan.id == PaymentOrder.plan_id)
            .order_by(desc(PaymentOrder.created_at))
            .limit(limit)
            .offset(offset)
        )
        if search:
            like = f"%{search.lower()}%"
            stmt = stmt.where(
                or_(
                    User.email.ilike(like),
                    Plan.code.ilike(like),
                    PaymentOrder.merchant_order_id.ilike(like),
                    PaymentOrder.provider_trade_id.ilike(like),
                )
            )
        result = await self.session.execute(stmt)
        return result.scalars().all()
