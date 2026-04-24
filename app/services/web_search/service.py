from __future__ import annotations

import re
from urllib.parse import urlsplit

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AppException
from app.services.web_search.llm import WebSearchLLMOrchestrator
from app.services.web_search.models import EvidenceChunk, ExtractedDocument, SearchPlan, SearchResult, WebSearchCommandResult
from app.services.web_search.providers import HttpDocumentExtractor, WebSearchProvider, build_web_search_providers

WEB_SEARCH_COMMAND = "web_search"


class WebSearchService:
    internal_model = "oracle-web-search"
    internal_provider = "internal-tool"
    internal_node_id = "web-search-command"

    def __init__(
        self,
        session: AsyncSession,
        *,
        llm: WebSearchLLMOrchestrator | None = None,
        providers: list[WebSearchProvider] | None = None,
        fallback_extractor: HttpDocumentExtractor | None = None,
    ) -> None:
        self.session = session
        self.llm = llm or WebSearchLLMOrchestrator(session)
        self.providers = providers or build_web_search_providers()
        self.fallback_extractor = fallback_extractor or HttpDocumentExtractor()

    def match_command(self, content: str) -> dict[str, str] | None:
        stripped = content.strip()
        matched = re.match(r"^#(?:搜索|search|web)\s+(.+)$", stripped, flags=re.DOTALL | re.IGNORECASE)
        if not matched:
            return None

        query_text = matched.group(1).strip()
        if not query_text:
            return None

        return {"command": WEB_SEARCH_COMMAND, "query_text": query_text}

    async def execute(
        self,
        *,
        query_text: str,
        allowed_models: list[str],
        requested_model: str | None,
    ) -> WebSearchCommandResult:
        active_providers = [provider for provider in self.providers if provider.is_enabled()]
        if not active_providers:
            raise AppException(
                503,
                "WEB_SEARCH_NOT_CONFIGURED",
                "网页搜索尚未配置。请至少启用 Tavily 或 SearXNG。",
            )

        plan = await self.llm.build_plan(
            query_text=query_text,
            allowed_models=allowed_models,
            requested_model=requested_model,
        )
        plan = self._refine_plan(query_text, plan)

        search_results, provider_name = await self._search(active_providers, plan)
        if not search_results:
            raise AppException(404, "WEB_SEARCH_NO_RESULTS", "没有检索到相关网页结果。")

        documents = await self._extract(active_providers, provider_name, search_results)
        evidence_chunks = self._select_evidence(query_text, search_results, documents)
        answer = await self.llm.synthesize_answer(
            query_text=query_text,
            evidence_chunks=evidence_chunks,
            allowed_models=allowed_models,
            requested_model=requested_model,
        )

        return WebSearchCommandResult(
            command=WEB_SEARCH_COMMAND,
            content=self._compose_output(answer, evidence_chunks),
            metadata={
                "query_text": query_text,
                "plan": {
                    "queries": plan.queries,
                    "topic": plan.topic,
                    "time_range": plan.time_range,
                    "include_domains": plan.include_domains,
                    "exclude_domains": plan.exclude_domains,
                    "search_depth": plan.search_depth,
                },
                "provider": provider_name,
                "search_results": [
                    {
                        "title": item.title,
                        "url": item.url,
                        "snippet": item.snippet,
                        "score": item.score,
                        "provider": item.provider,
                    }
                    for item in search_results
                ],
                "evidence": [
                    {
                        "title": item.title,
                        "url": item.url,
                        "provider": item.provider,
                        "score": item.rank_score,
                        "text_preview": item.text[:400],
                    }
                    for item in evidence_chunks
                ],
            },
        )

    async def _search(
        self,
        providers: list[WebSearchProvider],
        plan: SearchPlan,
    ) -> tuple[list[SearchResult], str]:
        last_error: AppException | None = None
        for provider in providers:
            merged_results: list[SearchResult] = []
            for query in plan.queries[: settings.web_search_max_queries]:
                try:
                    results = await provider.search(plan.with_query(query))
                except AppException as exc:
                    last_error = exc
                    merged_results = []
                    break
                merged_results.extend(results)

            filtered = self._rank_and_filter_results(plan.query, merged_results)
            if filtered:
                return filtered[: settings.web_search_max_results], provider.name

        if last_error:
            raise last_error
        return [], ""

    async def _extract(
        self,
        providers: list[WebSearchProvider],
        provider_name: str,
        search_results: list[SearchResult],
    ) -> list[ExtractedDocument]:
        selected_results = search_results[: settings.web_search_max_extract_urls]
        documents: list[ExtractedDocument] = []

        provider = next((item for item in providers if item.name == provider_name), None)
        if provider and provider.supports_extract:
            try:
                documents = await provider.extract(selected_results)
            except AppException:
                documents = []

        covered_urls = {item.url for item in documents}
        missing_results = [item for item in selected_results if item.url not in covered_urls]
        if missing_results:
            documents.extend(await self.fallback_extractor.extract(missing_results))

        return self._dedupe_documents(documents)

    def _select_evidence(
        self,
        query_text: str,
        search_results: list[SearchResult],
        documents: list[ExtractedDocument],
    ) -> list[EvidenceChunk]:
        chunks: list[EvidenceChunk] = []
        for document in documents:
            chunks.extend(self._chunk_document(query_text, document))
        if not chunks:
            chunks.extend(self._chunk_search_results(query_text, search_results))

        ranked = sorted(chunks, key=lambda item: item.rank_score, reverse=True)
        selected: list[EvidenceChunk] = []
        seen_urls: set[str] = set()
        seen_domains: set[str] = set()
        total_chars = 0

        for item in ranked:
            if item.rank_score < settings.web_search_min_evidence_score:
                continue
            domain = self._domain_of(item.url)
            if item.url in seen_urls and len(selected) >= 3:
                continue
            if domain in seen_domains and len(selected) >= 2:
                continue

            projected = total_chars + len(item.text)
            if projected > settings.web_search_max_context_chars and selected:
                continue

            selected.append(item)
            seen_urls.add(item.url)
            seen_domains.add(domain)
            total_chars = projected
            if len(selected) >= settings.web_search_max_evidence_chunks:
                break

        return selected or self._chunk_search_results(query_text, search_results)[:3]

    def _chunk_document(self, query_text: str, document: ExtractedDocument) -> list[EvidenceChunk]:
        paragraphs = [
            segment.strip()
            for segment in re.split(r"\n{2,}|(?<=[。！？.!?])\s+", document.content)
            if segment.strip()
        ]
        if not paragraphs:
            paragraphs = [document.content.strip()]

        chunks: list[EvidenceChunk] = []
        for segment in paragraphs[:40]:
            text = segment.replace("\r", " ").replace("\n", " ").strip()
            if len(text) < 80:
                continue
            if len(text) > 900:
                text = f"{text[:897]}..."
            chunks.append(
                EvidenceChunk(
                    title=document.title,
                    url=document.url,
                    text=text,
                    provider=document.provider,
                    rank_score=self._score_text(query_text, text, document.title, base=1.2),
                    metadata={"kind": "document"},
                )
            )
        return chunks

    def _chunk_search_results(self, query_text: str, search_results: list[SearchResult]) -> list[EvidenceChunk]:
        chunks: list[EvidenceChunk] = []
        for item in search_results:
            text = item.snippet.strip()
            if not text:
                continue
            chunks.append(
                EvidenceChunk(
                    title=item.title,
                    url=item.url,
                    text=text[:600],
                    provider=item.provider,
                    rank_score=self._score_text(query_text, text, item.title, base=max(item.score, 0.5)),
                    metadata={"kind": "search-result"},
                )
            )
        return chunks

    @staticmethod
    def _compose_output(answer: str, evidence_chunks: list[EvidenceChunk]) -> str:
        answer = answer.strip() or "没有拿到足够证据，暂时无法可靠回答。"
        if not evidence_chunks:
            return answer

        lines = [answer, "", "来源："]
        seen_urls: set[str] = set()
        index = 1
        for item in evidence_chunks:
            if item.url in seen_urls:
                continue
            seen_urls.add(item.url)
            domain = urlsplit(item.url).netloc
            lines.append(f"{index}. {item.title} ({domain})")
            lines.append(item.url)
            index += 1
            if index > 5:
                break
        return "\n".join(lines).strip()

    def _rank_and_filter_results(self, query_text: str, results: list[SearchResult]) -> list[SearchResult]:
        seen: dict[str, SearchResult] = {}
        for item in results:
            domain = self._domain_of(item.url)
            if self._is_blocked_domain(domain):
                continue

            reranked_score = self._score_result(query_text, item)
            if reranked_score < settings.web_search_min_result_score:
                continue

            item.score = reranked_score
            current = seen.get(item.url)
            if not current or item.score > current.score:
                seen[item.url] = item

        ranked = sorted(seen.values(), key=lambda item: item.score, reverse=True)
        selected: list[SearchResult] = []
        seen_domains: set[str] = set()
        for item in ranked:
            domain = self._domain_of(item.url)
            if domain in seen_domains and len(selected) >= 3:
                continue
            selected.append(item)
            seen_domains.add(domain)
            if len(selected) >= settings.web_search_max_results:
                break
        return selected

    @staticmethod
    def _dedupe_documents(documents: list[ExtractedDocument]) -> list[ExtractedDocument]:
        seen: dict[str, ExtractedDocument] = {}
        for item in documents:
            current = seen.get(item.url)
            if not current or len(item.content) > len(current.content):
                seen[item.url] = item
        return list(seen.values())

    @staticmethod
    def _score_text(query_text: str, text: str, title: str, *, base: float) -> float:
        query_tokens = WebSearchService._tokenize(query_text)
        text_tokens = WebSearchService._tokenize(text)
        title_tokens = WebSearchService._tokenize(title)
        if not query_tokens:
            return base
        overlap = len(query_tokens.intersection(text_tokens))
        title_overlap = len(query_tokens.intersection(title_tokens))
        return base + overlap * 1.5 + title_overlap * 2.0

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        return {token.lower() for token in re.findall(r"[\u4e00-\u9fffA-Za-z0-9_]+", text) if token.strip()}

    def _score_result(self, query_text: str, result: SearchResult) -> float:
        domain = self._domain_of(result.url)
        score = self._score_text(query_text, result.snippet, result.title, base=max(result.score, 0.2))

        if self._is_primary_domain_for_query(query_text, domain):
            score += 5.0
        elif self._is_trusted_domain(domain):
            score += 2.0

        if self._looks_like_secondary_wrapper(domain):
            score -= 3.0
        return score

    def _refine_plan(self, query_text: str, plan: SearchPlan) -> SearchPlan:
        include_domains = [item for item in plan.include_domains if not self._is_blocked_domain(item)]
        exclude_domains = list(plan.exclude_domains)
        for domain in settings.web_search_blocked_domains:
            if domain not in exclude_domains:
                exclude_domains.append(domain)

        inferred_domains = self._infer_primary_domains(query_text)
        for domain in inferred_domains:
            if domain not in include_domains:
                include_domains.append(domain)

        return SearchPlan(
            query=plan.query,
            queries=plan.queries[: settings.web_search_max_queries],
            topic=plan.topic,
            time_range=plan.time_range,
            include_domains=include_domains[:20],
            exclude_domains=exclude_domains[:50],
            search_depth=plan.search_depth,
        )

    @staticmethod
    def _domain_of(url: str) -> str:
        return urlsplit(url).netloc.lower().strip()

    @staticmethod
    def _is_trusted_domain(domain: str) -> bool:
        trusted_suffixes = (".gov", ".edu", ".org")
        trusted_exact = {
            "openai.com",
            "developers.openai.com",
            "platform.openai.com",
            "github.com",
            "docs.github.com",
            "python.org",
            "pypi.org",
            "arxiv.org",
            "wikipedia.org",
        }
        return domain in trusted_exact or domain.endswith(trusted_suffixes)

    def _is_blocked_domain(self, domain: str) -> bool:
        for blocked in settings.web_search_blocked_domains:
            if domain == blocked or domain.endswith(f".{blocked}"):
                return True
        return False

    def _is_primary_domain_for_query(self, query_text: str, domain: str) -> bool:
        primary_domains = self._infer_primary_domains(query_text)
        return any(domain == item or domain.endswith(f".{item}") for item in primary_domains)

    @staticmethod
    def _looks_like_secondary_wrapper(domain: str) -> bool:
        return domain in {"codecanyon.net", "mcpmarket.com", "mindstudio.ai"}

    @staticmethod
    def _infer_primary_domains(query_text: str) -> list[str]:
        lowered = query_text.lower()
        domain_map = {
            "openai": ["openai.com", "developers.openai.com", "platform.openai.com"],
            "github": ["github.com", "docs.github.com"],
            "python": ["python.org", "pypi.org"],
        }
        domains: list[str] = []
        for keyword, mapped_domains in domain_map.items():
            if keyword in lowered:
                domains.extend(mapped_domains)
        return domains
