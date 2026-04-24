from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr

from app.schemas.subscription import PlanRead, SubscriptionRead


class UserRead(BaseModel):
    id: str
    email: EmailStr
    username: Optional[str]
    status: str
    is_admin: bool
    email_verified: bool
    timezone: Optional[str]
    locale: Optional[str]
    created_at: datetime
    updated_at: datetime


class MeResponse(BaseModel):
    user: UserRead
    subscription: SubscriptionRead
    plan: PlanRead
