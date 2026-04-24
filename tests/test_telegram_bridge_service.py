from types import SimpleNamespace

import pytest

from app.services.telegram_bridge_service import TELEGRAM_QUERY_COMMAND, TelegramBridgeService


HASH_QUERY = "#\u67e5\u8be2 \u5d14\u4e91\u9704"
PLAIN_QUERY = "\u67e5\u8be2 \u5d14\u4e91\u9704"
QUERY_TEXT = "\u5d14\u4e91\u9704"
FIRST_PAGE_TEXT = "\u7b2c\u4e00\u9875\u5185\u5bb9\n\u5f53\u524d\u9875\uff1a1 / 40"
TXT_TEXT = "\u5b8c\u6574 TXT \u5185\u5bb9"


def test_match_command_extracts_query_text_from_hash_query() -> None:
    service = TelegramBridgeService.__new__(TelegramBridgeService)

    matched = TelegramBridgeService.match_command(service, HASH_QUERY)

    assert matched == {
        "command": TELEGRAM_QUERY_COMMAND,
        "query_text": QUERY_TEXT,
        "bot_request_text": QUERY_TEXT,
    }


def test_match_command_returns_none_for_plain_query_message() -> None:
    service = TelegramBridgeService.__new__(TelegramBridgeService)

    matched = TelegramBridgeService.match_command(service, PLAIN_QUERY)

    assert matched is None


@pytest.mark.asyncio
async def test_execute_returns_first_page_plus_download_link_when_txt_exists() -> None:
    class FakeUserbotManager:
        async def ensure_bridge_ready(self) -> None:
            return None

        async def send_and_wait(self, text: str) -> dict:
            assert text == QUERY_TEXT
            return {
                "raw_text": TXT_TEXT,
                "outgoing_message_id": 11,
                "incoming_message_id": 22,
                "incoming_date": "2026-04-21T00:00:00+00:00",
                "primary_message": {"text": FIRST_PAGE_TEXT},
                "all_messages": [{"text": FIRST_PAGE_TEXT}],
                "used_txt_download": True,
                "downloaded_file": {"file_name": "result.txt", "mime_type": "text/plain"},
            }

    class FakeDownloadService:
        async def create_download(self, *, text: str, file_name: str | None, mime_type: str | None):
            assert text == TXT_TEXT
            assert file_name == "result.txt"
            assert mime_type == "text/plain"
            return {
                "download_id": "dl-1",
                "token": "tok-1",
                "url": "https://example.com/dl-1",
            }

    service = TelegramBridgeService(
        session=SimpleNamespace(),
        userbot_manager=FakeUserbotManager(),
        download_service=FakeDownloadService(),
    )

    result = await service.execute(
        query_text=QUERY_TEXT,
        bot_request_text=QUERY_TEXT,
        allowed_models=[],
        requested_model=None,
    )

    assert FIRST_PAGE_TEXT in result.content
    assert "https://example.com/dl-1" in result.content
    assert result.metadata["txt_download_url"] == "https://example.com/dl-1"
    assert result.metadata["used_txt_download"] is True


@pytest.mark.asyncio
async def test_execute_returns_raw_text_when_no_txt_download_exists() -> None:
    class FakeUserbotManager:
        async def ensure_bridge_ready(self) -> None:
            return None

        async def send_and_wait(self, text: str) -> dict:
            assert text == QUERY_TEXT
            return {
                "raw_text": FIRST_PAGE_TEXT,
                "outgoing_message_id": 11,
                "incoming_message_id": 22,
                "incoming_date": "2026-04-21T00:00:00+00:00",
                "primary_message": {"text": FIRST_PAGE_TEXT},
                "all_messages": [{"text": FIRST_PAGE_TEXT}],
                "used_txt_download": False,
                "downloaded_file": None,
            }

    service = TelegramBridgeService(
        session=SimpleNamespace(),
        userbot_manager=FakeUserbotManager(),
        download_service=SimpleNamespace(),
    )

    result = await service.execute(
        query_text=QUERY_TEXT,
        bot_request_text=QUERY_TEXT,
        allowed_models=[],
        requested_model=None,
    )

    assert result.content == FIRST_PAGE_TEXT
    assert "txt_download_url" not in result.metadata
