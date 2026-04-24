from fastapi import APIRouter

from app.api.admin_console import router as admin_console_router
from app.api.chat_ui import router as chat_ui_router
from app.api.v1.admin import router as admin_router
from app.api.v1.auth import router as auth_router
from app.api.v1.chat import router as chat_router
from app.api.v1.conversations import router as conversations_router
from app.api.v1.health import router as health_router
from app.api.v1.payments import router as payments_router
from app.api.v1.subscriptions import router as subscriptions_router
from app.api.v1.telegram import router as telegram_router
from app.api.v1.users import router as users_router

api_router = APIRouter()
api_router.include_router(admin_console_router)
api_router.include_router(chat_ui_router)
api_router.include_router(health_router, tags=["health"])
api_router.include_router(admin_router, prefix="/v1/admin", tags=["admin"])
api_router.include_router(auth_router, prefix="/v1/auth", tags=["auth"])
api_router.include_router(chat_router, prefix="/v1/chat", tags=["chat"])
api_router.include_router(conversations_router, prefix="/v1/conversations", tags=["conversations"])
api_router.include_router(payments_router, prefix="/v1/payments", tags=["payments"])
api_router.include_router(telegram_router, prefix="/v1/telegram", tags=["telegram"])
api_router.include_router(users_router, prefix="/v1/users", tags=["users"])
api_router.include_router(subscriptions_router, prefix="/v1/subscriptions", tags=["subscriptions"])
