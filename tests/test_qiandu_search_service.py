from types import SimpleNamespace

import pytest

from app.core.exceptions import AppException
from app.services.qiandu_search import QIANDU_SEARCH_COMMAND, QianduSearchService
from app.services.qiandu_search.models import (
    QianduEvidenceChunk,
    QianduExtractedDocument,
    QianduSearchPlan,
    QianduSearchResult,
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
