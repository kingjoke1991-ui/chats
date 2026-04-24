from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
import re
from typing import Any

import httpx
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon import functions
from telethon.errors import UserAlreadyParticipantError
from telethon.tl.types import Channel

from app.core.config import settings
from app.core.exceptions import AppException


class TelegramUserbotManager:
    def __init__(self) -> None:
        self._client: TelegramClient | None = None
        self._started = False
        self._available = False
        self._last_error: str = ""
        self._lock = asyncio.Lock()
        self._prepared_target = False
        self._prepared_peers: set[str] = set()

    async def start(self) -> None:
        if self._started:
            return
        self._started = True

        if not settings.telegram_bridge_enabled:
            self._last_error = "Telegram bridge is not configured."
            return

        try:
            session = self._build_session()
            self._client = TelegramClient(
                session,
                settings.telegram_bridge_api_id,
                settings.telegram_bridge_api_hash,
            )
            await self._client.connect()
            if not await self._client.is_user_authorized():
                raise RuntimeError(
                    "Telegram userbot session is not authorized. Provide a valid session string or session file."
                )
            self._available = True
            self._last_error = ""
        except Exception as exc:
            self._available = False
            self._last_error = str(exc)
            if self._client:
                await self._client.disconnect()
                self._client = None

    async def stop(self) -> None:
        if self._client:
            await self._client.disconnect()
        self._client = None
        self._available = False
        self._started = False
        self._prepared_target = False
        self._prepared_peers.clear()

    async def send_and_wait(self, text: str) -> dict[str, Any]:
        client = await self._require_client()
        async with self._lock:
            async with client.conversation(
                settings.telegram_bridge_target_bot_username,
                timeout=settings.telegram_bridge_request_timeout_seconds,
            ) as conversation:
                outgoing = await conversation.send_message(text)
                first_incoming = await conversation.get_response()
                responses = [first_incoming]
                responses = await self._collect_followup_updates(
                    conversation=conversation,
                    messages=responses,
                )
                selected = await self._select_response_result(
                    client=client,
                    conversation=conversation,
                    messages=responses,
                )

        selected_message = selected["message"]
        response_messages = selected.get("messages", responses)
        primary_message = self._serialize_message(selected_message)
        downloaded_file = selected.get("downloaded_file")
        final_text = downloaded_file["text"] if downloaded_file else primary_message["text"]

        return {
            "request_text": text,
            "raw_text": final_text,
            "outgoing_message_id": outgoing.id,
            "incoming_message_id": getattr(selected_message, "id", None),
            "incoming_date": primary_message["date"],
            "primary_message": primary_message,
            "all_messages": [self._serialize_message(message) for message in response_messages],
            "used_txt_download": bool(downloaded_file),
            "downloaded_file": downloaded_file,
        }

    async def ensure_bridge_ready(self) -> None:
        client = await self._require_client()
        async with self._lock:
            for peer in self._required_peers():
                normalized_peer = self._normalize_peer(peer)
                if normalized_peer in self._prepared_peers:
                    continue
                entity = await client.get_entity(normalized_peer)
                if isinstance(entity, Channel):
                    try:
                        await client(functions.channels.JoinChannelRequest(channel=entity))
                    except UserAlreadyParticipantError:
                        pass
                self._prepared_peers.add(normalized_peer)

            if not self._prepared_target:
                await client.get_entity(self._target_bot())
                bootstrap_message = settings.telegram_bridge_bootstrap_start_message.strip()
                if bootstrap_message:
                    await client.send_message(self._target_bot(), bootstrap_message)
                self._prepared_target = True

    async def _require_client(self) -> TelegramClient:
        if not settings.telegram_bridge_enabled:
            raise AppException(
                503,
                "TELEGRAM_BRIDGE_NOT_CONFIGURED",
                "Telegram bridge 未配置，请补充 api_id、api_hash、session 和目标机器人用户名。",
            )
        if not self._started:
            await self.start()
        if not self._available or not self._client:
            detail = self._last_error or "Telegram userbot is unavailable."
            raise AppException(503, "TELEGRAM_BRIDGE_UNAVAILABLE", detail)
        return self._client

    def _build_session(self) -> StringSession | str:
        if settings.telegram_bridge_session_string:
            return StringSession(settings.telegram_bridge_session_string)
        if settings.telegram_bridge_session_file:
            return str(Path(settings.telegram_bridge_session_file))
        raise RuntimeError("Telegram bridge session is missing.")

    @staticmethod
    def _normalize_peer(value: str) -> str:
        normalized = value.strip()
        if not normalized:
            return normalized
        return normalized if normalized.startswith("@") else f"@{normalized}"

    @staticmethod
    def _required_peers() -> list[str]:
        peers: list[str] = []
        for item in settings.telegram_bridge_required_peers.split(","):
            normalized = TelegramUserbotManager._normalize_peer(item)
            if normalized:
                peers.append(normalized)
        return peers

    @staticmethod
    def _target_bot() -> str:
        return TelegramUserbotManager._normalize_peer(settings.telegram_bridge_target_bot_username or "")

    async def _maybe_download_text_file(
        self,
        *,
        client: TelegramClient,
        conversation: Any,
        message: Any,
        captured_messages: list[Any] | None = None,
    ) -> dict[str, Any] | None:
        if self._is_text_file_message(message):
            return await self._download_text_file(client=client, message=message)

        direct_url = self._extract_text_url_from_message(message)
        if direct_url:
            downloaded = await self._download_text_url(direct_url)
            downloaded["source_message"] = self._serialize_message(message)
            return downloaded

        button = self._find_export_button(message)
        if button is None:
            return None

        button_url = getattr(button, "url", None)
        if button_url:
            downloaded = await self._download_text_url(button_url)
            downloaded["source_message"] = self._serialize_message(message)
            return downloaded

        click_result = await button.click()
        click_url = self._extract_text_url_from_click_result(click_result)
        if click_url:
            downloaded = await self._download_text_url(click_url)
            downloaded["source_message"] = self._serialize_message(message)
            return downloaded

        updates = await self._collect_followup_updates(
            conversation=conversation,
            messages=[message],
            idle_timeout=min(30, settings.telegram_bridge_request_timeout_seconds),
            max_events=12,
        )
        if captured_messages is not None:
            for update in updates:
                self._merge_message_in_place(captured_messages, update)
        for followup in updates:
            if self._is_text_file_message(followup):
                downloaded = await self._download_text_file(client=client, message=followup)
                downloaded["source_message"] = self._serialize_message(followup)
                return downloaded
            followup_url = self._extract_text_url_from_message(followup)
            if followup_url:
                downloaded = await self._download_text_url(followup_url)
                downloaded["source_message"] = self._serialize_message(followup)
                return downloaded

        polled_messages = await self._poll_export_messages(client=client, source_message=message)
        if captured_messages is not None:
            for update in polled_messages:
                self._merge_message_in_place(captured_messages, update)
        for followup in polled_messages:
            if self._is_text_file_message(followup):
                downloaded = await self._download_text_file(client=client, message=followup)
                downloaded["source_message"] = self._serialize_message(followup)
                return downloaded
            followup_url = self._extract_text_url_from_message(followup)
            if followup_url:
                downloaded = await self._download_text_url(followup_url)
                downloaded["source_message"] = self._serialize_message(followup)
                return downloaded

        return None

    async def _collect_followup_updates(
        self,
        *,
        conversation: Any,
        messages: list[Any],
        idle_timeout: int | None = None,
        max_events: int = 8,
    ) -> list[Any]:
        collected = list(messages)
        wait_timeout = idle_timeout or min(3, settings.telegram_bridge_request_timeout_seconds)
        for _ in range(max_events):
            response_task = asyncio.create_task(conversation.get_response(timeout=wait_timeout))
            edit_task = asyncio.create_task(conversation.get_edit(timeout=wait_timeout))
            done, pending = await asyncio.wait(
                {response_task, edit_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            event_task = next(iter(done))
            try:
                event_message = await event_task
            except TimeoutError:
                break
            collected = self._merge_message(collected, event_message)
        return collected

    @staticmethod
    def _merge_message(messages: list[Any], message: Any) -> list[Any]:
        merged = list(messages)
        message_id = getattr(message, "id", None)
        for index, current in enumerate(merged):
            if getattr(current, "id", None) == message_id:
                merged[index] = message
                return merged
        merged.append(message)
        return merged

    async def _select_response_result(
        self,
        *,
        client: TelegramClient,
        conversation: Any,
        messages: list[Any],
    ) -> dict[str, Any]:
        working_messages = list(messages)
        export_candidate = self._find_export_candidate(messages)
        if export_candidate is not None:
            downloaded = await self._maybe_download_text_file(
                client=client,
                conversation=conversation,
                message=export_candidate,
                captured_messages=working_messages,
            )
            if downloaded:
                selected_message = self._find_export_candidate(working_messages) or export_candidate
                return {"message": selected_message, "downloaded_file": downloaded, "messages": working_messages}
            selected_message = self._find_export_candidate(working_messages) or export_candidate
            return {"message": selected_message, "downloaded_file": None, "messages": working_messages}

        for message in working_messages:
            downloaded = await self._maybe_download_text_file(
                client=client,
                conversation=conversation,
                message=message,
                captured_messages=working_messages,
            )
            if downloaded:
                return {"message": message, "downloaded_file": downloaded, "messages": working_messages}

        success_message = self._find_success_message(working_messages)
        if success_message is not None:
            return {"message": success_message, "downloaded_file": None, "messages": working_messages}

        for message in working_messages:
            text = str(getattr(message, "raw_text", None) or getattr(message, "text", None) or "").strip()
            if text:
                return {"message": message, "downloaded_file": None, "messages": working_messages}

        return {"message": working_messages[0], "downloaded_file": None, "messages": working_messages}

    @staticmethod
    def _find_txt_button(message: Any) -> Any | None:
        for row in getattr(message, "buttons", None) or []:
            for button in row:
                text = str(getattr(button, "text", "") or "").strip().lower()
                if "txt" in text:
                    return button
        return None

    @staticmethod
    def _find_export_button(message: Any) -> Any | None:
        for row in getattr(message, "buttons", None) or []:
            for button in row:
                text = str(getattr(button, "text", "") or "").strip().lower()
                if "txt" in text or "\u5bfc\u51fa" in text or "\u4e0b\u8f7d" in text:
                    return button
        return None

    @staticmethod
    def _find_export_candidate(messages: list[Any]) -> Any | None:
        for message in reversed(messages):
            if TelegramUserbotManager._find_export_button(message) is not None:
                return message
            text = str(getattr(message, "raw_text", None) or getattr(message, "text", None) or "")
            if "\u5bfc\u51fa\u6210\u529f" in text or "\u4e0b\u8f7dtxt" in text.lower():
                return message
        return None

    @staticmethod
    def _find_success_message(messages: list[Any]) -> Any | None:
        for message in messages:
            text = str(getattr(message, "raw_text", None) or getattr(message, "text", None) or "")
            if "查询成功" in text:
                return message
        return None

    @staticmethod
    def _is_text_file_message(message: Any) -> bool:
        file_obj = getattr(message, "file", None)
        if file_obj is None:
            return False
        name = str(getattr(file_obj, "name", "") or "").lower()
        mime_type = str(getattr(file_obj, "mime_type", "") or "").lower()
        return name.endswith(".txt") or mime_type.startswith("text/")

    async def _download_text_file(self, *, client: TelegramClient, message: Any) -> dict[str, Any]:
        payload = await client.download_media(message, file=bytes)
        if not isinstance(payload, bytes):
            raise RuntimeError("Telegram returned a non-bytes payload for text file download.")
        file_obj = getattr(message, "file", None)
        return {
            "text": self._decode_text_bytes(payload),
            "file_name": self._timestamped_file_name(),
            "mime_type": getattr(file_obj, "mime_type", None),
            "size": getattr(file_obj, "size", None),
        }

    async def _download_text_url(self, url: str) -> dict[str, Any]:
        timeout = min(30, settings.telegram_bridge_request_timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
        return {
            "text": self._decode_text_bytes(response.content),
            "file_name": self._timestamped_file_name(),
            "mime_type": response.headers.get("content-type"),
            "size": len(response.content),
            "url": url,
        }

    @staticmethod
    def _extract_text_url_from_message(message: Any) -> str | None:
        text = str(getattr(message, "raw_text", None) or getattr(message, "text", None) or "")
        matched = re.search(r"https?://[^\s]+?\.txt(?:\?[^\s]*)?", text, flags=re.IGNORECASE)
        if matched:
            return matched.group(0)
        generic = re.search(r"https?://[^\s]+", text, flags=re.IGNORECASE)
        if generic and ("\u5bfc\u51fa" in text or "txt" in text.lower()):
            return generic.group(0)
        for row in getattr(message, "buttons", None) or []:
            for button in row:
                url = getattr(button, "url", None)
                label = str(getattr(button, "text", "") or "").lower()
                if isinstance(url, str) and (".txt" in url.lower() or "txt" in label or "\u5bfc\u51fa" in label):
                    return url
        return None

    @staticmethod
    def _extract_text_url_from_click_result(result: Any) -> str | None:
        if isinstance(result, str) and result.startswith("http"):
            return result
        url = getattr(result, "url", None)
        if isinstance(url, str) and url.startswith("http"):
            return url
        message = getattr(result, "message", None)
        if isinstance(message, str):
            matched = re.search(r"https?://[^\s]+", message, flags=re.IGNORECASE)
            if matched:
                return matched.group(0)
        return None

    @staticmethod
    def _timestamped_file_name() -> str:
        return datetime.now(UTC).strftime("telegram-export-%Y%m%d-%H%M%S.txt")

    async def _poll_export_messages(
        self,
        *,
        client: TelegramClient,
        source_message: Any,
    ) -> list[Any]:
        tracked = [source_message]
        target = self._target_bot()
        deadline = asyncio.get_running_loop().time() + min(90, settings.telegram_bridge_request_timeout_seconds)
        while asyncio.get_running_loop().time() < deadline:
            refreshed = await client.get_messages(target, ids=getattr(source_message, "id", None))
            if refreshed is not None:
                self._merge_message_in_place(tracked, refreshed)

            recent_messages = await client.get_messages(target, limit=12)
            for item in recent_messages or []:
                if getattr(item, "out", False):
                    continue
                if getattr(source_message, "id", 0) and getattr(item, "id", 0) + 5 < getattr(source_message, "id", 0):
                    continue
                self._merge_message_in_place(tracked, item)

            if self._find_export_candidate(tracked) is not None or self._find_downloadable_candidate(tracked) is not None:
                if self._find_downloadable_candidate(tracked) is not None:
                    return tracked
            await asyncio.sleep(5)
        return tracked

    @staticmethod
    def _find_downloadable_candidate(messages: list[Any]) -> Any | None:
        for message in messages:
            if TelegramUserbotManager._is_text_file_message(message):
                return message
            if TelegramUserbotManager._extract_text_url_from_message(message):
                return message
        return None

    @staticmethod
    def _merge_message_in_place(messages: list[Any], message: Any) -> None:
        merged = TelegramUserbotManager._merge_message(messages, message)
        messages[:] = merged

    @staticmethod
    def _decode_text_bytes(payload: bytes) -> str:
        for encoding in ("utf-8", "utf-8-sig", "gb18030", "gbk"):
            try:
                return payload.decode(encoding)
            except UnicodeDecodeError:
                continue
        return payload.decode("utf-8", errors="replace")

    @staticmethod
    def _serialize_message(message: Any) -> dict[str, Any]:
        file_obj = getattr(message, "file", None)
        return {
            "id": getattr(message, "id", None),
            "text": getattr(message, "raw_text", None) or getattr(message, "text", None) or "",
            "date": message.date.isoformat() if getattr(message, "date", None) else None,
            "buttons": [
                [str(getattr(button, "text", "") or "") for button in row]
                for row in (getattr(message, "buttons", None) or [])
            ],
            "file": {
                "name": getattr(file_obj, "name", None),
                "mime_type": getattr(file_obj, "mime_type", None),
                "size": getattr(file_obj, "size", None),
            }
            if file_obj is not None
            else None,
        }


@lru_cache
def get_telegram_userbot_manager() -> TelegramUserbotManager:
    return TelegramUserbotManager()
