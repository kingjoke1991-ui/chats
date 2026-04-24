from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user, db_session
from app.schemas.conversation import (
    ConversationCreateRequest,
    ConversationListResponse,
    ConversationMessagesResponse,
    ConversationRead,
    ConversationUpdateRequest,
)
from app.schemas.user import UserRead
from app.services.conversation_service import ConversationService

router = APIRouter()


@router.get("", response_model=ConversationListResponse)
async def list_conversations(
    user: UserRead = Depends(current_user),
    session: AsyncSession = Depends(db_session),
) -> ConversationListResponse:
    return await ConversationService(session).list_for_user(user.id)


@router.post("", response_model=ConversationRead, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    payload: ConversationCreateRequest,
    user: UserRead = Depends(current_user),
    session: AsyncSession = Depends(db_session),
) -> ConversationRead:
    return await ConversationService(session).create_for_user(user.id, payload)


@router.get("/{conversation_id}", response_model=ConversationRead)
async def get_conversation(
    conversation_id: str,
    user: UserRead = Depends(current_user),
    session: AsyncSession = Depends(db_session),
) -> ConversationRead:
    return await ConversationService(session).get_for_user(user.id, conversation_id)


@router.get("/{conversation_id}/messages", response_model=ConversationMessagesResponse)
async def get_conversation_messages(
    conversation_id: str,
    user: UserRead = Depends(current_user),
    session: AsyncSession = Depends(db_session),
) -> ConversationMessagesResponse:
    return await ConversationService(session).get_messages_for_user(user.id, conversation_id)


@router.patch("/{conversation_id}", response_model=ConversationRead)
async def update_conversation(
    conversation_id: str,
    payload: ConversationUpdateRequest,
    user: UserRead = Depends(current_user),
    session: AsyncSession = Depends(db_session),
) -> ConversationRead:
    return await ConversationService(session).update_for_user(user.id, conversation_id, payload)


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: str,
    user: UserRead = Depends(current_user),
    session: AsyncSession = Depends(db_session),
) -> Response:
    await ConversationService(session).delete_for_user(user.id, conversation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
