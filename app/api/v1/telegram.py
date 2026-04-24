from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Query
from fastapi.responses import Response

from app.services.telegram_download_service import TelegramDownloadService

router = APIRouter()


@router.get("/downloads/{download_id}")
async def download_telegram_export(
    download_id: str,
    token: str = Query(..., min_length=1),
) -> Response:
    payload = await TelegramDownloadService().get_download(download_id=download_id, token=token)
    file_name = payload["file_name"]
    encoded_file_name = quote(file_name)
    return Response(
        content=payload["text"],
        media_type=payload["mime_type"],
        headers={
            "Content-Disposition": (
                f'attachment; filename="{file_name}"; filename*=UTF-8\'\'{encoded_file_name}'
            )
        },
    )
