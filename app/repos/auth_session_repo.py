from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import AUTH_SESSION_REVOKED
from app.models.auth_session import AuthSession


class AuthSessionRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, auth_session: AuthSession) -> AuthSession:
        self.session.add(auth_session)
        await self.session.flush()
        await self.session.refresh(auth_session)
        return auth_session

    async def get_active(self, session_id: str) -> AuthSession | None:
        result = await self.session.execute(select(AuthSession).where(AuthSession.id == session_id))
        auth_session = result.scalar_one_or_none()
        if not auth_session:
            return None
        if auth_session.status != "active" or auth_session.expires_at <= datetime.now(UTC):
            return None
        return auth_session

    async def revoke(self, auth_session: AuthSession) -> None:
        auth_session.status = AUTH_SESSION_REVOKED
        auth_session.revoked_at = datetime.now(UTC)
        await self.session.flush()
