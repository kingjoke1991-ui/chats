from types import SimpleNamespace

import pytest

from app.core.exceptions import AppException
from app.services.web_search import WEB_SEARCH_COMMAND, WebSearchService
from app.services.web_search.models import EvidenceChunk, ExtractedDocument, SearchPlan, SearchResult


def test_match_command_extracts_query_text() -> None:
    service = WebSearchService.__new__(WebSearchService)

    matched = WebSearchService.match_command(service, "#搜索 OpenAI 最新模型")

    assert matched == {
        "command": WEB_SEARCH_COMMAND,
        "query_text": "OpenAI 最新模型",
    }


def test_match_command_supports_search_alias() -> None:
    service = WebSearchService.__new__(WebSearchService)

    matched = WebSearchService.match_command(service, "#search OpenAI latest model")

    assert matched == {
        "command": WEB_SEARCH_COMMAND,
        "query_text": "OpenAI latest model",
    }


@pytest.mark.asyncio
async def test_execute_returns_answer_with_sources() -> None:
    class FakeLLM:
        async def build_plan(self, *, query_text: str, allowed_models: list[str], requested_model: str | None):
            del allowed_models
            del requested_model
            return SearchPlan(query=query_text, queries=[query_text], topic="news", time_range="week")

        async def synthesize_answer(
            self,
            *,
            query_text: str,
            evidence_chunks: list[EvidenceChunk],
            allowed_models: list[str],
            requested_model: str | None,
        ) -> str:
            del allowed_models
            del requested_model
            assert query_text == "OpenAI 最新模型"
            assert evidence_chunks
            return "结论：[1] 和 [2] 的证据显示信息已经更新。"

    class FakeProvider:
        name = "fake"
        supports_extract = True

        def is_enabled(self) -> bool:
            return True

        async def search(self, plan: SearchPlan) -> list[SearchResult]:
            assert plan.query == "OpenAI 最新模型"
            return [
                SearchResult(
                    title="Source A",
                    url="https://example.com/a",
                    snippet="OpenAI 发布了更新模型。",
                    score=0.9,
                    provider=self.name,
                ),
                SearchResult(
                    title="Source B",
                    url="https://example.com/b",
                    snippet="模型能力和发布时间细节。",
                    score=0.8,
                    provider=self.name,
                ),
            ]

        async def extract(self, results: list[SearchResult]) -> list[ExtractedDocument]:
            return [
                ExtractedDocument(
                    title=item.title,
                    url=item.url,
                    content=f"{item.title} 的正文，包含 OpenAI 最新模型的时间、能力和上下文。",
                    provider=self.name,
                )
                for item in results
            ]

    service = WebSearchService(
        session=SimpleNamespace(),
        llm=FakeLLM(),
        providers=[FakeProvider()],
    )

    result = await service.execute(
        query_text="OpenAI 最新模型",
        allowed_models=[],
        requested_model=None,
    )

    assert "结论：" in result.content
    assert "来源：" in result.content
    assert "https://example.com/a" in result.content
    assert result.metadata["provider"] == "fake"
    assert result.metadata["plan"]["topic"] == "news"


def test_rank_and_filter_results_prefers_primary_domain_and_blocks_low_quality_sites() -> None:
    service = WebSearchService(
        session=SimpleNamespace(),
        llm=SimpleNamespace(),
        providers=[],
    )

    results = [
        SearchResult(
            title="OpenAI Changelog",
            url="https://developers.openai.com/api/docs/changelog",
            snippet="Official changelog for new OpenAI models.",
            score=0.4,
            provider="fake",
        ),
        SearchResult(
            title="Third-party wrapper",
            url="https://mcpmarket.com/tools/openai-wrapper",
            snippet="A wrapper that mentions OpenAI.",
            score=0.9,
            provider="fake",
        ),
        SearchResult(
            title="Marketplace template",
            url="https://codecanyon.net/item/openai-app",
            snippet="OpenAI SaaS template.",
            score=0.95,
            provider="fake",
        ),
    ]

    ranked = service._rank_and_filter_results("OpenAI 最新模型", results)

    assert len(ranked) == 1
    assert ranked[0].url == "https://developers.openai.com/api/docs/changelog"


@pytest.mark.asyncio
async def test_execute_raises_when_no_provider_is_enabled() -> None:
    class DisabledProvider:
        name = "disabled"
        supports_extract = False

        def is_enabled(self) -> bool:
            return False

        async def search(self, plan: SearchPlan) -> list[SearchResult]:
            del plan
            return []

        async def extract(self, results: list[SearchResult]) -> list[ExtractedDocument]:
            del results
            return []

    service = WebSearchService(
        session=SimpleNamespace(),
        llm=SimpleNamespace(),
        providers=[DisabledProvider()],
    )

    with pytest.raises(AppException) as exc_info:
        await service.execute(query_text="测试", allowed_models=[], requested_model=None)

    assert exc_info.value.error_code == "WEB_SEARCH_NOT_CONFIGURED"
