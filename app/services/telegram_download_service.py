from __future__ import annotations

import json
import secrets
from uuid import uuid4

from redis.asyncio import Redis

from app.core.config import settings
from app.core.exceptions import AppException
from app.core.redis import get_redis


class TelegramDownloadService:
    def __init__(self, redis_client: Redis | None = None) -> None:
        self.redis = redis_client or get_redis()

    async def create_download(
        self,
        *,
        text: str,
        file_name: str | None,
        mime_type: str | None,
    ) -> dict[str, str]:
        download_id = uuid4().hex
        token = secrets.token_urlsafe(24)
        payload = {
            "token": token,
            "text": text,
            "file_name": file_name or "telegram-export.txt",
            "mime_type": mime_type or "text/plain; charset=utf-8",
        }
        await self.redis.set(
            self._download_key(download_id),
            json.dumps(payload, ensure_ascii=False),
            ex=settings.telegram_bridge_download_ttl_seconds,
        )
        return {
            "download_id": download_id,
            "token": token,
            "url": (
                f"{settings.resolved_public_base_url}/v1/telegram/downloads/{download_id}"
                f"?token={token}"
            ),
        }

    async def get_download(self, *, download_id: str, token: str) -> dict[str, str]:
        raw = await self.redis.get(self._download_key(download_id))
        if not raw:
            raise AppException(404, "TELEGRAM_DOWNLOAD_NOT_FOUND", "download not found or expired")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AppException(500, "TELEGRAM_DOWNLOAD_INVALID", "download payload is invalid") from exc
        if payload.get("token") != token:
            raise AppException(403, "TELEGRAM_DOWNLOAD_FORBIDDEN", "invalid download token")
        return payload

    @staticmethod
    def _download_key(download_id: str) -> str:
        return f"chat_oracle:telegram:download:{download_id}"
