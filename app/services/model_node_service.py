from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.constants import MODEL_NODE_HEALTHY, MODEL_NODE_UNHEALTHY, PROVIDER_TYPE_OPENAI_COMPAT
from app.models.model_node import ModelNode
from app.providers.openai_compat import OpenAICompatProvider
from app.repos.model_node_repo import ModelNodeRepo


class ModelNodeService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.nodes = ModelNodeRepo(session)
        self.provider = OpenAICompatProvider()

    async def sync_defaults_and_healthcheck(self) -> None:
        await self._upsert_default_nodes()
        await self._refresh_health()
        await self.session.commit()

    async def _upsert_default_nodes(self) -> None:
        now = datetime.now(UTC)
        desired_nodes = [
            {
                "code": settings.llm_default_node_code,
                "provider_code": settings.llm_default_provider_code,
                "base_url": settings.llm_local_base_url,
                "model_name": settings.llm_default_model_name,
                "api_key": None,
                "priority": 200,
                "weight": 200,
                "max_parallel_requests": 1,
                "capability_json": {
                    "model_aliases": [settings.llm_default_model, settings.llm_default_model_name],
                },
                "metadata_json": {"source": "mode.md", "type": "preferred-local"},
            },
            {
                "code": settings.llm_fallback_node_code,
                "provider_code": settings.llm_fallback_provider_code,
                "base_url": settings.llm_openai_compat_base_url,
                "model_name": settings.llm_fallback_model_name,
                "api_key": None,
                "priority": 100,
                "weight": 100,
                "max_parallel_requests": 100,
                "capability_json": {
                    "model_aliases": [settings.llm_fallback_model, settings.llm_fallback_model_name],
                },
                "metadata_json": {"source": "models.md", "type": "fallback-remote"},
            },
        ]
        if settings.telegram_audit_gemini_enabled:
            desired_nodes.append(
                {
                    "code": settings.telegram_audit_node_code,
                    "provider_code": settings.telegram_audit_provider_code,
                    "base_url": settings.telegram_audit_gemini_base_url,
                    "model_name": settings.telegram_audit_gemini_model,
                    "api_key": settings.telegram_audit_gemini_api_key,
                    "priority": 110,
                    "weight": 110,
                    "max_parallel_requests": 8,
                    "capability_json": {
                        "model_aliases": [
                            settings.telegram_audit_gemini_model,
                            settings.telegram_audit_node_code,
                        ],
                        "purpose": ["telegram_audit"],
                    },
                    "metadata_json": {"source": "telegram-audit", "type": "gemini-openai-compat"},
                }
            )
        for item in desired_nodes:
            node = await self.nodes.get_by_code(item["code"])
            if not node:
                await self.nodes.create(
                    ModelNode(
                        code=item["code"],
                        provider_type=PROVIDER_TYPE_OPENAI_COMPAT,
                        provider_code=item["provider_code"],
                        base_url=item["base_url"],
                        model_name=item["model_name"],
                        api_key_encrypted=item["api_key"],
                        enabled=True,
                        status=MODEL_NODE_UNHEALTHY,
                        weight=item["weight"],
                        priority=item["priority"],
                        max_parallel_requests=item["max_parallel_requests"],
                        current_parallel_requests=0,
                        capability_json=item["capability_json"],
                        metadata_json=item["metadata_json"],
                        created_at=now,
                        updated_at=now,
                    )
                )
                continue
            node.provider_type = PROVIDER_TYPE_OPENAI_COMPAT
            node.provider_code = item["provider_code"]
            node.base_url = item["base_url"]
            node.model_name = item["model_name"]
            node.api_key_encrypted = item["api_key"]
            node.enabled = True
            node.weight = item["weight"]
            node.priority = item["priority"]
            node.max_parallel_requests = item["max_parallel_requests"]
            node.capability_json = item["capability_json"]
            node.metadata_json = item["metadata_json"]
            node.updated_at = now
            await self.nodes.update(node)

    async def _refresh_health(self) -> None:
        now = datetime.now(UTC)
        for node in await self.nodes.list_all():
            healthy = await self.provider.healthcheck(node)
            node.last_healthcheck_at = now
            node.status = MODEL_NODE_HEALTHY if healthy else MODEL_NODE_UNHEALTHY
            if healthy:
                node.last_healthy_at = now
            await self.nodes.update(node)
