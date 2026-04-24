from collections.abc import AsyncGenerator

from fastapi import Depends
from fastapi import status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db_session
from app.core.exceptions import AppException
from app.schemas.user import UserRead
from app.services.auth_service import AuthService

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/v1/auth/login")


async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async for session in get_db_session():
        yield session


async def current_user(
    token: str = Depends(oauth2_scheme),
    session: AsyncSession = Depends(db_session),
) -> UserRead:
    return await AuthService(session).get_current_user(token)


async def current_admin(user: UserRead = Depends(current_user)) -> UserRead:
    if not user.is_admin:
        raise AppException(status.HTTP_403_FORBIDDEN, "ADMIN_REQUIRED", "admin access required")
    return user
