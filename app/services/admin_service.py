from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.repos.conversation_repo import ConversationRepo
from app.repos.message_repo import MessageRepo
from app.repos.model_node_repo import ModelNodeRepo
from app.repos.payment_order_repo import PaymentOrderRepo
from app.repos.plan_repo import PlanRepo
from app.repos.subscription_repo import SubscriptionRepo
from app.repos.user_repo import UserRepo
from app.schemas.admin import (
    AdminConversationRow,
    AdminConversationsResponse,
    AdminFailedMessageRow,
    AdminFailedMessagesResponse,
    AdminMetricsOverview,
    AdminNodeRead,
    AdminNodeUpdateRequest,
    AdminPaymentOrderRow,
    AdminPaymentOrdersResponse,
    AdminPlanCreateRequest,
    AdminPlanRow,
    AdminPlansResponse,
    AdminPlanUpdateRequest,
    AdminUserRow,
    AdminUsersResponse,
    AdminUserUpdateRequest,
)
from app.schemas.conversation import ConversationMessagesResponse, ConversationRead, MessageRead
from app.models.plan import Plan


class AdminService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.users = UserRepo(session)
        self.subscriptions = SubscriptionRepo(session)
        self.nodes = ModelNodeRepo(session)
        self.conversations = ConversationRepo(session)
        self.messages = MessageRepo(session)
        self.plans = PlanRepo(session)
        self.payment_orders = PaymentOrderRepo(session)

    async def list_users(
        self,
        *,
        search: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> AdminUsersResponse:
        users = await self.users.list_users(search=search, status=status, limit=limit, offset=offset)
        total = await self.users.count_users()
        items: list[AdminUserRow] = []
        for user in users:
            current_subscription = await self.subscriptions.get_current_for_user(user.id)
            items.append(
                AdminUserRow(
                    id=user.id,
                    email=user.email,
                    username=user.username,
                    status=user.status,
                    is_admin=user.is_admin,
                    last_login_at=user.last_login_at,
                    created_at=user.created_at,
                    subscription_status=current_subscription.status if current_subscription else None,
                    plan_code=current_subscription.plan.code if current_subscription else None,
                )
            )
        return AdminUsersResponse(items=items, total=total)

    async def update_user(self, user_id: str, payload: AdminUserUpdateRequest) -> AdminUserRow:
        user = await self.users.get_by_id(user_id)
        if not user:
            raise AppException(404, "USER_NOT_FOUND", "user not found")
        if payload.status is not None:
            user.status = payload.status
        if payload.is_admin is not None:
            user.is_admin = payload.is_admin
        await self.session.commit()
        current_subscription = await self.subscriptions.get_current_for_user(user.id)
        return AdminUserRow(
            id=user.id,
            email=user.email,
            username=user.username,
            status=user.status,
            is_admin=user.is_admin,
            last_login_at=user.last_login_at,
            created_at=user.created_at,
            subscription_status=current_subscription.status if current_subscription else None,
            plan_code=current_subscription.plan.code if current_subscription else None,
        )

    async def metrics_overview(self) -> AdminMetricsOverview:
        total_users = await self.users.count_users()
        active_subscriptions = await self.subscriptions.count_active()
        total_conversations = await self.conversations.count_all()
        total_messages = await self.messages.count_total()
        assistant_success_today, assistant_failed_today = await self.messages.count_assistant_messages_today()
        tokens_today = await self.messages.sum_tokens_today()
        return AdminMetricsOverview(
            total_users=total_users,
            active_subscriptions=active_subscriptions,
            total_conversations=total_conversations,
            total_messages=total_messages,
            assistant_success_today=assistant_success_today,
            assistant_failed_today=assistant_failed_today,
            tokens_today=tokens_today,
        )

    async def list_nodes(self) -> list[AdminNodeRead]:
        nodes = await self.nodes.list_all()
        return [AdminNodeRead.model_validate(node, from_attributes=True) for node in nodes]

    async def update_node(self, node_id: str, payload: AdminNodeUpdateRequest) -> AdminNodeRead:
        node = await self.nodes.get_by_id(node_id)
        if not node:
            raise AppException(404, "NODE_NOT_FOUND", "node not found")
        if payload.enabled is not None:
            node.enabled = payload.enabled
        if payload.status is not None:
            node.status = payload.status
        if payload.weight is not None:
            node.weight = payload.weight
        if payload.priority is not None:
            node.priority = payload.priority
        await self.nodes.update(node)
        await self.session.commit()
        return AdminNodeRead.model_validate(node, from_attributes=True)

    async def list_conversations(self, *, search: str | None = None, limit: int = 50, offset: int = 0) -> AdminConversationsResponse:
        conversations = await self.conversations.list_admin(search=search, limit=limit, offset=offset)
        return AdminConversationsResponse(
            items=[
                AdminConversationRow(
                    id=item.id,
                    user_id=item.user_id,
                    user_email=item.user.email,
                    title=item.title,
                    latest_model=item.latest_model,
                    latest_message_at=item.latest_message_at,
                    message_count=item.message_count,
                    archived=item.archived,
                    pinned=item.pinned,
                )
                for item in conversations
            ]
        )

    async def get_conversation_messages(self, conversation_id: str) -> ConversationMessagesResponse:
        conversation = await self.conversations.get_by_id(conversation_id)
        if not conversation or conversation.deleted_at is not None:
            raise AppException(404, "CONVERSATION_NOT_FOUND", "conversation not found")
        messages = await self.messages.list_for_conversation(conversation_id)
        return ConversationMessagesResponse(
            conversation=ConversationRead.model_validate(conversation, from_attributes=True),
            messages=[MessageRead.model_validate(message, from_attributes=True) for message in messages],
        )

    async def list_failed_messages(self, *, limit: int = 50) -> AdminFailedMessagesResponse:
        failed_messages = await self.messages.list_failed(limit=limit)
        return AdminFailedMessagesResponse(
            items=[
                AdminFailedMessageRow(
                    id=item.id,
                    conversation_id=item.conversation_id,
                    user_id=item.user_id,
                    content_text=item.content_text,
                    error_code=item.error_code,
                    error_message=item.error_message,
                    created_at=item.created_at,
                )
                for item in failed_messages
            ]
        )

    async def list_plans(self) -> AdminPlansResponse:
        plans = await self.plans.list_all()
        return AdminPlansResponse(items=[AdminPlanRow.model_validate(plan, from_attributes=True) for plan in plans])

    async def create_plan(self, payload: AdminPlanCreateRequest) -> AdminPlanRow:
        if await self.plans.get_any_by_code(payload.code):
            raise AppException(409, "PLAN_ALREADY_EXISTS", "plan code already exists")
        plan = await self.plans.create(Plan(**payload.model_dump()))
        await self.session.commit()
        return AdminPlanRow.model_validate(plan, from_attributes=True)

    async def update_plan(self, plan_id: str, payload: AdminPlanUpdateRequest) -> AdminPlanRow:
        plan = await self.plans.get_by_id(plan_id)
        if not plan:
            raise AppException(404, "PLAN_NOT_FOUND", "plan not found")
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(plan, field, value)
        await self.plans.update(plan)
        await self.session.commit()
        return AdminPlanRow.model_validate(plan, from_attributes=True)

    async def list_payment_orders(self, *, search: str | None = None, limit: int = 50, offset: int = 0) -> AdminPaymentOrdersResponse:
        orders = await self.payment_orders.list_admin(search=search, limit=limit, offset=offset)
        return AdminPaymentOrdersResponse(
            items=[
                AdminPaymentOrderRow(
                    id=item.id,
                    user_email=item.user.email,
                    plan_code=item.plan.code,
                    plan_name=item.plan.name,
                    provider=item.provider,
                    status=item.status,
                    merchant_order_id=item.merchant_order_id,
                    provider_trade_id=item.provider_trade_id,
                    amount_cents=item.amount_cents,
                    currency=item.currency,
                    checkout_url=item.checkout_url,
                    expires_at=item.expires_at,
                    paid_at=item.paid_at,
                    created_at=item.created_at,
                )
                for item in orders
            ]
        )
