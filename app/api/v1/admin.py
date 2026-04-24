from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_admin, db_session
from app.schemas.admin import (
    AdminConversationsResponse,
    AdminFailedMessagesResponse,
    AdminMetricsOverview,
    AdminNodeRead,
    AdminNodeUpdateRequest,
    AdminPaymentOrdersResponse,
    AdminPlanCreateRequest,
    AdminPlanRow,
    AdminPlansResponse,
    AdminPlanUpdateRequest,
    AdminUserRow,
    AdminUsersResponse,
    AdminUserUpdateRequest,
)
from app.schemas.conversation import ConversationMessagesResponse
from app.schemas.user import UserRead
from app.services.admin_service import AdminService

router = APIRouter()


@router.get("/users", response_model=AdminUsersResponse)
async def admin_list_users(
    search: str | None = None,
    status: str | None = None,
    _: UserRead = Depends(current_admin),
    session: AsyncSession = Depends(db_session),
) -> AdminUsersResponse:
    return await AdminService(session).list_users(search=search, status=status)


@router.patch("/users/{user_id}", response_model=AdminUserRow)
async def admin_update_user(
    user_id: str,
    payload: AdminUserUpdateRequest,
    _: UserRead = Depends(current_admin),
    session: AsyncSession = Depends(db_session),
) -> AdminUserRow:
    return await AdminService(session).update_user(user_id, payload)


@router.get("/metrics/overview", response_model=AdminMetricsOverview)
async def admin_metrics_overview(
    _: UserRead = Depends(current_admin),
    session: AsyncSession = Depends(db_session),
) -> AdminMetricsOverview:
    return await AdminService(session).metrics_overview()


@router.get("/nodes", response_model=list[AdminNodeRead])
async def admin_list_nodes(
    _: UserRead = Depends(current_admin),
    session: AsyncSession = Depends(db_session),
) -> list[AdminNodeRead]:
    return await AdminService(session).list_nodes()


@router.patch("/nodes/{node_id}", response_model=AdminNodeRead)
async def admin_update_node(
    node_id: str,
    payload: AdminNodeUpdateRequest,
    _: UserRead = Depends(current_admin),
    session: AsyncSession = Depends(db_session),
) -> AdminNodeRead:
    return await AdminService(session).update_node(node_id, payload)


@router.get("/conversations", response_model=AdminConversationsResponse)
async def admin_list_conversations(
    search: str | None = None,
    _: UserRead = Depends(current_admin),
    session: AsyncSession = Depends(db_session),
) -> AdminConversationsResponse:
    return await AdminService(session).list_conversations(search=search)


@router.get("/conversations/{conversation_id}/messages", response_model=ConversationMessagesResponse)
async def admin_conversation_messages(
    conversation_id: str,
    _: UserRead = Depends(current_admin),
    session: AsyncSession = Depends(db_session),
) -> ConversationMessagesResponse:
    return await AdminService(session).get_conversation_messages(conversation_id)


@router.get("/failed-messages", response_model=AdminFailedMessagesResponse)
async def admin_failed_messages(
    _: UserRead = Depends(current_admin),
    session: AsyncSession = Depends(db_session),
) -> AdminFailedMessagesResponse:
    return await AdminService(session).list_failed_messages()


@router.get("/plans", response_model=AdminPlansResponse)
async def admin_list_plans(
    _: UserRead = Depends(current_admin),
    session: AsyncSession = Depends(db_session),
) -> AdminPlansResponse:
    return await AdminService(session).list_plans()


@router.post("/plans", response_model=AdminPlanRow)
async def admin_create_plan(
    payload: AdminPlanCreateRequest,
    _: UserRead = Depends(current_admin),
    session: AsyncSession = Depends(db_session),
) -> AdminPlanRow:
    return await AdminService(session).create_plan(payload)


@router.patch("/plans/{plan_id}", response_model=AdminPlanRow)
async def admin_update_plan(
    plan_id: str,
    payload: AdminPlanUpdateRequest,
    _: UserRead = Depends(current_admin),
    session: AsyncSession = Depends(db_session),
) -> AdminPlanRow:
    return await AdminService(session).update_plan(plan_id, payload)


@router.get("/payment-orders", response_model=AdminPaymentOrdersResponse)
async def admin_list_payment_orders(
    search: str | None = None,
    _: UserRead = Depends(current_admin),
    session: AsyncSession = Depends(db_session),
) -> AdminPaymentOrdersResponse:
    return await AdminService(session).list_payment_orders(search=search)
