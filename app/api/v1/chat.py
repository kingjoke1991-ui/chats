from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user, db_session
from app.schemas.chat import ChatCompletionRequest, ChatCompletionResponse
from app.schemas.user import UserRead
from app.services.chat_service import ChatService

router = APIRouter()

@router.post("/completions")
async def create_chat_completion(
    payload: ChatCompletionRequest,
    user: UserRead = Depends(current_user),
    session: AsyncSession = Depends(db_session),
):
    if payload.stream:
        return StreamingResponse(
            ChatService(session).create_completion_stream(user_id=user.id, payload=payload),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    return await ChatService(session).create_completion(user_id=user.id, payload=payload)
