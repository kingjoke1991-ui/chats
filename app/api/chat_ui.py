from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, RedirectResponse

router = APIRouter()
CHAT_HTML = Path(__file__).resolve().parents[1] / "static" / "chat.html"


@router.get("/", include_in_schema=False)
async def chat_root() -> RedirectResponse:
    return RedirectResponse(url="/chat", status_code=307)


@router.get("/chat", include_in_schema=False)
@router.get("/chat/", include_in_schema=False)
async def chat_ui() -> FileResponse:
    return FileResponse(CHAT_HTML)
