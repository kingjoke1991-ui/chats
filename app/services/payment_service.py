from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from uuid import uuid4

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.constants import (
    PAYMENT_PROVIDER_BEPUSDT,
    PAYMENT_STATUS_EXPIRED,
    PAYMENT_STATUS_FAILED,
    PAYMENT_STATUS_PAID,
    PAYMENT_STATUS_PENDING,
)
from app.core.exceptions import AppException
from app.core.payment_utils import build_bepusdt_signature, extract_bepusdt_meta, normalize_bepusdt_status
from app.models.payment_order import PaymentOrder
from app.repos.payment_order_repo import PaymentOrderRepo
from app.repos.plan_repo import PlanRepo
from app.schemas.payment import CheckoutSessionResponse, PaymentOrderRead, PaymentOrdersResponse
from app.services.subscription_service import SubscriptionService


PROVIDER_STATUS_WAITING = "1"
PROVIDER_STATUS_SUCCESS = "2"
PROVIDER_STATUS_TIMEOUT = "3"


@dataclass
class BepusdtOrderResult:
    trade_id: str
    payment_url: str
    payment_token: str | None
    actual_amount: float | None
    expires_at: datetime | None
    status: str
    block_transaction_id: str | None
    raw: dict[str, Any]


class PaymentService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.plans = PlanRepo(session)
        self.orders = PaymentOrderRepo(session)
        self.subscriptions = SubscriptionService(session)

    async def create_checkout_session(self, *, user_id: str, plan_code: str) -> CheckoutSessionResponse:
        self._ensure_bepusdt_configured()

        plan = await self.plans.get_by_code(plan_code)
        if not plan:
            raise AppException(404, "PLAN_NOT_FOUND", "plan not found")
        if plan.monthly_price_cents <= 0:
            raise AppException(400, "PLAN_NOT_PAYABLE", "free plan does not require checkout")

        existing = await self.orders.get_latest_pending_for_user_plan(user_id, plan.id)
        if existing:
            if existing.provider_trade_id:
                await self._sync_order_with_provider(existing)
                await self.session.commit()
            if existing.status == PAYMENT_STATUS_PENDING and existing.checkout_url:
                return CheckoutSessionResponse(
                    status=existing.status,
                    provider=existing.provider,
                    checkout_url=existing.checkout_url,
                    detail="reused existing pending order",
                    order=self._serialize_order(existing),
                )
            if existing.status == PAYMENT_STATUS_PAID:
                return CheckoutSessionResponse(
                    status=existing.status,
                    provider=existing.provider,
                    checkout_url=existing.checkout_url,
                    detail="latest order already paid",
                    order=self._serialize_order(existing),
                )

        now = datetime.now(UTC)
        merchant_order_id = f"sub_{uuid4().hex}"
        order = await self.orders.create(
            PaymentOrder(
                user_id=user_id,
                plan_id=plan.id,
                provider=PAYMENT_PROVIDER_BEPUSDT,
                merchant_order_id=merchant_order_id,
                status=PAYMENT_STATUS_PENDING,
                amount_cents=plan.monthly_price_cents,
                currency=plan.currency.upper(),
                redirect_url=self._build_redirect_url(),
                created_at=now,
                updated_at=now,
            )
        )
        order.plan = plan

        try:
            provider_order = await self._create_bepusdt_order(order, plan)
            await self._apply_provider_update(order, provider_order.raw, source="create_order")
        except Exception:
            order.status = PAYMENT_STATUS_FAILED
            await self.orders.update(order)
            await self.session.commit()
            raise

        await self.orders.update(order)
        await self.session.commit()
        return CheckoutSessionResponse(
            status=order.status,
            provider=order.provider,
            checkout_url=order.checkout_url,
            detail="checkout session created",
            order=self._serialize_order(order, plan_code=plan.code, plan_name=plan.name),
        )

    async def list_orders_for_user(self, user_id: str, *, sync_pending: bool = False) -> PaymentOrdersResponse:
        if sync_pending:
            await self.sync_pending_orders_for_user(user_id)
        orders = await self.orders.list_for_user(user_id)
        return PaymentOrdersResponse(items=[self._serialize_order(order) for order in orders])

    async def sync_pending_orders_for_user(self, user_id: str) -> PaymentOrdersResponse:
        orders = await self.orders.list_syncable_pending_for_user(user_id)
        for order in orders:
            await self._sync_order_with_provider(order)
        await self.session.commit()
        refreshed = await self.orders.list_for_user(user_id)
        return PaymentOrdersResponse(items=[self._serialize_order(order) for order in refreshed])

    async def handle_bepusdt_webhook(self, payload: dict[str, Any]) -> str:
        self._ensure_bepusdt_configured()
        signature = payload.get("signature")
        if not signature or build_bepusdt_signature(payload, settings.bepusdt_api_token or "") != signature:
            raise AppException(400, "INVALID_SIGNATURE", "invalid BEpusdt signature")

        trade_id = str(payload.get("trade_id") or "")
        merchant_order_id = str(payload.get("order_id") or "")
        order = None
        if trade_id:
            order = await self.orders.get_by_provider_trade_id(trade_id)
        if not order and merchant_order_id:
            order = await self.orders.get_by_merchant_order_id(merchant_order_id)
        if not order:
            raise AppException(404, "ORDER_NOT_FOUND", "payment order not found")

        await self._apply_provider_update(order, payload, source="webhook")
        await self.orders.update(order)
        await self.session.commit()
        return "ok"

    def _ensure_bepusdt_configured(self) -> None:
        if not settings.bepusdt_base_url or not settings.bepusdt_api_token:
            raise AppException(503, "PAYMENT_NOT_CONFIGURED", "BEpusdt is not configured")

    def _build_redirect_url(self) -> str:
        path = settings.bepusdt_redirect_path.strip()
        if path.startswith("http://") or path.startswith("https://"):
            return path
        if not path.startswith("/"):
            path = f"/{path}"
        return f"{settings.resolved_public_base_url}{path}"

    async def _create_bepusdt_order(self, order: PaymentOrder, plan) -> BepusdtOrderResult:
        amount = (Decimal(order.amount_cents) / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        payload = {
            "order_id": order.merchant_order_id,
            "amount": int(amount) if amount == amount.to_integral_value() else float(amount),
            "notify_url": f"{settings.resolved_public_base_url}/v1/payments/webhook/bepusdt",
            "redirect_url": order.redirect_url,
            "trade_type": str(plan.features_json.get("trade_type") or settings.bepusdt_trade_type),
            "timeout": settings.bepusdt_timeout_seconds,
            "fiat": order.currency.upper(),
            "name": plan.name,
        }
        payload["signature"] = build_bepusdt_signature(payload, settings.bepusdt_api_token or "")

        response_json = await self._post_bepusdt("/api/v1/order/create-transaction", payload)
        data = response_json.get("data") or {}
        status_code = response_json.get("status_code")
        if status_code != 200:
            raise AppException(
                502,
                "PAYMENT_PROVIDER_ERROR",
                str(response_json.get("message") or "payment provider rejected order"),
            )

        expires_at = None
        expiration_seconds = data.get("expiration_time")
        if expiration_seconds is not None:
            expires_at = datetime.now(UTC) + timedelta(seconds=int(expiration_seconds))

        raw_payload = dict(data)
        raw_payload["order_id"] = order.merchant_order_id
        raw_payload["fiat"] = order.currency.upper()
        return BepusdtOrderResult(
            trade_id=str(data.get("trade_id") or ""),
            payment_url=str(data.get("payment_url") or ""),
            payment_token=str(data.get("token") or "") or None,
            actual_amount=float(data["actual_amount"]) if data.get("actual_amount") is not None else None,
            expires_at=expires_at,
            status=self._normalize_provider_status(data.get("status")),
            block_transaction_id=str(data.get("block_transaction_id") or "") or None,
            raw=raw_payload,
        )

    async def _sync_order_with_provider(self, order: PaymentOrder) -> PaymentOrder:
        if not order.provider_trade_id or order.status == PAYMENT_STATUS_PAID:
            return order
        payload = await self._query_bepusdt_order(order.provider_trade_id)
        await self._apply_provider_update(order, payload, source="query_order")
        await self.orders.update(order)
        return order

    async def _query_bepusdt_order(self, trade_id: str) -> dict[str, Any]:
        assert settings.bepusdt_base_url
        try:
            async with httpx.AsyncClient(
                base_url=settings.bepusdt_base_url.rstrip("/"),
                timeout=settings.bepusdt_request_timeout_seconds,
            ) as client:
                response = await client.get(f"/pay/check-status/{trade_id}")
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise AppException(502, "PAYMENT_PROVIDER_UNAVAILABLE", f"BEpusdt query failed: {exc}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise AppException(502, "PAYMENT_PROVIDER_INVALID_RESPONSE", "BEpusdt returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise AppException(502, "PAYMENT_PROVIDER_INVALID_RESPONSE", "BEpusdt returned unexpected payload")
        return payload

    async def _apply_provider_update(self, order: PaymentOrder, payload: dict[str, Any], *, source: str) -> None:
        now = datetime.now(UTC)
        merged_payload = dict(order.provider_payload_json or {})
        merged_payload.update({key: value for key, value in payload.items() if value not in (None, "")})
        merged_payload["last_source"] = source

        trade_id = str(payload.get("trade_id") or order.provider_trade_id or "")
        payment_url = str(payload.get("payment_url") or order.checkout_url or "")
        payment_token = str(payload.get("token") or order.payment_token or "")
        block_transaction_id = str(payload.get("block_transaction_id") or merged_payload.get("block_transaction_id") or "")
        status = self._normalize_provider_status(payload.get("status"))

        expiration_value = payload.get("expiration_time")
        if expiration_value is not None:
            order.expires_at = now + timedelta(seconds=int(expiration_value))
            merged_payload["expiration_time"] = int(expiration_value)

        if trade_id:
            order.provider_trade_id = trade_id
            merged_payload["trade_id"] = trade_id
        if payment_url:
            order.checkout_url = payment_url
            merged_payload["payment_url"] = payment_url
        if payment_token:
            order.payment_token = payment_token
            merged_payload["token"] = payment_token
        if block_transaction_id:
            merged_payload["block_transaction_id"] = block_transaction_id
        if payload.get("actual_amount") is not None:
            merged_payload["actual_amount"] = payload.get("actual_amount")
        if payload.get("order_id"):
            merged_payload["order_id"] = payload.get("order_id")
        if payload.get("fiat"):
            merged_payload["fiat"] = payload.get("fiat")

        order.provider_payload_json = merged_payload
        order.updated_at = now

        if order.status == PAYMENT_STATUS_PAID and status != PAYMENT_STATUS_PAID:
            merged_payload["status"] = PROVIDER_STATUS_SUCCESS
            return

        if status == PAYMENT_STATUS_PAID:
            if order.status != PAYMENT_STATUS_PAID:
                order.status = PAYMENT_STATUS_PAID
                order.paid_at = now
                merged_payload["status"] = PROVIDER_STATUS_SUCCESS
                await self._activate_subscription_if_paid(order)
            order.canceled_at = None
        elif status == PAYMENT_STATUS_EXPIRED:
            order.status = PAYMENT_STATUS_EXPIRED
            order.canceled_at = order.canceled_at or now
            merged_payload["status"] = PROVIDER_STATUS_TIMEOUT
        else:
            order.status = PAYMENT_STATUS_PENDING
            merged_payload["status"] = PROVIDER_STATUS_WAITING

    async def _activate_subscription_if_paid(self, order: PaymentOrder) -> None:
        period_days = int(order.plan.features_json.get("billing_period_days", 30))
        await self.subscriptions.activate_plan_after_payment(
            user_id=order.user_id,
            plan_id=order.plan_id,
            provider_subscription_id=order.provider_trade_id or order.merchant_order_id,
            period_days=period_days,
        )

    @staticmethod
    def _normalize_provider_status(value: Any) -> str:
        return normalize_bepusdt_status(value)

    async def _post_bepusdt(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        assert settings.bepusdt_base_url
        try:
            async with httpx.AsyncClient(
                base_url=settings.bepusdt_base_url.rstrip("/"),
                timeout=settings.bepusdt_request_timeout_seconds,
            ) as client:
                response = await client.post(path, json=payload)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise AppException(502, "PAYMENT_PROVIDER_UNAVAILABLE", f"BEpusdt request failed: {exc}") from exc
        try:
            body = response.json()
        except ValueError as exc:
            raise AppException(502, "PAYMENT_PROVIDER_INVALID_RESPONSE", "BEpusdt returned invalid JSON") from exc
        if not isinstance(body, dict):
            raise AppException(502, "PAYMENT_PROVIDER_INVALID_RESPONSE", "BEpusdt returned unexpected payload")
        return body

    def _serialize_order(
        self,
        order: PaymentOrder,
        *,
        plan_code: str | None = None,
        plan_name: str | None = None,
    ) -> PaymentOrderRead:
        payload = order.provider_payload_json or {}
        provider_meta = extract_bepusdt_meta(payload, order.payment_token)
        return PaymentOrderRead(
            id=order.id,
            provider=order.provider,
            status=order.status,
            merchant_order_id=order.merchant_order_id,
            provider_trade_id=order.provider_trade_id,
            amount_cents=order.amount_cents,
            currency=order.currency,
            actual_amount=provider_meta["actual_amount"],
            payment_address=provider_meta["payment_address"],
            block_transaction_id=provider_meta["block_transaction_id"],
            checkout_url=order.checkout_url,
            payment_token=order.payment_token,
            expires_at=order.expires_at,
            paid_at=order.paid_at,
            created_at=order.created_at,
            plan_code=plan_code or order.plan.code,
            plan_name=plan_name or order.plan.name,
        )
