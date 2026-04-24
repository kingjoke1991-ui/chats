from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.core.constants import PAYMENT_PROVIDER_BEPUSDT, SUBSCRIPTION_ACTIVE
from app.models.subscription import Subscription
from app.repos.plan_repo import PlanRepo
from app.repos.subscription_repo import SubscriptionRepo
from app.schemas.subscription import CurrentSubscriptionResponse, PlanListResponse, PlanRead, SubscriptionRead


class SubscriptionService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.plans = PlanRepo(session)
        self.subscriptions = SubscriptionRepo(session)

    async def fetch_current(self, user_id: str) -> CurrentSubscriptionResponse:
        subscription = await self.subscriptions.get_current_for_user(user_id)
        if not subscription:
            raise AppException(404, "SUBSCRIPTION_REQUIRED", "subscription not found")
        return CurrentSubscriptionResponse(
            subscription=SubscriptionRead.model_validate(subscription, from_attributes=True),
            plan=PlanRead.model_validate(subscription.plan, from_attributes=True),
        )

    async def list_plans(self) -> PlanListResponse:
        plans = await self.plans.list_active()
        return PlanListResponse(items=[PlanRead.model_validate(plan, from_attributes=True) for plan in plans])

    async def activate_plan_after_payment(
        self,
        *,
        user_id: str,
        plan_id: str,
        provider_subscription_id: str,
        period_days: int,
    ) -> Subscription:
        plan = await self.plans.get_by_id(plan_id)
        if not plan:
            raise AppException(404, "PLAN_NOT_FOUND", "plan not found")

        now = datetime.now(UTC)
        current_subscriptions = await self.subscriptions.list_current_for_user(user_id)
        same_plan = next((item for item in current_subscriptions if item.plan_id == plan_id), None)
        start_at = max(now, same_plan.end_at) if same_plan else now
        subscription = await self.subscriptions.create(
            Subscription(
                user_id=user_id,
                plan_id=plan_id,
                provider=PAYMENT_PROVIDER_BEPUSDT,
                provider_subscription_id=provider_subscription_id,
                status=SUBSCRIPTION_ACTIVE,
                start_at=start_at,
                end_at=start_at + timedelta(days=period_days),
                cancel_at_period_end=False,
                created_at=now,
                updated_at=now,
            )
        )
        await self.session.flush()
        return subscription
