from fastapi import APIRouter, Depends

from app.api.deps import current_user, db_session
from app.schemas.user import MeResponse, UserRead
from app.services.subscription_service import SubscriptionService

from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


@router.get("/me", response_model=MeResponse)
async def me(
    user: UserRead = Depends(current_user),
    session: AsyncSession = Depends(db_session),
) -> MeResponse:
    subscription = await SubscriptionService(session).fetch_current(user.id)
    return MeResponse(user=user, subscription=subscription.subscription, plan=subscription.plan)
