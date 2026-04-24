from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter()
ADMIN_HTML = Path(__file__).resolve().parents[1] / "templates" / "admin.html"


@router.get("/admin", include_in_schema=False)
@router.get("/admin/", include_in_schema=False)
async def admin_console() -> FileResponse:
    return FileResponse(ADMIN_HTML)
