from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import AUTH_SESSION_ACTIVE, SUBSCRIPTION_ACTIVE, USER_STATUS_ACTIVE
from app.core.config import settings
from app.core.exceptions import AppException
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from app.models.auth_session import AuthSession
from app.models.subscription import Subscription
from app.models.user import User
from app.repos.auth_session_repo import AuthSessionRepo
from app.repos.plan_repo import PlanRepo
from app.repos.subscription_repo import SubscriptionRepo
from app.repos.user_repo import UserRepo
from app.schemas.auth import AuthResponse, LoginRequest, TokenPair, TokenRefreshResponse, UserRegisterRequest
from app.schemas.subscription import PlanRead, SubscriptionRead
from app.schemas.user import UserRead


class AuthService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.users = UserRepo(session)
        self.auth_sessions = AuthSessionRepo(session)
        self.plans = PlanRepo(session)
        self.subscriptions = SubscriptionRepo(session)

    async def register(self, payload: UserRegisterRequest, user_agent: str | None, ip_address: str | None) -> AuthResponse:
        existing_user = await self.users.get_by_email(payload.email)
        if existing_user:
            raise AppException(status.HTTP_409_CONFLICT, "EMAIL_ALREADY_EXISTS", "email already exists")

        free_plan = await self.plans.get_by_code(settings.default_free_plan_code)
        if not free_plan:
            raise AppException(status.HTTP_500_INTERNAL_SERVER_ERROR, "PLAN_NOT_FOUND", "default free plan is missing")

        username = await self._generate_username(payload.email)
        user = await self.users.create(
            User(
                email=payload.email,
                username=username,
                password_hash=hash_password(payload.password),
                status=USER_STATUS_ACTIVE,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        subscription = await self.subscriptions.create(
            Subscription(
                user_id=user.id,
                plan_id=free_plan.id,
                provider="manual",
                status=SUBSCRIPTION_ACTIVE,
                start_at=datetime.now(UTC),
                end_at=datetime.now(UTC) + timedelta(days=3650),
                cancel_at_period_end=False,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        tokens = await self._issue_tokens(user.id, user_agent, ip_address)
        await self.session.commit()
        await self.session.refresh(user)
        return self._build_auth_response(user, subscription, free_plan, tokens)

    async def login(self, payload: LoginRequest, user_agent: str | None, ip_address: str | None) -> AuthResponse:
        user = await self.users.get_by_email(payload.email)
        if not user or not verify_password(payload.password, user.password_hash):
            raise AppException(status.HTTP_401_UNAUTHORIZED, "AUTH_REQUIRED", "invalid credentials")
        if user.status != USER_STATUS_ACTIVE:
            raise AppException(status.HTTP_403_FORBIDDEN, "USER_DISABLED", "user is not active")

        subscription = await self.subscriptions.get_current_for_user(user.id)
        if not subscription:
            raise AppException(status.HTTP_403_FORBIDDEN, "SUBSCRIPTION_REQUIRED", "subscription not found")

        user.last_login_at = datetime.now(UTC)
        tokens = await self._issue_tokens(user.id, user_agent, ip_address)
        await self.session.commit()
        await self.session.refresh(user)
        return self._build_auth_response(user, subscription, subscription.plan, tokens)

    async def refresh(
        self,
        refresh_token: str,
        user_agent: str | None,
        ip_address: str | None,
    ) -> TokenRefreshResponse:
        payload = decode_token(refresh_token, "refresh")
        auth_session = await self.auth_sessions.get_active(payload["sid"])
        if not auth_session or auth_session.user_id != payload["sub"]:
            raise AppException(status.HTTP_401_UNAUTHORIZED, "AUTH_REQUIRED", "session is invalid")
        if auth_session.refresh_token_hash != hash_refresh_token(refresh_token):
            raise AppException(status.HTTP_401_UNAUTHORIZED, "AUTH_REQUIRED", "session token mismatch")

        await self.auth_sessions.revoke(auth_session)
        tokens = await self._issue_tokens(payload["sub"], user_agent, ip_address)
        await self.session.commit()
        return TokenRefreshResponse(tokens=tokens)

    async def logout(self, refresh_token: str) -> None:
        payload = decode_token(refresh_token, "refresh")
        auth_session = await self.auth_sessions.get_active(payload["sid"])
        if auth_session:
            await self.auth_sessions.revoke(auth_session)
            await self.session.commit()

    async def get_current_user(self, access_token: str) -> UserRead:
        payload = decode_token(access_token, "access")
        user = await self.users.get_by_id(payload["sub"])
        if not user:
            raise AppException(status.HTTP_401_UNAUTHORIZED, "AUTH_REQUIRED", "user not found")
        if user.status != USER_STATUS_ACTIVE:
            raise AppException(status.HTTP_403_FORBIDDEN, "USER_DISABLED", "user is not active")
        return UserRead.model_validate(user, from_attributes=True)

    async def ensure_admin_bootstrap(self) -> None:
        if not settings.admin_bootstrap_email or not settings.admin_bootstrap_password:
            return
        user = await self.users.get_by_email(settings.admin_bootstrap_email)
        if user:
            changed = False
            if not user.is_admin:
                user.is_admin = True
                changed = True
            if not verify_password(settings.admin_bootstrap_password, user.password_hash):
                user.password_hash = hash_password(settings.admin_bootstrap_password)
                changed = True
            if changed:
                user.updated_at = datetime.now(UTC)
                await self.session.commit()
            return

        free_plan = await self.plans.get_by_code(settings.default_free_plan_code)
        if not free_plan:
            raise AppException(status.HTTP_500_INTERNAL_SERVER_ERROR, "PLAN_NOT_FOUND", "default free plan is missing")

        now = datetime.now(UTC)
        username = await self._generate_username(settings.admin_bootstrap_email)
        user = await self.users.create(
            User(
                email=settings.admin_bootstrap_email,
                username=username,
                password_hash=hash_password(settings.admin_bootstrap_password),
                status=USER_STATUS_ACTIVE,
                is_admin=True,
                created_at=now,
                updated_at=now,
            )
        )
        await self.subscriptions.create(
            Subscription(
                user_id=user.id,
                plan_id=free_plan.id,
                provider="manual",
                status=SUBSCRIPTION_ACTIVE,
                start_at=now,
                end_at=now + timedelta(days=3650),
                cancel_at_period_end=False,
                created_at=now,
                updated_at=now,
            )
        )
        await self.session.commit()

    async def _generate_username(self, email: str) -> str:
        base = email.split("@", 1)[0][:24]
        candidate = base
        index = 1
        while await self.users.get_by_username(candidate):
            index += 1
            candidate = f"{base[:20]}{index}"
        return candidate

    async def _issue_tokens(self, user_id: str, user_agent: str | None, ip_address: str | None) -> TokenPair:
        session_id = str(uuid4())
        access_token, access_expires = create_access_token(user_id, session_id)
        refresh_token, refresh_expires = create_refresh_token(user_id, session_id)
        await self.auth_sessions.create(
            AuthSession(
                id=session_id,
                user_id=user_id,
                refresh_token_hash=hash_refresh_token(refresh_token),
                user_agent=user_agent,
                ip_address=ip_address,
                status=AUTH_SESSION_ACTIVE,
                expires_at=refresh_expires,
                created_at=datetime.now(UTC),
            )
        )
        return TokenPair(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=int((access_expires - datetime.now(UTC)).total_seconds()),
        )

    def _build_auth_response(
        self,
        user: User,
        subscription: Subscription,
        plan,
        tokens: TokenPair,
    ) -> AuthResponse:
        return AuthResponse(
            user=UserRead.model_validate(user, from_attributes=True),
            tokens=tokens,
            subscription=SubscriptionRead.model_validate(subscription, from_attributes=True),
            plan=PlanRead.model_validate(plan, from_attributes=True),
        )
