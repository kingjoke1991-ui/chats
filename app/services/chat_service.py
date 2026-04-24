from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.constants import (
    MESSAGE_ROLE_ASSISTANT,
    MESSAGE_ROLE_SYSTEM,
    MESSAGE_ROLE_USER,
    MESSAGE_STATUS_COMPLETED,
    MESSAGE_STATUS_FAILED,
    MESSAGE_STATUS_PENDING,
    MESSAGE_STATUS_STREAMING,
    PROVIDER_TYPE_OPENAI_COMPAT,
)
from app.core.exceptions import AppException
from app.models.conversation import Conversation
from app.models.message import Message
from app.providers.openai_compat import OpenAICompatProvider
from app.repos.conversation_repo import ConversationRepo
from app.repos.message_repo import MessageRepo
from app.repos.model_node_repo import ModelNodeRepo
from app.repos.subscription_repo import SubscriptionRepo
from app.schemas.chat import (
    ChatCompletionChoice,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionUsage,
    ChatMessageInput,
    ChatMessageOutput,
)
from app.services.phone_number_service import (
    PHONE_COMMAND_GET_NUMBER,
    PhoneCommandResult,
    PhoneNumberService,
)
from app.services.qiandu_search import QianduSearchCommandResult, QianduSearchService
from app.services.telegram_bridge_service import TelegramBridgeCommandResult, TelegramBridgeService
from app.services.web_search import WebSearchCommandResult, WebSearchService


class ChatService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.conversations = ConversationRepo(session)
        self.messages = MessageRepo(session)
        self.model_nodes = ModelNodeRepo(session)
        self.subscriptions = SubscriptionRepo(session)
        self.providers = {
            PROVIDER_TYPE_OPENAI_COMPAT: OpenAICompatProvider(),
        }
        self.phone_numbers = PhoneNumberService()
        self.telegram_bridge = TelegramBridgeService(session)
        self.web_search = WebSearchService(session)
        self.qiandu_search = QianduSearchService(session)

    async def create_completion(self, user_id: str, payload: ChatCompletionRequest) -> ChatCompletionResponse:
        internal_response = await self._handle_internal_command(user_id=user_id, payload=payload)
        if internal_response:
            return self._build_internal_completion_response(internal_response)

        prepared = await self._prepare_request(user_id=user_id, payload=payload)
        provider = self._provider_for(prepared["node"].provider_type)
        result = await provider.create_chat_completion(node=prepared["node"], payload=prepared["context_payload"])

        finished_at = datetime.now(UTC)
        assistant_message: Message = prepared["assistant_message"]
        assistant_message.content_text = result.content
        assistant_message.content_json = {"role": MESSAGE_ROLE_ASSISTANT, "content": result.content}
        assistant_message.model = result.model
        assistant_message.status = MESSAGE_STATUS_COMPLETED
        assistant_message.finish_reason = result.finish_reason
        assistant_message.prompt_tokens = result.prompt_tokens
        assistant_message.completion_tokens = result.completion_tokens
        assistant_message.total_tokens = result.total_tokens
        assistant_message.updated_at = finished_at
        await self.conversations.touch(
            prepared["conversation"],
            latest_message_at=finished_at,
            latest_model=prepared["response_model"],
            message_increment=2,
        )
        await self.session.commit()

        return ChatCompletionResponse(
            id=result.completion_id or prepared["request_id"],
            created=result.created or int(finished_at.timestamp()),
            model=prepared["response_model"],
            choices=[
                ChatCompletionChoice(
                    index=0,
                    message=ChatMessageOutput(role=MESSAGE_ROLE_ASSISTANT, content=result.content),
                    finish_reason=result.finish_reason,
                )
            ],
            usage=ChatCompletionUsage(
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
                total_tokens=result.total_tokens,
            ),
            conversation_id=prepared["conversation"].id,
            provider=prepared["node"].provider_code,
            node_id=prepared["node"].id,
        )

    async def create_completion_stream(
        self,
        user_id: str,
        payload: ChatCompletionRequest,
    ) -> AsyncIterator[str]:
        try:
            internal_response = await self._handle_internal_command(user_id=user_id, payload=payload)
            if internal_response:
                async for event in self._stream_internal_completion_response(internal_response):
                    yield event
                return

            prepared = await self._prepare_request(user_id=user_id, payload=payload, streaming=True)
            provider = self._provider_for(prepared["node"].provider_type)
            accumulated = ""
            finish_reason: str | None = None
            prompt_tokens = 0
            completion_tokens = 0
            total_tokens = 0
            created = int(datetime.now(UTC).timestamp())

            async for chunk in provider.stream_chat_completion(node=prepared["node"], payload=prepared["context_payload"]):
                if chunk.text_delta:
                    accumulated += chunk.text_delta
                    payload_json = {
                        "id": prepared["request_id"],
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": prepared["response_model"],
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"content": chunk.text_delta},
                                "finish_reason": None,
                            }
                        ],
                        "conversation_id": prepared["conversation"].id,
                    }
                    yield f"data: {json.dumps(payload_json, ensure_ascii=False)}\n\n"
                if chunk.finish_reason is not None:
                    finish_reason = chunk.finish_reason
                prompt_tokens = max(prompt_tokens, chunk.prompt_tokens)
                completion_tokens = max(completion_tokens, chunk.completion_tokens)
                total_tokens = max(total_tokens, chunk.total_tokens)

            finished_at = datetime.now(UTC)
            assistant_message: Message = prepared["assistant_message"]
            assistant_message.content_text = accumulated
            assistant_message.content_json = {"role": MESSAGE_ROLE_ASSISTANT, "content": accumulated}
            assistant_message.model = prepared["response_model"]
            assistant_message.status = MESSAGE_STATUS_COMPLETED
            assistant_message.finish_reason = finish_reason or "stop"
            assistant_message.prompt_tokens = prompt_tokens
            assistant_message.completion_tokens = completion_tokens
            assistant_message.total_tokens = total_tokens
            assistant_message.updated_at = finished_at
            await self.conversations.touch(
                prepared["conversation"],
                latest_message_at=finished_at,
                latest_model=prepared["response_model"],
                message_increment=2,
            )
            await self.session.commit()

            final_payload = {
                "id": prepared["request_id"],
                "object": "chat.completion.chunk",
                "created": created,
                "model": prepared["response_model"],
                "choices": [{"index": 0, "delta": {}, "finish_reason": finish_reason or "stop"}],
                "conversation_id": prepared["conversation"].id,
            }
            yield f"data: {json.dumps(final_payload, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        except AppException as exc:
            prepared_payload = locals().get("prepared")
            if prepared_payload:
                assistant_message = prepared_payload["assistant_message"]
                assistant_message.status = MESSAGE_STATUS_FAILED
                assistant_message.error_code = exc.error_code
                assistant_message.error_message = exc.detail
                assistant_message.updated_at = datetime.now(UTC)
                await self.conversations.touch(
                    prepared_payload["conversation"],
                    latest_message_at=assistant_message.updated_at,
                    latest_model=prepared_payload["response_model"],
                    message_increment=2,
                )
                await self.session.commit()
            error_payload = {"error_code": exc.error_code, "detail": exc.detail}
            yield f"event: error\ndata: {json.dumps(error_payload, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

    async def _handle_internal_command(
        self,
        *,
        user_id: str,
        payload: ChatCompletionRequest,
    ) -> dict | None:
        last_user_message = self._extract_last_user_message(payload)
        phone_command = self.phone_numbers.match_command(last_user_message.content)
        telegram_command = self.telegram_bridge.match_command(last_user_message.content)
        web_search_command = self.web_search.match_command(last_user_message.content)
        qiandu_search_command = self.qiandu_search.match_command(last_user_message.content)
        if not phone_command and not telegram_command and not web_search_command and not qiandu_search_command:
            return None

        subscription = await self.subscriptions.get_current_for_user(user_id)
        if not subscription:
            raise AppException(403, "SUBSCRIPTION_REQUIRED", "subscription not found")

        conversation = await self._prepare_conversation(
            user_id,
            payload,
            self._internal_model_for_command(
                phone_command,
                telegram_command,
                web_search_command,
                qiandu_search_command,
            ),
        )
        request_id = str(uuid4())
        now = datetime.now(UTC)

        await self.messages.create(
            Message(
                conversation_id=conversation.id,
                user_id=user_id,
                role=MESSAGE_ROLE_USER,
                content_text=last_user_message.content,
                content_json={
                    **last_user_message.model_dump(),
                    "command": phone_command
                    or (telegram_command or {}).get("command")
                    or (web_search_command or {}).get("command")
                    or (qiandu_search_command or {}).get("command"),
                },
                model=self._internal_model_for_command(
                    phone_command,
                    telegram_command,
                    web_search_command,
                    qiandu_search_command,
                ),
                status=MESSAGE_STATUS_COMPLETED,
                request_id=request_id,
                created_at=now,
                updated_at=now,
            )
        )

        assistant_message = await self.messages.create(
            Message(
                conversation_id=conversation.id,
                user_id=user_id,
                role=MESSAGE_ROLE_ASSISTANT,
                content_text="",
                model=self._internal_model_for_command(
                    phone_command,
                    telegram_command,
                    web_search_command,
                    qiandu_search_command,
                ),
                status=MESSAGE_STATUS_PENDING,
                request_id=request_id,
                created_at=now,
                updated_at=now,
            )
        )

        try:
            if phone_command and phone_command != PHONE_COMMAND_GET_NUMBER:
                recent_phone_number = await self._resolve_recent_phone_number(conversation.id)
                await self.phone_numbers.set_current_number(conversation.id, recent_phone_number)
            if phone_command:
                result = await self.phone_numbers.execute(command=phone_command, conversation_id=conversation.id)
                result_model = self.phone_numbers.internal_model
            elif telegram_command:
                result = await self.telegram_bridge.execute(
                    query_text=telegram_command["query_text"],
                    bot_request_text=telegram_command["bot_request_text"],
                    allowed_models=list(subscription.plan.allowed_models_json or []),
                    requested_model=payload.model,
                )
                result_model = self.telegram_bridge.internal_model
            elif qiandu_search_command:
                result = await self.qiandu_search.execute(
                    query_text=qiandu_search_command["query_text"],
                    allowed_models=list(subscription.plan.allowed_models_json or []),
                    requested_model=payload.model,
                )
                result_model = self.qiandu_search.internal_model
            else:
                result = await self.web_search.execute(
                    query_text=web_search_command["query_text"],
                    allowed_models=list(subscription.plan.allowed_models_json or []),
                    requested_model=payload.model,
                )
                result_model = self.web_search.internal_model
        except AppException as exc:
            assistant_message.status = MESSAGE_STATUS_FAILED
            assistant_message.error_code = exc.error_code
            assistant_message.error_message = exc.detail
            assistant_message.updated_at = datetime.now(UTC)
            await self.conversations.touch(
                conversation,
                latest_message_at=assistant_message.updated_at,
                latest_model=self._internal_model_for_command(
                    phone_command,
                    telegram_command,
                    web_search_command,
                    qiandu_search_command,
                ),
                message_increment=2,
            )
            await self.session.commit()
            raise

        finished_at = datetime.now(UTC)
        assistant_message.content_text = result.content
        assistant_message.content_json = self._build_internal_message_json(result)
        assistant_message.model = result_model
        assistant_message.status = MESSAGE_STATUS_COMPLETED
        assistant_message.finish_reason = "stop"
        assistant_message.prompt_tokens = 0
        assistant_message.completion_tokens = 0
        assistant_message.total_tokens = 0
        assistant_message.updated_at = finished_at
        await self.conversations.touch(
            conversation,
            latest_message_at=finished_at,
            latest_model=result_model,
            message_increment=2,
        )
        await self.session.commit()

        return {
            "request_id": request_id,
            "conversation_id": conversation.id,
            "created": int(finished_at.timestamp()),
            "content": result.content,
            "model": result_model,
            "provider": self._internal_provider_for_command(
                phone_command,
                telegram_command,
                web_search_command,
                qiandu_search_command,
            ),
            "node_id": self._internal_node_for_command(
                phone_command,
                telegram_command,
                web_search_command,
                qiandu_search_command,
            ),
        }

    def _build_internal_completion_response(self, payload: dict) -> ChatCompletionResponse:
        return ChatCompletionResponse(
            id=payload["request_id"],
            created=payload["created"],
            model=payload["model"],
            choices=[
                ChatCompletionChoice(
                    index=0,
                    message=ChatMessageOutput(role=MESSAGE_ROLE_ASSISTANT, content=payload["content"]),
                    finish_reason="stop",
                )
            ],
            usage=ChatCompletionUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
            conversation_id=payload["conversation_id"],
            provider=payload["provider"],
            node_id=payload["node_id"],
        )

    async def _stream_internal_completion_response(self, payload: dict) -> AsyncIterator[str]:
        chunk_payload = {
            "id": payload["request_id"],
            "object": "chat.completion.chunk",
            "created": payload["created"],
            "model": payload["model"],
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": payload["content"]},
                    "finish_reason": None,
                }
            ],
            "conversation_id": payload["conversation_id"],
        }
        yield f"data: {json.dumps(chunk_payload, ensure_ascii=False)}\n\n"

        final_payload = {
            "id": payload["request_id"],
            "object": "chat.completion.chunk",
            "created": payload["created"],
            "model": payload["model"],
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            "conversation_id": payload["conversation_id"],
        }
        yield f"data: {json.dumps(final_payload, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    @staticmethod
    def _build_internal_message_json(
        result: PhoneCommandResult | TelegramBridgeCommandResult | WebSearchCommandResult | QianduSearchCommandResult,
    ) -> dict:
        return {
            "role": MESSAGE_ROLE_ASSISTANT,
            "content": result.content,
            "command": result.command,
            "metadata": result.metadata,
        }

    def _internal_model_for_command(
        self,
        phone_command: str | None,
        telegram_command: dict | None,
        web_search_command: dict | None,
        qiandu_search_command: dict | None,
    ) -> str:
        if phone_command:
            return self.phone_numbers.internal_model
        if telegram_command:
            return self.telegram_bridge.internal_model
        if qiandu_search_command:
            return self.qiandu_search.internal_model
        return self.web_search.internal_model

    def _internal_provider_for_command(
        self,
        phone_command: str | None,
        telegram_command: dict | None,
        web_search_command: dict | None,
        qiandu_search_command: dict | None,
    ) -> str:
        if phone_command:
            return self.phone_numbers.internal_provider
        if telegram_command:
            return self.telegram_bridge.internal_provider
        if qiandu_search_command:
            return self.qiandu_search.internal_provider
        return self.web_search.internal_provider

    def _internal_node_for_command(
        self,
        phone_command: str | None,
        telegram_command: dict | None,
        web_search_command: dict | None,
        qiandu_search_command: dict | None,
    ) -> str:
        if phone_command:
            return self.phone_numbers.internal_node_id
        if telegram_command:
            return self.telegram_bridge.internal_node_id
        if qiandu_search_command:
            return self.qiandu_search.internal_node_id
        return self.web_search.internal_node_id

    async def _resolve_recent_phone_number(self, conversation_id: str) -> str:
        history = await self.messages.list_for_conversation(conversation_id)
        phone_number = self._extract_recent_phone_number_from_messages(history)
        if phone_number:
            return phone_number
        raise AppException(400, "PHONE_NUMBER_REQUIRED", "当前会话还没有号码，请先发送“获取一个号码”。")

    @staticmethod
    def _extract_recent_phone_number_from_messages(messages: list[Message]) -> str | None:
        for message in reversed(messages):
            if message.role != MESSAGE_ROLE_ASSISTANT or message.status != MESSAGE_STATUS_COMPLETED:
                continue
            if not isinstance(message.content_json, dict):
                continue
            if message.content_json.get("command") != PHONE_COMMAND_GET_NUMBER:
                continue
            metadata = message.content_json.get("metadata")
            if not isinstance(metadata, dict):
                continue
            phone_number = metadata.get("phone_number")
            if isinstance(phone_number, str) and phone_number.strip():
                return phone_number.strip()
        return None

    async def _prepare_request(
        self,
        *,
        user_id: str,
        payload: ChatCompletionRequest,
        streaming: bool = False,
    ) -> dict:
        subscription = await self.subscriptions.get_current_for_user(user_id)
        if not subscription:
            raise AppException(403, "SUBSCRIPTION_REQUIRED", "subscription not found")

        allowed_models = list(subscription.plan.allowed_models_json or [])
        if payload.model and payload.model not in allowed_models:
            raise AppException(403, "MODEL_NOT_ALLOWED", f"model `{payload.model}` is not allowed for current plan")

        node, response_model = await self._select_node(requested_model=payload.model, allowed_models=allowed_models)
        if not node:
            raise AppException(503, "MODEL_ROUTE_NOT_FOUND", "no active model node is currently available")

        conversation = await self._prepare_conversation(user_id, payload, response_model)
        request_id = str(uuid4())
        last_user_message = self._extract_last_user_message(payload)
        now = datetime.now(UTC)

        await self.messages.create(
            Message(
                conversation_id=conversation.id,
                user_id=user_id,
                role=MESSAGE_ROLE_USER,
                content_text=last_user_message.content,
                content_json=last_user_message.model_dump(),
                model=response_model,
                status=MESSAGE_STATUS_COMPLETED,
                request_id=request_id,
                created_at=now,
                updated_at=now,
            )
        )

        context_messages = await self._build_context_messages(
            conversation_id=conversation.id,
            max_context_tokens=subscription.plan.max_context_tokens,
        )
        context_payload = payload.model_copy(
            update={
                "messages": context_messages,
                "model": response_model,
                "stream": streaming,
            }
        )

        assistant_message = await self.messages.create(
            Message(
                conversation_id=conversation.id,
                user_id=user_id,
                role=MESSAGE_ROLE_ASSISTANT,
                content_text="",
                model=response_model,
                status=MESSAGE_STATUS_STREAMING if streaming else MESSAGE_STATUS_PENDING,
                request_id=request_id,
                created_at=now,
                updated_at=now,
            )
        )

        return {
            "subscription": subscription,
            "conversation": conversation,
            "request_id": request_id,
            "assistant_message": assistant_message,
            "node": node,
            "response_model": response_model,
            "context_payload": context_payload,
        }

    async def _select_node(self, requested_model: str | None, allowed_models: list[str]):
        if requested_model:
            node = await self.model_nodes.get_routable_for_model(requested_model)
            if node:
                return node, requested_model
            if requested_model in {settings.llm_default_model, settings.llm_default_model_name}:
                fallback_node = await self.model_nodes.get_best_available_for_models(allowed_models)
                if fallback_node:
                    return fallback_node, fallback_node.model_name
            return None, requested_model

        node = await self.model_nodes.get_best_available_for_models(allowed_models)
        if node:
            return node, node.model_name
        return None, settings.llm_default_model

    def _provider_for(self, provider_type: str):
        provider = self.providers.get(provider_type)
        if not provider:
            raise AppException(500, "PROVIDER_NOT_IMPLEMENTED", f"provider `{provider_type}` is not implemented")
        return provider

    async def _prepare_conversation(
        self,
        user_id: str,
        payload: ChatCompletionRequest,
        requested_model: str,
    ) -> Conversation:
        now = datetime.now(UTC)
        if payload.conversation_id:
            conversation = await self.conversations.get_for_user(payload.conversation_id, user_id)
            if not conversation:
                raise AppException(404, "CONVERSATION_NOT_FOUND", "conversation not found")
            return conversation

        title = self._extract_last_user_message(payload).content.strip().replace("\r", " ").replace("\n", " ")
        return await self.conversations.create(
            Conversation(
                user_id=user_id,
                title=title[:80],
                latest_model=requested_model,
                latest_message_at=now,
                message_count=0,
                created_at=now,
                updated_at=now,
            )
        )

    async def _build_context_messages(
        self,
        conversation_id: str,
        max_context_tokens: int,
    ) -> list[ChatMessageInput]:
        token_per_message_estimate = 200
        max_messages = max(4, max_context_tokens // token_per_message_estimate)
        history = await self.messages.list_for_conversation(conversation_id)
        valid_messages = []
        for message in history:
            if message.role == MESSAGE_ROLE_USER and message.status == MESSAGE_STATUS_COMPLETED:
                valid_messages.append(message)
            elif message.role == MESSAGE_ROLE_ASSISTANT and message.status == MESSAGE_STATUS_COMPLETED:
                valid_messages.append(message)
            elif message.role == MESSAGE_ROLE_SYSTEM:
                valid_messages.append(message)
        if len(valid_messages) > max_messages:
            valid_messages = valid_messages[-max_messages:]
        return [ChatMessageInput(role=item.role, content=item.content_text) for item in valid_messages]

    @staticmethod
    def _extract_last_user_message(payload: ChatCompletionRequest):
        for message in reversed(payload.messages):
            if message.role == MESSAGE_ROLE_USER:
                return message
        raise AppException(400, "USER_MESSAGE_REQUIRED", "at least one user message is required")
