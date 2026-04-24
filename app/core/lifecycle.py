from __future__ import annotations

from sqlalchemy import text

from app.core.db import SessionLocal
from app.core.redis import get_redis
from app.services.auth_service import AuthService
from app.services.model_node_service import ModelNodeService
from app.services.telegram_userbot_manager import get_telegram_userbot_manager


async def app_startup_check() -> None:
    async with SessionLocal() as session:
        await session.execute(text("SELECT 1"))
        await AuthService(session).ensure_admin_bootstrap()
        await ModelNodeService(session).sync_defaults_and_healthcheck()
    await get_redis().ping()
    await get_telegram_userbot_manager().start()


async def app_shutdown() -> None:
    await get_telegram_userbot_manager().stop()
    await get_redis().aclose()
