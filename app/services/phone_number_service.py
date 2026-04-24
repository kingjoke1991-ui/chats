from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx
from redis.asyncio import Redis

from app.core.config import settings
from app.core.exceptions import AppException
from app.core.redis import get_redis

PHONE_COMMAND_GET_NUMBER = "get_number"
PHONE_COMMAND_READ_CACHED_SMS = "read_cached_sms"
PHONE_COMMAND_FETCH_LATEST_SMS = "fetch_latest_sms"


@dataclass(slots=True)
class PhoneCommandResult:
    command: str
    content: str
    metadata: dict[str, Any]


class PhoneNumberService:
    internal_model = "oracle-number-tool"
    internal_provider = "internal-tool"
    internal_node_id = "number-command"

    def __init__(self, redis_client: Redis | None = None):
        self.redis = redis_client or get_redis()

    def match_command(self, content: str) -> str | None:
        normalized = self._normalize(content)
        if "获取一个号码" in normalized:
            return PHONE_COMMAND_GET_NUMBER
        if "获取最新短信列表" in normalized or "手动抓一次最新短信" in normalized:
            return PHONE_COMMAND_FETCH_LATEST_SMS
        if "读取当前号码缓存短信" in normalized or "读取缓存短信" in normalized:
            return PHONE_COMMAND_READ_CACHED_SMS
        return None

    async def execute(self, *, command: str, conversation_id: str) -> PhoneCommandResult:
        if command == PHONE_COMMAND_GET_NUMBER:
            return await self._get_number(conversation_id)
        if command == PHONE_COMMAND_READ_CACHED_SMS:
            return await self._read_cached_sms(conversation_id)
        if command == PHONE_COMMAND_FETCH_LATEST_SMS:
            return await self._fetch_latest_sms(conversation_id)
        raise AppException(400, "PHONE_COMMAND_NOT_SUPPORTED", f"unsupported phone command `{command}`")

    async def get_current_number(self, conversation_id: str) -> str | None:
        return await self.redis.get(self._current_number_key(conversation_id))

    async def set_current_number(self, conversation_id: str, phone_number: str) -> None:
        await self.redis.set(
            self._current_number_key(conversation_id),
            phone_number,
            ex=settings.phone_current_number_ttl_seconds,
        )

    async def _get_number(self, conversation_id: str) -> PhoneCommandResult:
        payload = await self._request_json(
            "GET",
            "number",
            params={"country": settings.phone_api_country},
        )
        phone_number = self._extract_phone_number(payload)
        await self.set_current_number(conversation_id, phone_number)
        return PhoneCommandResult(
            command=PHONE_COMMAND_GET_NUMBER,
            content=f"号码已获取。\n当前号码：{phone_number}",
            metadata={"phone_number": phone_number},
        )

    async def _read_cached_sms(self, conversation_id: str) -> PhoneCommandResult:
        phone_number = await self._require_current_number(conversation_id)
        payload = await self._request_json("GET", f"sms/{quote(phone_number, safe='')}")
        messages = self._extract_sms_items(payload)
        return PhoneCommandResult(
            command=PHONE_COMMAND_READ_CACHED_SMS,
            content=self._format_sms_output(
                phone_number=phone_number,
                messages=messages,
                status_lines=["已读取当前号码缓存短信，未触发抓取。"],
                raw_payload=payload,
            ),
            metadata={"phone_number": phone_number, "sms_count": len(messages)},
        )

    async def _fetch_latest_sms(self, conversation_id: str) -> PhoneCommandResult:
        phone_number = await self._require_current_number(conversation_id)
        encoded_phone = quote(phone_number, safe="")
        baseline_payload = await self._request_json("GET", f"sms/{encoded_phone}")
        fetch_request_returned = await self._trigger_single_fetch(encoded_phone)
        payload, cache_updated, waited_seconds = await self._poll_sms_cache(
            encoded_phone=encoded_phone,
            baseline_payload=baseline_payload,
        )
        messages = self._extract_sms_items(payload)
        status_lines = self._build_fetch_status_lines(
            fetch_request_returned=fetch_request_returned,
            cache_updated=cache_updated,
            waited_seconds=waited_seconds,
        )
        return PhoneCommandResult(
            command=PHONE_COMMAND_FETCH_LATEST_SMS,
            content=self._format_sms_output(
                phone_number=phone_number,
                messages=messages,
                status_lines=status_lines,
                raw_payload=payload,
            ),
            metadata={"phone_number": phone_number, "sms_count": len(messages)},
        )

    async def _require_current_number(self, conversation_id: str) -> str:
        phone_number = await self.get_current_number(conversation_id)
        if phone_number:
            return phone_number
        raise AppException(400, "PHONE_NUMBER_REQUIRED", "当前会话还没有号码，请先发送“获取一个号码”。")

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any] | list[Any]:
        try:
            async with httpx.AsyncClient(timeout=settings.phone_api_timeout_seconds) as client:
                response = await client.request(
                    method,
                    self._build_url(path),
                    params=params,
                )
        except httpx.HTTPError as exc:
            raise AppException(502, "PHONE_API_UNAVAILABLE", f"号码服务请求失败：{exc}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise AppException(502, "PHONE_API_INVALID_RESPONSE", "号码服务返回了无效 JSON。") from exc

        if response.status_code >= 400:
            detail = self._extract_error_detail(payload) or f"号码服务返回状态码 {response.status_code}。"
            raise AppException(502, "PHONE_API_ERROR", detail)

        if not isinstance(payload, (dict, list)):
            raise AppException(502, "PHONE_API_INVALID_RESPONSE", "号码服务返回了不支持的数据结构。")
        return payload

    @staticmethod
    def _normalize(content: str) -> str:
        return "".join(content.split())

    @staticmethod
    def _extract_phone_number(payload: dict[str, Any] | list[Any]) -> str:
        if not isinstance(payload, dict):
            raise AppException(502, "PHONE_API_INVALID_RESPONSE", "号码服务未返回号码对象。")
        number = payload.get("number")
        if isinstance(number, dict):
            phone_number = number.get("phone")
            if isinstance(phone_number, str) and phone_number.strip():
                return phone_number.strip()
        raise AppException(502, "PHONE_API_INVALID_RESPONSE", "号码服务返回中缺少 `number.phone`。")

    def _extract_sms_items(self, payload: dict[str, Any] | list[Any]) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if not isinstance(payload, dict):
            return []

        for key in ("messages", "items", "sms", "data", "results", "list"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
            if isinstance(value, dict):
                nested_items = self._extract_sms_items(value)
                if nested_items:
                    return nested_items

        if any(key in payload for key in ("content", "text", "message", "code", "otp")):
            return [payload]
        return []

    def _format_sms_output(
        self,
        *,
        phone_number: str,
        messages: list[dict[str, Any]],
        status_lines: list[str],
        raw_payload: dict[str, Any] | list[Any],
    ) -> str:
        lines = [f"当前号码：{phone_number}", *status_lines]

        if not messages:
            lines.append("当前没有短信。")
            raw_preview = self._raw_preview(raw_payload)
            if raw_preview:
                lines.append("原始返回：")
                lines.append(raw_preview)
            return "\n".join(lines)

        lines.append(f"短信数量：{len(messages)}")
        for index, message in enumerate(messages[:10], start=1):
            timestamp = self._stringify_field(message, "received_at", "created_at", "time", "timestamp", "date")
            sender = self._stringify_field(message, "sender", "from", "source", "origin")
            code = self._stringify_field(message, "code", "otp", "verify_code")
            content = self._stringify_field(message, "content", "text", "message", "body")

            lines.append("")
            lines.append(f"{index}. 时间：{timestamp or '-'}")
            if sender:
                lines.append(f"来源：{sender}")
            if code:
                lines.append(f"验证码：{code}")
            lines.append(f"内容：{content or '-'}")

        if len(messages) > 10:
            lines.append("")
            lines.append(f"其余 {len(messages) - 10} 条短信未展开。")
        return "\n".join(lines)

    @staticmethod
    def _stringify_field(item: dict[str, Any], *keys: str) -> str:
        for key in keys:
            value = item.get(key)
            if value is None:
                continue
            text = str(value).strip()
            if text:
                return text
        return ""

    @staticmethod
    def _raw_preview(payload: dict[str, Any] | list[Any]) -> str:
        if payload in ({}, []):
            return ""
        raw = json.dumps(payload, ensure_ascii=False)
        if len(raw) > 600:
            raw = f"{raw[:597]}..."
        return raw

    @staticmethod
    def _extract_error_detail(payload: Any) -> str:
        if isinstance(payload, dict):
            for key in ("detail", "message", "error"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
                if isinstance(value, dict):
                    nested = PhoneNumberService._extract_error_detail(value)
                    if nested:
                        return nested
        return ""

    @staticmethod
    def _current_number_key(conversation_id: str) -> str:
        return f"chat_oracle:phone:current_number:{conversation_id}"

    @staticmethod
    def _build_url(path: str) -> str:
        return f"{settings.phone_api_base_url.rstrip('/')}/{path.lstrip('/')}"

    async def _trigger_single_fetch(self, encoded_phone: str) -> bool:
        try:
            await asyncio.wait_for(
                self._request_json("POST", f"sms/{encoded_phone}/fetch"),
                timeout=settings.phone_api_poll_interval_seconds,
            )
            return True
        except TimeoutError:
            return False

    async def _poll_sms_cache(
        self,
        *,
        encoded_phone: str,
        baseline_payload: dict[str, Any] | list[Any],
    ) -> tuple[dict[str, Any] | list[Any], bool, int]:
        baseline_fingerprint = self._payload_fingerprint(baseline_payload)
        latest_payload = await self._request_json("GET", f"sms/{encoded_phone}")
        latest_fingerprint = self._payload_fingerprint(latest_payload)
        if latest_fingerprint != baseline_fingerprint:
            return latest_payload, True, 0

        interval = max(1, settings.phone_api_poll_interval_seconds)
        deadline = time.monotonic() + max(interval, settings.phone_api_timeout_seconds)
        waited_seconds = 0

        while time.monotonic() < deadline:
            await asyncio.sleep(interval)
            waited_seconds += interval
            latest_payload = await self._request_json("GET", f"sms/{encoded_phone}")
            latest_fingerprint = self._payload_fingerprint(latest_payload)
            if latest_fingerprint != baseline_fingerprint:
                return latest_payload, True, waited_seconds

        return latest_payload, False, waited_seconds

    @staticmethod
    def _payload_fingerprint(payload: dict[str, Any] | list[Any]) -> str:
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    @staticmethod
    def _build_fetch_status_lines(
        *,
        fetch_request_returned: bool,
        cache_updated: bool,
        waited_seconds: int,
    ) -> list[str]:
        lines = [
            "已手动触发一次最新短信抓取。",
            f"按 30 秒间隔轮询缓存，最长等待 180 秒。",
        ]
        if not fetch_request_returned:
            lines.append("抓取请求在 30 秒内未返回，已继续轮询缓存等待结果。")
        if cache_updated:
            lines.append(
                "缓存已更新，已返回最新短信。"
                if waited_seconds == 0
                else f"缓存已在约 {waited_seconds} 秒后更新，已返回最新短信。"
            )
        else:
            lines.append(f"轮询约 {waited_seconds} 秒后未发现缓存更新，以下为当前缓存短信。")
        return lines
