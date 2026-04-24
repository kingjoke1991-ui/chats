from app.schemas.conversation import ConversationCreateRequest, ConversationUpdateRequest


def test_create_conversation_request_accepts_empty_title() -> None:
    payload = ConversationCreateRequest()
    assert payload.title is None


def test_update_conversation_request_fields() -> None:
    payload = ConversationUpdateRequest(title="hello", pinned=True, archived=False)
    assert payload.title == "hello"
    assert payload.pinned is True
    assert payload.archived is False
