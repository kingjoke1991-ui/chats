from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session
from app.core.redis import get_redis
from app.schemas.common import HealthResponse

router = APIRouter()


@router.get("/health/live", response_model=HealthResponse)
async def live() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/health/ready", response_model=HealthResponse)
async def ready(session: AsyncSession = Depends(db_session)) -> HealthResponse:
    await session.execute(text("SELECT 1"))
    redis = get_redis()
    pong = await redis.ping()
    return HealthResponse(status="ok" if pong else "degraded")
