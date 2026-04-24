from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session
from app.core.exceptions import AppException
from app.services.payment_service import PaymentService

router = APIRouter()


@router.post("/webhook/bepusdt", include_in_schema=False)
async def bepusdt_webhook(
    request: Request,
    session: AsyncSession = Depends(db_session),
) -> PlainTextResponse:
    try:
        payload = await request.json()
    except ValueError:
        return PlainTextResponse("fail", status_code=400)
    try:
        result = await PaymentService(session).handle_bepusdt_webhook(payload)
    except AppException:
        return PlainTextResponse("fail", status_code=400)
    return PlainTextResponse(result)
