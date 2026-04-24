import pytest

from app.core.exceptions import AppException
from app.services.phone_number_service import (
    PHONE_COMMAND_FETCH_LATEST_SMS,
    PHONE_COMMAND_GET_NUMBER,
    PHONE_COMMAND_READ_CACHED_SMS,
    PhoneNumberService,
)


class FakeRedis:
    def __init__(self) -> None:
        self.storage: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.storage.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.storage[key] = value


def test_match_command() -> None:
    service = PhoneNumberService(redis_client=FakeRedis())

    assert service.match_command("获取一个号码") == PHONE_COMMAND_GET_NUMBER
    assert service.match_command("读取当前号码缓存短信") == PHONE_COMMAND_READ_CACHED_SMS
    assert service.match_command("获取最新短信列表") == PHONE_COMMAND_FETCH_LATEST_SMS
    assert service.match_command("普通聊天内容") is None


@pytest.mark.asyncio
async def test_get_number_caches_phone(monkeypatch: pytest.MonkeyPatch) -> None:
    service = PhoneNumberService(redis_client=FakeRedis())

    async def fake_request_json(method: str, path: str, *, params=None):
        assert method == "GET"
        assert path == "number"
        assert params == {"country": "FI"}
        return {"number": {"phone": "+3584573998787"}}

    monkeypatch.setattr(service, "_request_json", fake_request_json)

    result = await service.execute(command=PHONE_COMMAND_GET_NUMBER, conversation_id="conv-1")

    assert result.metadata["phone_number"] == "+3584573998787"
    assert "当前号码：+3584573998787" in result.content
    assert await service.get_current_number("conv-1") == "+3584573998787"


@pytest.mark.asyncio
async def test_read_cached_sms_uses_cached_number(monkeypatch: pytest.MonkeyPatch) -> None:
    service = PhoneNumberService(redis_client=FakeRedis())
    await service.set_current_number("conv-1", "+3584573998787")

    async def fake_request_json(method: str, path: str, *, params=None):
        assert method == "GET"
        assert path == "sms/%2B3584573998787"
        assert params is None
        return {
            "messages": [
                {
                    "received_at": "2026-04-20T11:22:33Z",
                    "sender": "Verifier",
                    "content": "验证码 123456",
                }
            ]
        }

    monkeypatch.setattr(service, "_request_json", fake_request_json)

    result = await service.execute(command=PHONE_COMMAND_READ_CACHED_SMS, conversation_id="conv-1")

    assert "未触发抓取" in result.content
    assert "Verifier" in result.content
    assert "验证码 123456" in result.content


@pytest.mark.asyncio
async def test_fetch_latest_sms_posts_then_reads_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    service = PhoneNumberService(redis_client=FakeRedis())
    await service.set_current_number("conv-1", "+3584573998787")
    calls: list[tuple[str, str]] = []

    async def fake_sleep(_: int) -> None:
        return None

    async def fake_request_json(method: str, path: str, *, params=None):
        calls.append((method, path))
        if method == "POST":
            return {"ok": True}
        if len([item for item in calls if item[0] == "GET"]) <= 2:
            return {"messages": []}
        return {"messages": [{"content": "最新短信", "time": "2026-04-20 12:00:00"}]}

    monkeypatch.setattr("app.services.phone_number_service.asyncio.sleep", fake_sleep)
    monkeypatch.setattr(service, "_request_json", fake_request_json)

    result = await service.execute(command=PHONE_COMMAND_FETCH_LATEST_SMS, conversation_id="conv-1")

    assert calls == [
        ("GET", "sms/%2B3584573998787"),
        ("POST", "sms/%2B3584573998787/fetch"),
        ("GET", "sms/%2B3584573998787"),
        ("GET", "sms/%2B3584573998787"),
    ]
    assert "按 30 秒间隔轮询缓存" in result.content
    assert "最新短信" in result.content


@pytest.mark.asyncio
async def test_read_cached_sms_requires_current_number() -> None:
    service = PhoneNumberService(redis_client=FakeRedis())

    with pytest.raises(AppException) as exc_info:
        await service.execute(command=PHONE_COMMAND_READ_CACHED_SMS, conversation_id="conv-1")

    assert exc_info.value.error_code == "PHONE_NUMBER_REQUIRED"
