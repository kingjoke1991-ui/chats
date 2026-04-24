from types import SimpleNamespace

import pytest

from app.core.exceptions import AppException
from app.services.qiandu_search import QIANDU_SEARCH_COMMAND, QianduSearchService
from app.services.qiandu_search.llm import QianduSearchLLMOrchestrator
from app.services.qiandu_search.models import (
    QianduEvidenceChunk,
    QianduExtractedDocument,
    QianduIntelExtraction,
    QianduSearchPlan,
    QianduSearchResult,
    QianduSearchTask,
)


def test_match_command_extracts_query_text() -> None:
    service = QianduSearchService.__new__(QianduSearchService)

    matched = QianduSearchService.match_command(service, "#千度 张三 法人")

    assert matched == {
        "command": QIANDU_SEARCH_COMMAND,
        "query_text": "张三 法人",
    }


@pytest.mark.asyncio
async def test_execute_prefers_provider_mix_and_sources() -> None:
    class FakeLLM:
        async def build_plan(self, *, query_text: str, allowed_models: list[str], requested_model: str | None):
            del allowed_models
            del requested_model
            return QianduSearchPlan(
                query=query_text,
                queries=[query_text, f"{query_text} 企查查"],
                intent="legal_entity",
                preferred_providers=["tavily", "exa"],
            )

        async def synthesize_answer(
            self,
            *,
            query_text: str,
            plan: QianduSearchPlan,
            evidence_chunks: list[QianduEvidenceChunk],
            allowed_models: list[str],
            requested_model: str | None,
        ) -> str:
            del allowed_models
            del requested_model
            assert query_text == "深圳腾讯 法人"
            assert plan.intent == "legal_entity"
            assert evidence_chunks
            return "结论：抓到了企业主体和法人线索。"

    class FakeProvider:
        def __init__(self, name: str, score: float, snippet: str, url: str):
            self.name = name
            self._score = score
            self._snippet = snippet
            self._url = url

        def is_enabled(self) -> bool:
            return True

        async def search(self, plan: QianduSearchPlan) -> list[QianduSearchResult]:
            return [
                QianduSearchResult(
                    title=f"{self.name} result",
                    url=self._url,
                    snippet=self._snippet,
                    score=self._score,
                    provider=self.name,
                )
            ]

    class FakeExtractor:
        name = "fake-extractor"

        def is_enabled(self) -> bool:
            return True

        async def extract(self, results: list[QianduSearchResult]) -> list[QianduExtractedDocument]:
            return [
                QianduExtractedDocument(
                    title=item.title,
                    url=item.url,
                    content=f"{item.title} 正文，包含法人、股东、注册资本等线索。",
                    provider=self.name,
                )
                for item in results
            ]

    service = QianduSearchService(
        session=SimpleNamespace(),
        llm=FakeLLM(),
        providers=[
            FakeProvider("tavily", 0.9, "企业主体基础信息和法人。", "https://example.com/a"),
            FakeProvider("exa", 0.8, "深度语义命中企业资料。", "https://example.com/b"),
        ],
        extractors=[FakeExtractor()],
    )

    result = await service.execute(
        query_text="深圳腾讯 法人",
        allowed_models=[],
        requested_model=None,
    )

    assert "结论：" in result.content
    assert "来源：" in result.content
    assert "https://example.com/a" in result.content
    assert result.metadata["plan"]["intent"] == "legal_entity"
    assert result.metadata["providers"] == ["tavily", "exa"]


@pytest.mark.asyncio
async def test_execute_raises_when_no_provider_is_enabled() -> None:
    class DisabledProvider:
        name = "disabled"

        def is_enabled(self) -> bool:
            return False

        async def search(self, plan: QianduSearchPlan) -> list[QianduSearchResult]:
            del plan
            return []

    service = QianduSearchService(
        session=SimpleNamespace(),
        llm=SimpleNamespace(),
        providers=[DisabledProvider()],
        extractors=[],
    )

    with pytest.raises(AppException) as exc_info:
        await service.execute(query_text="测试", allowed_models=[], requested_model=None)

    assert exc_info.value.error_code == "QIANDU_NOT_CONFIGURED"


@pytest.mark.asyncio
async def test_execute_skips_broken_provider_and_falls_back_answer() -> None:
    class FakeLLM:
        async def build_plan(self, *, query_text: str, allowed_models: list[str], requested_model: str | None):
            del allowed_models
            del requested_model
            return QianduSearchPlan(query=query_text, queries=[query_text], intent="general")

        async def synthesize_answer(
            self,
            *,
            query_text: str,
            plan: QianduSearchPlan,
            evidence_chunks: list[QianduEvidenceChunk],
            allowed_models: list[str],
            requested_model: str | None,
        ) -> str:
            del query_text
            del plan
            del evidence_chunks
            del allowed_models
            del requested_model
            raise RuntimeError("llm offline")

    class BrokenProvider:
        name = "broken"

        def is_enabled(self) -> bool:
            return True

        async def search(self, plan: QianduSearchPlan) -> list[QianduSearchResult]:
            del plan
            raise RuntimeError("boom")

    class GoodProvider:
        name = "tavily"

        def is_enabled(self) -> bool:
            return True

        async def search(self, plan: QianduSearchPlan) -> list[QianduSearchResult]:
            return [
                QianduSearchResult(
                    title="evidence",
                    url="https://example.com/evidence",
                    snippet=f"{plan.query} related evidence",
                    score=1.0,
                    provider=self.name,
                )
            ]

    class BrokenExtractor:
        name = "broken-extractor"

        def is_enabled(self) -> bool:
            return True

        async def extract(self, results: list[QianduSearchResult]) -> list[QianduExtractedDocument]:
            del results
            raise RuntimeError("extractor failed")

    service = QianduSearchService(
        session=SimpleNamespace(),
        llm=FakeLLM(),
        providers=[BrokenProvider(), GoodProvider()],
        extractors=[BrokenExtractor()],
    )

    result = await service.execute(query_text="OpenAI 最新模型", allowed_models=[], requested_model=None)

    assert "已完成检索" in result.content
    assert "https://example.com/evidence" in result.content


# --- Heuristic / intel pipeline tests --------------------------------------


def test_heuristic_entity_extraction_picks_up_identifiers() -> None:
    extraction = QianduSearchLLMOrchestrator.heuristic_entity_extraction(
        "姓名：李雷 手机号 13800001234 公司：北京字节跳动科技有限公司 邮箱 test@example.com @lei_han"
    )
    assert "李雷" in extraction.names
    assert "13800001234" in extraction.phones
    assert any("字节跳动" in org for org in extraction.organizations)
    assert extraction.other_fields.get("邮箱") == ["test@example.com"]
    assert "@lei_han" in extraction.other_fields.get("社交账号", [])
    assert extraction.data_quality == "high"


def test_heuristic_generate_tasks_covers_all_dimensions() -> None:
    extraction = QianduIntelExtraction(
        summary="姓名=张伟；组织=某某集团",
        names=["张伟"],
        phones=[],
        id_numbers=[],
        addresses=[],
        organizations=["某某集团"],
        other_fields={},
        data_quality="medium",
        raw_input="张伟 某某集团",
    )
    tasks = QianduSearchLLMOrchestrator.heuristic_generate_tasks(extraction)
    dimensions = {task.task_type for task in tasks}
    for required in ("business", "judicial", "education", "profession", "social", "wechat", "news"):
        assert required in dimensions, f"missing dimension {required}"


def test_should_trigger_intel_pipeline_signal_driven() -> None:
    orchestrator = QianduSearchLLMOrchestrator.__new__(QianduSearchLLMOrchestrator)
    # A bare common Chinese name has no OSINT signal — intel pipeline is
    # far too expensive to fire for this. Simple pipeline handles it.
    assert orchestrator.should_trigger_intel_pipeline("张三") is False
    # Name + dimension keyword → clear OSINT target.
    assert orchestrator.should_trigger_intel_pipeline("张三 深圳 法人") is True
    # Phone alone is enough (2-point signal).
    assert orchestrator.should_trigger_intel_pipeline("13800001234") is True
    # Id number alone is enough.
    assert orchestrator.should_trigger_intel_pipeline("110101199001011234") is True
    # Handle + dimension keyword (social).
    assert orchestrator.should_trigger_intel_pipeline("@alice_li 小红书") is True
    # Bare URLs should not trigger the expensive multi-dimension pipeline.
    assert orchestrator.should_trigger_intel_pipeline("https://example.com/page") is False
    assert orchestrator.should_trigger_intel_pipeline("") is False


def test_classify_trigger_returns_scoring_metadata() -> None:
    orchestrator = QianduSearchLLMOrchestrator.__new__(QianduSearchLLMOrchestrator)
    verdict = orchestrator.classify_trigger("张三 深圳 法人")
    assert verdict["pipeline"] == "intel_fusion"
    assert isinstance(verdict["score"], int) and verdict["score"] >= verdict["threshold"]
    assert "organization" not in verdict["reason"]  # 深圳 has no company suffix
    assert "dimension_keyword" in verdict["reason"]

    cheap = orchestrator.classify_trigger("张三")
    assert cheap["pipeline"] == "simple"
    assert cheap["score"] < cheap["threshold"]


@pytest.mark.asyncio
async def test_execute_intel_pipeline_structured_report_inline() -> None:
    """End-to-end: LLM providing all intel-pipeline methods produces a
    structured综合查询 report that is returned inline (no download link)."""

    class FakeProvider:
        def __init__(self, name: str, url: str, snippet: str, score: float = 1.0):
            self.name = name
            self._url = url
            self._snippet = snippet
            self._score = score

        def is_enabled(self) -> bool:
            return True

        async def search(self, plan: QianduSearchPlan) -> list[QianduSearchResult]:
            return [
                QianduSearchResult(
                    title=f"{plan.intent} hit",
                    url=self._url,
                    snippet=self._snippet,
                    score=self._score,
                    provider=self.name,
                )
            ]

    class FakeExtractor:
        name = "fake"

        def is_enabled(self) -> bool:
            return True

        async def extract(self, results: list[QianduSearchResult]) -> list[QianduExtractedDocument]:
            return [
                QianduExtractedDocument(
                    title=item.title,
                    url=item.url,
                    content=f"{item.snippet} 法人 股东 裁判文书 学历 任职 微博 公众号 新闻",
                    provider=self.name,
                )
                for item in results
            ]

    class FakeLLM:
        def should_trigger_intel_pipeline(self, text: str) -> bool:
            return True

        async def extract_entities(self, *, raw_input: str, allowed_models, requested_model):
            del allowed_models, requested_model
            return QianduSearchLLMOrchestrator.heuristic_entity_extraction(raw_input)

        async def generate_search_tasks(self, *, extraction, allowed_models, requested_model):
            del allowed_models, requested_model
            return QianduSearchLLMOrchestrator.heuristic_generate_tasks(extraction)

        async def fuse_intel_report(self, *, extraction, search_results, allowed_models, requested_model):
            del allowed_models, requested_model
            return (
                "# 综合查询结论\n"
                f"针对 {extraction.summary} 的多维度检索命中 {len(search_results)} 条证据。\n"
                "## 工商 / 企业信息\n- [1] 命中\n"
                "## 司法记录\n- [2] 命中\n"
            )

    providers = [
        FakeProvider("tavily", "https://qcc.com/firm/123", "某某集团 法人 股东"),
        FakeProvider("exa", "https://wenshu.court.gov.cn/c/abc", "张伟 裁判文书"),
    ]

    service = QianduSearchService(
        session=SimpleNamespace(),
        llm=FakeLLM(),
        providers=providers,
        extractors=[FakeExtractor()],
    )

    result = await service.execute(
        query_text="张伟 某某集团",
        allowed_models=[],
        requested_model=None,
    )

    assert result.metadata["pipeline"] == "intel_fusion"
    assert "综合查询结论" in result.content
    # Structured dimensions from the heuristic task generator must be present in metadata.
    task_types = {entry["task_type"] for entry in result.metadata["tasks"]}
    assert {"business", "judicial", "education", "profession", "social", "wechat", "news"}.issubset(task_types)
    # Evidence sources block should be inlined.
    assert "## 证据来源" in result.content
    # Short report → no download link in content.
    assert "下载链接" not in result.content


@pytest.mark.asyncio
async def test_must_include_hard_filter_only_fires_for_strong_identifiers() -> None:
    """If the extraction only has a bare personal name (no phone / id / handle),
    results with the right domain for the target dimension should survive even
    when the snippet does not literally contain that name."""

    class FakeProvider:
        name = "tavily"

        def is_enabled(self) -> bool:
            return True

        async def search(self, plan: QianduSearchPlan) -> list[QianduSearchResult]:
            return [
                QianduSearchResult(
                    title="某公司 企业信息",
                    url="https://qcc.com/firm/xyz",
                    snippet="法人 股东 注册资本 5000 万",
                    score=0.9,
                    provider=self.name,
                )
            ]

    class FakeExtractor:
        name = "fake"

        def is_enabled(self) -> bool:
            return True

        async def extract(self, results):
            return [
                QianduExtractedDocument(
                    title=item.title,
                    url=item.url,
                    content=item.snippet,
                    provider=self.name,
                )
                for item in results
            ]

    class FakeLLM:
        def should_trigger_intel_pipeline(self, text: str) -> bool:
            return True

        async def extract_entities(self, *, raw_input, allowed_models, requested_model):
            del raw_input, allowed_models, requested_model
            return QianduIntelExtraction(
                summary="姓名=张三",
                names=["张三"],  # common name — NOT a strong identifier
                phones=[],
                id_numbers=[],
                addresses=[],
                organizations=[],
                other_fields={},
                data_quality="medium",
                raw_input="张三",
            )

        async def generate_search_tasks(self, *, extraction, allowed_models, requested_model):
            del allowed_models, requested_model
            return [
                QianduSearchTask(
                    task_id="biz",
                    task_type="business",
                    query="张三 企查查",
                    goal="",
                    priority=1,
                    include_domains=[],
                    preferred_providers=["tavily"],
                )
            ]

        async def fuse_intel_report(self, *, extraction, search_results, allowed_models, requested_model):
            del extraction, allowed_models, requested_model
            return f"命中 {len(search_results)} 条"

    service = QianduSearchService(
        session=SimpleNamespace(),
        llm=FakeLLM(),
        providers=[FakeProvider()],
        extractors=[FakeExtractor()],
    )

    result = await service.execute(query_text="张三", allowed_models=[], requested_model=None)

    assert result.metadata["pipeline"] == "intel_fusion"
    # Result survives even though the snippet does not literally contain "张三"
    assert "qcc.com" in result.content
