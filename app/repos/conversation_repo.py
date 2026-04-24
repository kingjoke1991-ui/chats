from __future__ import annotations

from datetime import datetime

from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.conversation import Conversation
from app.models.user import User


class ConversationRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, conversation: Conversation) -> Conversation:
        self.session.add(conversation)
        await self.session.flush()
        return conversation

    async def get_for_user(self, conversation_id: str, user_id: str) -> Conversation | None:
        result = await self.session.execute(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.user_id == user_id,
                Conversation.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def touch(
        self,
        conversation: Conversation,
        latest_message_at: datetime,
        latest_model: str,
        message_increment: int,
    ) -> Conversation:
        conversation.latest_message_at = latest_message_at
        conversation.latest_model = latest_model
        conversation.message_count += message_increment
        await self.session.flush()
        return conversation

    async def list_for_user(self, user_id: str, *, limit: int = 50, offset: int = 0) -> list[Conversation]:
        result = await self.session.execute(
            select(Conversation)
            .where(
                Conversation.user_id == user_id,
                Conversation.deleted_at.is_(None),
            )
            .order_by(desc(Conversation.latest_message_at))
            .limit(limit)
            .offset(offset)
        )
        return result.scalars().all()

    async def get_by_id(self, conversation_id: str) -> Conversation | None:
        result = await self.session.execute(select(Conversation).where(Conversation.id == conversation_id))
        return result.scalar_one_or_none()

    async def update(self, conversation: Conversation) -> Conversation:
        await self.session.flush()
        return conversation

    async def soft_delete(self, conversation: Conversation, deleted_at: datetime) -> Conversation:
        conversation.deleted_at = deleted_at
        conversation.updated_at = deleted_at
        await self.session.flush()
        return conversation

    async def list_admin(
        self,
        *,
        search: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Conversation]:
        stmt = (
            select(Conversation)
            .options(selectinload(Conversation.user))
            .join(User, User.id == Conversation.user_id)
            .where(Conversation.deleted_at.is_(None))
            .order_by(desc(Conversation.latest_message_at))
            .limit(limit)
            .offset(offset)
        )
        if search:
            like = f"%{search.lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(User.email).like(like),
                    func.lower(Conversation.title).like(like),
                )
            )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def count_all(self) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(Conversation).where(Conversation.deleted_at.is_(None))
        )
        return int(result.scalar_one())
