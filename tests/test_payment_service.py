from app.core.constants import PAYMENT_STATUS_EXPIRED, PAYMENT_STATUS_PAID, PAYMENT_STATUS_PENDING
from app.core.payment_utils import build_bepusdt_signature, extract_bepusdt_meta, normalize_bepusdt_status


def test_build_bepusdt_signature_ignores_signature_and_empty_values() -> None:
    payload = {
        "order_id": "20220201030210321",
        "amount": 42,
        "notify_url": "http://example.com/notify",
        "redirect_url": "http://example.com/redirect",
        "signature": "ignored",
        "empty": "",
        "missing": None,
    }
    token = "epusdt_password_xasddawqe"
    assert build_bepusdt_signature(payload, token) == "1cd4b52df5587cfb1968b0c0c6e156cd"


def test_normalize_bepusdt_status_maps_provider_codes() -> None:
    assert normalize_bepusdt_status(1) == PAYMENT_STATUS_PENDING
    assert normalize_bepusdt_status("2") == PAYMENT_STATUS_PAID
    assert normalize_bepusdt_status(3) == PAYMENT_STATUS_EXPIRED
    assert normalize_bepusdt_status("unexpected") == PAYMENT_STATUS_PENDING


def test_extract_bepusdt_meta_reads_provider_payload() -> None:
    meta = extract_bepusdt_meta(
        {
            "actual_amount": "4.123",
            "token": "TXYZ123456",
            "block_transaction_id": "0xabc",
        }
    )
    assert meta == {
        "actual_amount": 4.123,
        "payment_address": "TXYZ123456",
        "block_transaction_id": "0xabc",
    }


def test_extract_bepusdt_meta_falls_back_to_saved_payment_token() -> None:
    meta = extract_bepusdt_meta({}, "TSAVEDTOKEN")
    assert meta["actual_amount"] is None
    assert meta["payment_address"] == "TSAVEDTOKEN"
    assert meta["block_transaction_id"] is None
