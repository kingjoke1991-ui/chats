from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.telegram_download_service import TelegramDownloadService
from app.services.telegram_userbot_manager import TelegramUserbotManager, get_telegram_userbot_manager

TELEGRAM_QUERY_COMMAND = "telegram_query"


@dataclass(slots=True)
class TelegramBridgeCommandResult:
    command: str
    content: str
    metadata: dict[str, Any]


class TelegramBridgeService:
    internal_model = "oracle-telegram-bridge"
    internal_provider = "internal-tool"
    internal_node_id = "telegram-bridge-command"

    def __init__(
        self,
        session: AsyncSession,
        userbot_manager: TelegramUserbotManager | None = None,
        download_service: TelegramDownloadService | None = None,
    ) -> None:
        self.session = session
        self.userbot_manager = userbot_manager or get_telegram_userbot_manager()
        self.download_service = download_service or TelegramDownloadService()

    def match_command(self, content: str) -> dict[str, str] | None:
        stripped = content.strip()
        matched = re.match(r"^#查询\s+(.+)$", stripped, flags=re.DOTALL)
        if not matched:
            return None
        query_text = matched.group(1).strip()
        if not query_text:
            return None
        return {
            "command": TELEGRAM_QUERY_COMMAND,
            "query_text": query_text,
            "bot_request_text": query_text,
        }

    async def execute(
        self,
        *,
        query_text: str,
        bot_request_text: str,
        allowed_models: list[str],
        requested_model: str | None,
    ) -> TelegramBridgeCommandResult:
        await self.userbot_manager.ensure_bridge_ready()
        bridge_reply = await self.userbot_manager.send_and_wait(bot_request_text)
        content, extra_metadata = await self._build_output(
            bridge_reply,
            allowed_models=allowed_models,
            requested_model=requested_model,
        )

        return TelegramBridgeCommandResult(
            command=TELEGRAM_QUERY_COMMAND,
            content=content,
            metadata={
                "query_text": query_text,
                "bot_request_text": bot_request_text,
                "raw_reply_text": bridge_reply["raw_text"],
                "outgoing_message_id": bridge_reply["outgoing_message_id"],
                "incoming_message_id": bridge_reply["incoming_message_id"],
                "incoming_date": bridge_reply["incoming_date"],
                "primary_message": bridge_reply.get("primary_message"),
                "all_messages": bridge_reply.get("all_messages", []),
                "used_txt_download": bridge_reply.get("used_txt_download", False),
                "downloaded_file": bridge_reply.get("downloaded_file"),
                **extra_metadata,
            },
        )

    async def _build_output(
        self,
        bridge_reply: dict[str, Any],
        *,
        allowed_models: list[str],
        requested_model: str | None,
    ) -> tuple[str, dict[str, Any]]:
        del allowed_models
        del requested_model
        downloaded_file = bridge_reply.get("downloaded_file") or {}
        raw_text = str(bridge_reply.get("raw_text") or "").strip()
        if downloaded_file and raw_text:
            download = await self.download_service.create_download(
                text=raw_text,
                file_name=downloaded_file.get("file_name"),
                mime_type=downloaded_file.get("mime_type"),
            )
            page_text = self._extract_first_page_text(bridge_reply)
            content = self._compose_text_with_download(page_text=page_text, download_url=download["url"])
            return (
                content,
                {
                    "txt_download_url": download["url"],
                    "txt_download_id": download["download_id"],
                    "txt_download_token": download["token"],
                    "txt_file_name": downloaded_file.get("file_name"),
                },
            )
        return self._format_output(bridge_reply), {}

    @staticmethod
    def _format_output(bridge_reply: dict[str, Any]) -> str:
        raw_text = str(bridge_reply.get("raw_text") or "").strip()
        if raw_text:
            return raw_text
        return json.dumps(bridge_reply.get("primary_message") or {}, ensure_ascii=False, indent=2)

    @staticmethod
    def _extract_first_page_text(bridge_reply: dict[str, Any]) -> str:
        all_messages = bridge_reply.get("all_messages") or []
        for item in all_messages:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or "").strip()
            if text:
                return text
        primary_message = bridge_reply.get("primary_message") or {}
        primary_text = str(primary_message.get("text") or "").strip()
        if primary_text:
            return primary_text
        return str(bridge_reply.get("raw_text") or "").strip()

    @staticmethod
    def _compose_text_with_download(*, page_text: str, download_url: str) -> str:
        page = page_text.strip()
        if not page:
            return f"TXT下载链接：{download_url}"
        return f"{page}\n\nTXT下载链接：{download_url}"
