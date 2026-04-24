from __future__ import annotations

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import MODEL_NODE_DEGRADED, MODEL_NODE_HEALTHY
from app.models.model_node import ModelNode


class ModelNodeRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_routable_for_model(self, requested_model: str) -> ModelNode | None:
        for node in await self.list_routable():
            aliases = set(node.capability_json.get("model_aliases", []))
            aliases.add(node.code)
            aliases.add(node.model_name)
            if requested_model in aliases:
                return node
        return None

    async def get_best_available_for_models(self, allowed_models: list[str]) -> ModelNode | None:
        allowed = set(allowed_models)
        for node in await self.list_routable():
            aliases = set(node.capability_json.get("model_aliases", []))
            aliases.add(node.code)
            aliases.add(node.model_name)
            if aliases.intersection(allowed):
                return node
        return None

    async def list_routable(self) -> list[ModelNode]:
        result = await self.session.execute(
            select(ModelNode)
            .where(
                ModelNode.enabled.is_(True),
                ModelNode.status.in_([MODEL_NODE_HEALTHY, MODEL_NODE_DEGRADED]),
            )
            .order_by(desc(ModelNode.priority), desc(ModelNode.weight))
        )
        return result.scalars().all()

    async def list_all(self) -> list[ModelNode]:
        result = await self.session.execute(
            select(ModelNode).order_by(desc(ModelNode.priority), desc(ModelNode.weight), ModelNode.code)
        )
        return result.scalars().all()

    async def get_by_id(self, node_id: str) -> ModelNode | None:
        result = await self.session.execute(select(ModelNode).where(ModelNode.id == node_id))
        return result.scalar_one_or_none()

    async def get_by_code(self, code: str) -> ModelNode | None:
        result = await self.session.execute(select(ModelNode).where(ModelNode.code == code))
        return result.scalar_one_or_none()

    async def create(self, node: ModelNode) -> ModelNode:
        self.session.add(node)
        await self.session.flush()
        return node

    async def update(self, node: ModelNode) -> ModelNode:
        await self.session.flush()
        return node
