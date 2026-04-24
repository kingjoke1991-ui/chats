from app.models.model_node import ModelNode
from app.providers.openai_compat import OpenAICompatProvider


def test_build_headers_prefers_node_api_key() -> None:
    node = ModelNode(
        code="telegram-audit-gemini",
        provider_type="openai_compat",
        provider_code="google-gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        api_key_encrypted="gemini-secret",
        model_name="gemini-1.5-pro",
        enabled=True,
        status="healthy",
        weight=1,
        priority=1,
        max_parallel_requests=1,
        current_parallel_requests=0,
        capability_json={},
        metadata_json={},
    )

    headers = OpenAICompatProvider._build_headers(node)

    assert headers["Authorization"] == "Bearer gemini-secret"


class _FakeResponse:
    def json(self):
        return [{"error": {"message": "bad request"}}]


def test_decode_response_accepts_single_item_list_payload() -> None:
    parsed = OpenAICompatProvider._decode_response(_FakeResponse())

    assert parsed["error"]["message"] == "bad request"
