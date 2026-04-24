from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field

from app.schemas.subscription import PlanRead, SubscriptionRead
from app.schemas.user import UserRead


class UserRegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class AuthResponse(BaseModel):
    user: UserRead
    tokens: TokenPair
    subscription: SubscriptionRead
    plan: PlanRead


class TokenRefreshResponse(BaseModel):
    tokens: TokenPair
