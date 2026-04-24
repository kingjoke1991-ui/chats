from pydantic import ValidationError

from app.schemas.chat import ChatCompletionRequest


def test_chat_request_defaults() -> None:
    payload = ChatCompletionRequest(messages=[{"role": "user", "content": "hello"}])
    assert payload.stream is False
    assert payload.messages[0].role == "user"


def test_chat_request_rejects_empty_content() -> None:
    try:
        ChatCompletionRequest(messages=[{"role": "user", "content": "   "}])
    except ValidationError as exc:
        assert "content must not be empty" in str(exc)
    else:
        raise AssertionError("validation error expected")
