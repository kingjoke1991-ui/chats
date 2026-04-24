from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.plan import Plan
from app.models.subscription import Subscription


class SubscriptionRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, subscription: Subscription) -> Subscription:
        self.session.add(subscription)
        await self.session.flush()
        await self.session.refresh(subscription)
        return subscription

    async def get_current_for_user(self, user_id: str) -> Subscription | None:
        now = datetime.now(UTC)
        result = await self.session.execute(
            select(Subscription)
            .options(selectinload(Subscription.plan))
            .join(Plan, Plan.id == Subscription.plan_id)
            .where(
                Subscription.user_id == user_id,
                Subscription.start_at <= now,
                Subscription.end_at >= now,
            )
            .order_by(desc(Plan.priority_level), desc(Subscription.end_at), desc(Subscription.created_at))
        )
        return result.scalars().first()

    async def count_active(self) -> int:
        now = datetime.now(UTC)
        result = await self.session.execute(
            select(func.count()).select_from(Subscription).where(
                Subscription.start_at <= now,
                Subscription.end_at >= now,
            )
        )
        return int(result.scalar_one())

    async def list_current_for_user(self, user_id: str) -> list[Subscription]:
        now = datetime.now(UTC)
        result = await self.session.execute(
            select(Subscription)
            .options(selectinload(Subscription.plan))
            .join(Plan, Plan.id == Subscription.plan_id)
            .where(
                Subscription.user_id == user_id,
                Subscription.start_at <= now,
                Subscription.end_at >= now,
            )
            .order_by(desc(Plan.priority_level), desc(Subscription.end_at), desc(Subscription.created_at))
        )
        return result.scalars().all()
