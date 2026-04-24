from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.core.config import settings
from app.core.exceptions import AppException
from app.models.model_node import ModelNode
from app.providers.base import BaseLLMProvider, ProviderChatResult, ProviderStreamChunk
from app.schemas.chat import ChatCompletionRequest


class OpenAICompatProvider(BaseLLMProvider):
    async def create_chat_completion(
        self,
        node: ModelNode,
        payload: ChatCompletionRequest,
    ) -> ProviderChatResult:
        request_payload = self._build_payload(node=node, payload=payload, stream=False)
        try:
            async with httpx.AsyncClient(timeout=settings.llm_request_timeout_seconds) as client:
                response = await client.post(
                    f"{node.base_url.rstrip('/')}/chat/completions",
                    headers=self._build_headers(node),
                    json=request_payload,
                )
        except httpx.HTTPError as exc:
            raise AppException(502, "UPSTREAM_UNAVAILABLE", f"upstream request failed: {exc}") from exc

        data = self._decode_response(response)
        if response.status_code >= 400:
            error = data.get("error", {}) if isinstance(data, dict) else {}
            detail = error.get("message") or f"upstream returned status {response.status_code}"
            error_code = "MODEL_UNAVAILABLE" if response.status_code == 503 else "UPSTREAM_ERROR"
            raise AppException(response.status_code if response.status_code == 503 else 502, error_code, detail)

        choices = data.get("choices") or []
        if not choices:
            raise AppException(502, "UPSTREAM_ERROR", "upstream response did not include choices")

        message = choices[0].get("message") or {}
        usage = data.get("usage") or {}
        return ProviderChatResult(
            completion_id=data.get("id", ""),
            created=data.get("created", 0),
            model=data.get("model", node.model_name),
            content=message.get("content", ""),
            finish_reason=choices[0].get("finish_reason"),
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
            raw_response=data,
        )

    async def stream_chat_completion(
        self,
        node: ModelNode,
        payload: ChatCompletionRequest,
    ) -> AsyncIterator[ProviderStreamChunk]:
        request_payload = self._build_payload(node=node, payload=payload, stream=True)
        try:
            async with httpx.AsyncClient(timeout=settings.llm_request_timeout_seconds) as client:
                async with client.stream(
                    "POST",
                    f"{node.base_url.rstrip('/')}/chat/completions",
                    headers=self._build_headers(node),
                    json=request_payload,
                ) as response:
                    if response.status_code >= 400:
                        body = await response.aread()
                        self._raise_stream_error(response.status_code, body.decode("utf-8", errors="ignore"))
                    async for line in response.aiter_lines():
                        if not line or not line.startswith("data: "):
                            continue
                        payload_text = line[6:].strip()
                        if payload_text == "[DONE]":
                            break
                        try:
                            parsed = json.loads(payload_text)
                        except json.JSONDecodeError:
                            continue
                        choices = parsed.get("choices") or []
                        if not choices:
                            continue
                        delta = choices[0].get("delta") or {}
                        usage = parsed.get("usage") or {}
                        yield ProviderStreamChunk(
                            text_delta=delta.get("content", ""),
                            finish_reason=choices[0].get("finish_reason"),
                            prompt_tokens=usage.get("prompt_tokens", 0),
                            completion_tokens=usage.get("completion_tokens", 0),
                            total_tokens=usage.get("total_tokens", 0),
                            raw_payload=parsed,
                        )
        except httpx.HTTPError as exc:
            raise AppException(502, "UPSTREAM_UNAVAILABLE", f"upstream stream failed: {exc}") from exc

    async def healthcheck(self, node: ModelNode) -> bool:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(
                    f"{node.base_url.rstrip('/')}/models",
                    headers=self._build_headers(node),
                )
            return response.status_code < 500
        except httpx.HTTPError:
            return False

    @staticmethod
    def _build_payload(node: ModelNode, payload: ChatCompletionRequest, stream: bool) -> dict[str, Any]:
        data: dict[str, Any] = {
            "model": payload.model or node.model_name,
            "messages": [message.model_dump() for message in payload.messages],
            "stream": stream,
        }
        if payload.temperature is not None:
            data["temperature"] = payload.temperature
        if payload.max_tokens is not None:
            data["max_tokens"] = payload.max_tokens
        return data

    @staticmethod
    def _build_headers(node: ModelNode) -> dict[str, str]:
        api_key = (
            (node.api_key_encrypted or "").strip()
            or (
                settings.llm_local_api_key
                if node.code == settings.llm_default_node_code
                else settings.llm_openai_compat_api_key
            )
        )
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _decode_response(response: httpx.Response) -> dict[str, Any]:
        try:
            data = response.json()
        except ValueError as exc:
            raise AppException(502, "UPSTREAM_ERROR", "upstream returned invalid JSON") from exc
        if isinstance(data, list) and data and isinstance(data[0], dict):
            data = data[0]
        if not isinstance(data, dict):
            raise AppException(502, "UPSTREAM_ERROR", "upstream returned unexpected payload")
        return data

    @staticmethod
    def _raise_stream_error(status_code: int, body: str) -> None:
        detail = body or f"upstream returned status {status_code}"
        error_code = "MODEL_UNAVAILABLE" if status_code == 503 else "UPSTREAM_ERROR"
        raise AppException(status_code if status_code == 503 else 502, error_code, detail)
