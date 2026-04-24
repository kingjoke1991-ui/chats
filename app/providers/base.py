from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from app.models.model_node import ModelNode
from app.schemas.chat import ChatCompletionRequest


@dataclass
class ProviderChatResult:
    completion_id: str
    created: int
    model: str
    content: str
    finish_reason: str | None
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    raw_response: dict[str, Any]


@dataclass
class ProviderStreamChunk:
    text_delta: str = ""
    finish_reason: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    raw_payload: dict[str, Any] | None = None


class BaseLLMProvider(ABC):
    @abstractmethod
    async def create_chat_completion(
        self,
        node: ModelNode,
        payload: ChatCompletionRequest,
    ) -> ProviderChatResult:
        raise NotImplementedError

    @abstractmethod
    async def stream_chat_completion(
        self,
        node: ModelNode,
        payload: ChatCompletionRequest,
    ) -> AsyncIterator[ProviderStreamChunk]:
        raise NotImplementedError

    @abstractmethod
    async def healthcheck(self, node: ModelNode) -> bool:
        raise NotImplementedError
