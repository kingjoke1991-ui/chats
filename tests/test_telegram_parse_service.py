from app.services.telegram_parse_service import TelegramParseService


def test_coerce_json_reads_fenced_json_block() -> None:
    model_output = """```json
{"name":"张三","amount":"100"}
```"""

    parsed = TelegramParseService._coerce_json(model_output, "raw telegram text")

    assert parsed["name"] == "张三"
    assert parsed["amount"] == "100"
    assert parsed["raw_text"] == "raw telegram text"


def test_coerce_json_falls_back_when_model_output_is_not_json() -> None:
    parsed = TelegramParseService._coerce_json("not valid json", "raw telegram text")

    assert parsed["raw_text"] == "raw telegram text"
    assert parsed["parse_error"] == "model did not return valid JSON"


def test_audit_model_candidates_include_gemini_fallbacks() -> None:
    models = TelegramParseService._audit_model_candidates("google-gemini", "gemini-1.5-pro")

    assert models[0] == "gemini-1.5-pro"
    assert "gemini-2.5-pro" in models
