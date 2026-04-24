from datetime import UTC, datetime

from app.core.constants import MESSAGE_ROLE_ASSISTANT, MESSAGE_STATUS_COMPLETED, MESSAGE_STATUS_FAILED
from app.models.message import Message
from app.services.chat_service import ChatService


def build_message(
    *,
    content_json: dict | None,
    status: str = MESSAGE_STATUS_COMPLETED,
    role: str = MESSAGE_ROLE_ASSISTANT,
) -> Message:
    now = datetime.now(UTC)
    return Message(
        conversation_id="conv-1",
        user_id="user-1",
        role=role,
        content_text="",
        content_json=content_json,
        model="oracle-number-tool",
        status=status,
        created_at=now,
        updated_at=now,
    )


def test_extract_recent_phone_number_prefers_latest_get_number_message() -> None:
    messages = [
        build_message(content_json={"command": "get_number", "metadata": {"phone_number": "+358111"}}),
        build_message(content_json={"command": "read_cached_sms", "metadata": {"phone_number": "+358111"}}),
        build_message(content_json={"command": "get_number", "metadata": {"phone_number": "+358222"}}),
    ]

    phone_number = ChatService._extract_recent_phone_number_from_messages(messages)

    assert phone_number == "+358222"


def test_extract_recent_phone_number_ignores_failed_or_invalid_messages() -> None:
    messages = [
        build_message(
            content_json={"command": "get_number", "metadata": {"phone_number": "+358111"}},
            status=MESSAGE_STATUS_FAILED,
        ),
        build_message(content_json={"command": "get_number", "metadata": {}}),
        build_message(content_json=None),
    ]

    phone_number = ChatService._extract_recent_phone_number_from_messages(messages)

    assert phone_number is None
