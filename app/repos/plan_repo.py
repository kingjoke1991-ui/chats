from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.plan import Plan


class PlanRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_code(self, code: str) -> Plan | None:
        result = await self.session.execute(select(Plan).where(Plan.code == code, Plan.is_active.is_(True)))
        return result.scalar_one_or_none()

    async def get_any_by_code(self, code: str) -> Plan | None:
        result = await self.session.execute(select(Plan).where(Plan.code == code))
        return result.scalar_one_or_none()

    async def get_by_id(self, plan_id: str) -> Plan | None:
        result = await self.session.execute(select(Plan).where(Plan.id == plan_id))
        return result.scalar_one_or_none()

    async def list_active(self) -> list[Plan]:
        result = await self.session.execute(select(Plan).where(Plan.is_active.is_(True)).order_by(Plan.monthly_price_cents.asc()))
        return result.scalars().all()

    async def list_all(self) -> list[Plan]:
        result = await self.session.execute(select(Plan).order_by(Plan.monthly_price_cents.asc(), Plan.created_at.asc()))
        return result.scalars().all()

    async def create(self, plan: Plan) -> Plan:
        self.session.add(plan)
        await self.session.flush()
        await self.session.refresh(plan)
        return plan

    async def update(self, plan: Plan) -> Plan:
        await self.session.flush()
        await self.session.refresh(plan)
        return plan
