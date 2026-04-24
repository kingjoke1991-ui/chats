from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.models.conversation import Conversation
from app.repos.conversation_repo import ConversationRepo
from app.repos.message_repo import MessageRepo
from app.schemas.conversation import (
    ConversationCreateRequest,
    ConversationListResponse,
    ConversationMessagesResponse,
    ConversationRead,
    ConversationUpdateRequest,
    MessageRead,
)


class ConversationService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.conversations = ConversationRepo(session)
        self.messages = MessageRepo(session)

    async def list_for_user(self, user_id: str, *, limit: int = 50, offset: int = 0) -> ConversationListResponse:
        items = await self.conversations.list_for_user(user_id, limit=limit, offset=offset)
        return ConversationListResponse(
            items=[ConversationRead.model_validate(item, from_attributes=True) for item in items],
            total=len(items),
        )

    async def create_for_user(self, user_id: str, payload: ConversationCreateRequest) -> ConversationRead:
        now = datetime.now(UTC)
        conversation = await self.conversations.create(
            Conversation(
                user_id=user_id,
                title=payload.title,
                latest_message_at=now,
                message_count=0,
                created_at=now,
                updated_at=now,
            )
        )
        await self.session.commit()
        return ConversationRead.model_validate(conversation, from_attributes=True)

    async def get_for_user(self, user_id: str, conversation_id: str) -> ConversationRead:
        conversation = await self._require_user_conversation(user_id, conversation_id)
        return ConversationRead.model_validate(conversation, from_attributes=True)

    async def get_messages_for_user(self, user_id: str, conversation_id: str) -> ConversationMessagesResponse:
        conversation = await self._require_user_conversation(user_id, conversation_id)
        messages = await self.messages.list_for_conversation(conversation_id)
        return ConversationMessagesResponse(
            conversation=ConversationRead.model_validate(conversation, from_attributes=True),
            messages=[MessageRead.model_validate(message, from_attributes=True) for message in messages],
        )

    async def update_for_user(
        self,
        user_id: str,
        conversation_id: str,
        payload: ConversationUpdateRequest,
    ) -> ConversationRead:
        conversation = await self._require_user_conversation(user_id, conversation_id)
        if payload.title is not None:
            conversation.title = payload.title
        if payload.pinned is not None:
            conversation.pinned = payload.pinned
        if payload.archived is not None:
            conversation.archived = payload.archived
        conversation.updated_at = datetime.now(UTC)
        await self.conversations.update(conversation)
        await self.session.commit()
        return ConversationRead.model_validate(conversation, from_attributes=True)

    async def delete_for_user(self, user_id: str, conversation_id: str) -> None:
        conversation = await self._require_user_conversation(user_id, conversation_id)
        await self.conversations.soft_delete(conversation, datetime.now(UTC))
        await self.session.commit()

    async def _require_user_conversation(self, user_id: str, conversation_id: str) -> Conversation:
        conversation = await self.conversations.get_for_user(conversation_id, user_id)
        if not conversation:
            raise AppException(404, "CONVERSATION_NOT_FOUND", "conversation not found")
        return conversation
