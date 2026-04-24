from __future__ import annotations

from hashlib import md5
from typing import Any

from app.core.constants import PAYMENT_STATUS_EXPIRED, PAYMENT_STATUS_PAID, PAYMENT_STATUS_PENDING


def build_bepusdt_signature(payload: dict[str, Any], api_token: str) -> str:
    filtered: list[tuple[str, str]] = []
    for key, value in payload.items():
        if key == "signature" or value is None or value == "":
            continue
        filtered.append((key, str(value)))
    filtered.sort(key=lambda item: item[0])
    joined = "&".join(f"{key}={value}" for key, value in filtered)
    return md5(f"{joined}{api_token}".encode("utf-8")).hexdigest()


def normalize_bepusdt_status(value: Any) -> str:
    normalized = str(value or "").strip()
    if normalized == "2":
        return PAYMENT_STATUS_PAID
    if normalized == "3":
        return PAYMENT_STATUS_EXPIRED
    return PAYMENT_STATUS_PENDING


def extract_bepusdt_meta(payload: dict[str, Any] | None, payment_token: str | None = None) -> dict[str, Any]:
    raw = payload or {}
    actual_amount = raw.get("actual_amount")
    return {
        "actual_amount": float(actual_amount) if actual_amount is not None else None,
        "payment_address": str(raw.get("token") or payment_token or "") or None,
        "block_transaction_id": str(raw.get("block_transaction_id") or "") or None,
    }
