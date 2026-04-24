from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user, db_session
from app.schemas.payment import CheckoutSessionRequest, CheckoutSessionResponse, PaymentOrdersResponse
from app.schemas.subscription import CurrentSubscriptionResponse, PlanListResponse
from app.schemas.user import UserRead
from app.services.payment_service import PaymentService
from app.services.subscription_service import SubscriptionService

router = APIRouter()


@router.get("/current", response_model=CurrentSubscriptionResponse)
async def current_subscription(
    user: UserRead = Depends(current_user),
    session: AsyncSession = Depends(db_session),
) -> CurrentSubscriptionResponse:
    return await SubscriptionService(session).fetch_current(user.id)


@router.get("/plans", response_model=PlanListResponse)
async def available_plans(
    _: UserRead = Depends(current_user),
    session: AsyncSession = Depends(db_session),
) -> PlanListResponse:
    return await SubscriptionService(session).list_plans()


@router.get("/orders", response_model=PaymentOrdersResponse)
async def list_orders(
    user: UserRead = Depends(current_user),
    session: AsyncSession = Depends(db_session),
) -> PaymentOrdersResponse:
    return await PaymentService(session).list_orders_for_user(user.id)


@router.post("/orders/sync", response_model=PaymentOrdersResponse)
async def sync_orders(
    user: UserRead = Depends(current_user),
    session: AsyncSession = Depends(db_session),
) -> PaymentOrdersResponse:
    return await PaymentService(session).sync_pending_orders_for_user(user.id)


@router.post("/checkout-session", response_model=CheckoutSessionResponse)
async def checkout_session(
    payload: CheckoutSessionRequest,
    user: UserRead = Depends(current_user),
    session: AsyncSession = Depends(db_session),
) -> CheckoutSessionResponse:
    return await PaymentService(session).create_checkout_session(user_id=user.id, plan_code=payload.plan_code)
