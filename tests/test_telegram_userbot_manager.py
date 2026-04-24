import asyncio
from types import SimpleNamespace

import pytest

from app.services.telegram_userbot_manager import TelegramUserbotManager


def build_message(
    *,
    text: str = "",
    buttons: list | None = None,
    file: object | None = None,
    message_id: int = 1,
):
    return SimpleNamespace(
        file=file,
        raw_text=text,
        text=text,
        buttons=buttons or [],
        id=message_id,
        date=None,
    )


def test_normalize_peer_adds_at_prefix() -> None:
    assert TelegramUserbotManager._normalize_peer("kalisgk_bot") == "@kalisgk_bot"
    assert TelegramUserbotManager._normalize_peer("@KaliCD") == "@KaliCD"


def test_normalize_peer_keeps_empty_string() -> None:
    assert TelegramUserbotManager._normalize_peer("   ") == ""


def test_find_txt_button_matches_download_label() -> None:
    button = SimpleNamespace(text="下载TXT")
    message = build_message(buttons=[[button]])

    matched = TelegramUserbotManager._find_txt_button(message)

    assert matched is button


def test_decode_text_bytes_supports_gbk() -> None:
    payload = "崔云霄".encode("gbk")

    decoded = TelegramUserbotManager._decode_text_bytes(payload)

    assert decoded == "崔云霄"


@pytest.mark.asyncio
async def test_maybe_download_text_file_uses_existing_document_message() -> None:
    manager = TelegramUserbotManager()
    manager._timestamped_file_name = lambda: "telegram-export-20260421-123000.txt"  # type: ignore[method-assign]
    message = build_message(
        file=SimpleNamespace(name="result.txt", mime_type="text/plain", size=12),
        message_id=8,
    )

    class FakeClient:
        async def download_media(self, current_message, file):
            assert current_message is message
            assert file is bytes
            return "完整内容".encode("utf-8")

    downloaded = await manager._maybe_download_text_file(
        client=FakeClient(),
        conversation=SimpleNamespace(),
        message=message,
    )

    assert downloaded == {
        "text": "完整内容",
        "file_name": "telegram-export-20260421-123000.txt",
        "mime_type": "text/plain",
        "size": 12,
    }


@pytest.mark.asyncio
async def test_maybe_download_text_file_waits_for_exported_url() -> None:
    manager = TelegramUserbotManager()
    manager._timestamped_file_name = lambda: "telegram-export-20260421-123001.txt"  # type: ignore[method-assign]

    class FakeButton:
        text = "导出TXT"
        url = None

        async def click(self) -> None:
            return None

    source = build_message(buttons=[[FakeButton()]], message_id=1)
    exported = build_message(text="导出成功 https://example.com/result.txt", message_id=1)

    class FakeConversation:
        def __init__(self) -> None:
            self._response_calls = 0
            self._edit_calls = 0

        async def get_response(self, timeout=None):
            self._response_calls += 1
            await asyncio.sleep(0.01)
            raise TimeoutError

        async def get_edit(self, timeout=None):
            self._edit_calls += 1
            await asyncio.sleep(0)
            if self._edit_calls == 1:
                return exported
            raise TimeoutError

    async def fake_download(url: str) -> dict:
        assert url == "https://example.com/result.txt"
        return {
            "text": "TXT 全量内容",
            "file_name": "result.txt",
            "mime_type": "text/plain",
            "size": 99,
            "url": url,
        }

    manager._download_text_url = fake_download  # type: ignore[method-assign]

    downloaded = await manager._maybe_download_text_file(
        client=SimpleNamespace(),
        conversation=FakeConversation(),
        message=source,
    )

    assert downloaded["text"] == "TXT 全量内容"
    assert downloaded["source_message"]["text"] == "导出成功 https://example.com/result.txt"


@pytest.mark.asyncio
async def test_maybe_download_text_file_uses_click_result_url() -> None:
    manager = TelegramUserbotManager()
    manager._timestamped_file_name = lambda: "telegram-export-20260421-123002.txt"  # type: ignore[method-assign]

    class FakeButton:
        text = "导出TXT"
        url = None

        async def click(self):
            return SimpleNamespace(url="https://example.com/from-click.txt")

    message = build_message(buttons=[[FakeButton()]], message_id=1)

    async def fake_download(url: str) -> dict:
        assert url == "https://example.com/from-click.txt"
        return {
            "text": "TXT 点击回调内容",
            "file_name": "telegram-export-20260421-123002.txt",
            "mime_type": "text/plain",
            "size": 88,
            "url": url,
        }

    manager._download_text_url = fake_download  # type: ignore[method-assign]

    downloaded = await manager._maybe_download_text_file(
        client=SimpleNamespace(),
        conversation=SimpleNamespace(),
        message=message,
    )

    assert downloaded["text"] == "TXT 点击回调内容"


def test_find_export_candidate_prefers_export_success_message() -> None:
    first = build_message(text="第一页", message_id=1)
    export_success = build_message(text="导出成功，稍后下载", message_id=2)

    matched = TelegramUserbotManager._find_export_candidate([first, export_success])

    assert matched is export_success


@pytest.mark.asyncio
async def test_select_response_result_prefers_txt_download() -> None:
    manager = TelegramUserbotManager()
    first = build_message(text="处理中", message_id=1)
    second = build_message(
        text="导出数据",
        buttons=[[SimpleNamespace(text="导出txt", url="https://example.com/result.txt")]],
        message_id=2,
    )
    success = build_message(text="查询成功，共 3 页", message_id=3)

    async def fake_download(url: str) -> dict:
        assert url == "https://example.com/result.txt"
        return {
            "text": "TXT 全部内容",
            "file_name": "result.txt",
            "mime_type": "text/plain",
            "size": 20,
            "url": url,
        }

    manager._download_text_url = fake_download  # type: ignore[method-assign]

    result = await manager._select_response_result(
        client=SimpleNamespace(),
        conversation=SimpleNamespace(),
        messages=[first, second, success],
    )

    assert result["message"] is second
    assert result["downloaded_file"]["text"] == "TXT 全部内容"


@pytest.mark.asyncio
async def test_select_response_result_falls_back_to_success_message() -> None:
    manager = TelegramUserbotManager()
    first = build_message(text="处理中", message_id=1)
    success = build_message(text="查询成功，共 3 页", message_id=2)
    later = build_message(text="点击导出", message_id=3)

    result = await manager._select_response_result(
        client=SimpleNamespace(),
        conversation=SimpleNamespace(),
        messages=[first, success, later],
    )

    assert result["message"] is success
    assert result["downloaded_file"] is None


@pytest.mark.asyncio
async def test_collect_followup_updates_replaces_edited_message() -> None:
    manager = TelegramUserbotManager()
    placeholder = build_message(text="处理中", message_id=1)
    edited = build_message(text="查询成功，共 3 页", message_id=1)

    class FakeConversation:
        def __init__(self) -> None:
            self._response_calls = 0
            self._edit_calls = 0

        async def get_response(self, timeout=None):
            self._response_calls += 1
            await asyncio.sleep(0.01)
            raise TimeoutError

        async def get_edit(self, timeout=None):
            self._edit_calls += 1
            await asyncio.sleep(0)
            if self._edit_calls == 1:
                return edited
            raise TimeoutError

    collected = await manager._collect_followup_updates(
        conversation=FakeConversation(),
        messages=[placeholder],
    )

    assert len(collected) == 1
    assert collected[0].raw_text == "查询成功，共 3 页"
