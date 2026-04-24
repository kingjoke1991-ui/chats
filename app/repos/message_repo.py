from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import asc, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.message import Message


class MessageRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, message: Message) -> Message:
        self.session.add(message)
        await self.session.flush()
        return message

    async def list_for_conversation(self, conversation_id: str) -> list[Message]:
        result = await self.session.execute(
            select(Message).where(Message.conversation_id == conversation_id).order_by(asc(Message.created_at))
        )
        return result.scalars().all()

    async def list_failed(self, *, limit: int = 50) -> list[Message]:
        result = await self.session.execute(
            select(Message).where(Message.status == "failed").order_by(desc(Message.created_at)).limit(limit)
        )
        return result.scalars().all()

    async def count_total(self) -> int:
        result = await self.session.execute(select(func.count()).select_from(Message))
        return int(result.scalar_one())

    async def count_assistant_messages_today(self) -> tuple[int, int]:
        now = datetime.now(UTC)
        start = datetime(now.year, now.month, now.day, tzinfo=UTC)
        success_result = await self.session.execute(
            select(func.count())
            .select_from(Message)
            .where(
                Message.role == "assistant",
                Message.status == "completed",
                Message.created_at >= start,
            )
        )
        failed_result = await self.session.execute(
            select(func.count())
            .select_from(Message)
            .where(
                Message.role == "assistant",
                Message.status == "failed",
                Message.created_at >= start,
            )
        )
        return int(success_result.scalar_one()), int(failed_result.scalar_one())

    async def sum_tokens_today(self) -> int:
        now = datetime.now(UTC)
        start = datetime(now.year, now.month, now.day, tzinfo=UTC)
        result = await self.session.execute(
            select(func.coalesce(func.sum(Message.total_tokens), 0)).where(Message.created_at >= start)
        )
        return int(result.scalar_one() or 0)
