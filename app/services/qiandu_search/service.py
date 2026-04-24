from __future__ import annotations

import asyncio
import re
from urllib.parse import urlsplit

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AppException
from app.services.qiandu_search.llm import QianduSearchLLMOrchestrator
from app.services.qiandu_search.models import (
    QianduEvidenceChunk,
    QianduExtractedDocument,
    QianduSearchCommandResult,
    QianduSearchPlan,
    QianduSearchResult,
    QianduSearchTask,
)
from app.services.telegram_download_service import TelegramDownloadService
from app.services.qiandu_search.providers import (
    HttpFallbackExtractor,
    QianduDocumentExtractor,
    QianduSearchProvider,
    build_qiandu_extractors,
    build_qiandu_search_providers,
)

QIANDU_SEARCH_COMMAND = "qiandu_search"


class QianduSearchService:
    internal_model = "oracle-qiandu-search"
    internal_provider = "internal-tool"
    internal_node_id = "qiandu-search-command"

    def __init__(
        self,
        session: AsyncSession,
        *,
        llm: QianduSearchLLMOrchestrator | None = None,
        providers: list[QianduSearchProvider] | None = None,
        extractors: list[QianduDocumentExtractor] | None = None,
    ) -> None:
        self.session = session
        self.llm = llm or QianduSearchLLMOrchestrator(session)
        self.providers = providers or build_qiandu_search_providers()
        self.extractors = extractors or build_qiandu_extractors()
        self.fallback_extractor = HttpFallbackExtractor()
        self.download_service = TelegramDownloadService()

    def match_command(self, content: str) -> dict[str, str] | None:
        stripped = content.strip()
        matched = re.match(r"^#千度\s+(.+)$", stripped, flags=re.DOTALL | re.IGNORECASE)
        if not matched:
            return None

        query_text = matched.group(1).strip()
        if not query_text:
            return None
        return {"command": QIANDU_SEARCH_COMMAND, "query_text": query_text}

    async def execute(
        self,
        *,
        query_text: str,
        allowed_models: list[str],
        requested_model: str | None,
    ) -> QianduSearchCommandResult:
        active_providers = [provider for provider in self.providers if provider.is_enabled()]
        if not active_providers:
            raise AppException(
                503,
                "QIANDU_NOT_CONFIGURED",
                "千度搜索尚未配置。请至少启用 Tavily、Exa、SearXNG、Snoop 或 WeChat-Crawler 之一。",
            )

        if self.llm.detect_structured_input(query_text):
            return await self._execute_intel_pipeline(
                query_text=query_text,
                active_providers=active_providers,
                allowed_models=allowed_models,
                requested_model=requested_model,
            )

        plan = await self.llm.build_plan(
            query_text=query_text,
            allowed_models=allowed_models,
            requested_model=requested_model,
        )
        plan = self._refine_plan(query_text, plan)

        search_results, used_providers = await self._search(active_providers, plan)
        if not search_results:
            raise AppException(404, "QIANDU_NO_RESULTS", "没有检索到相关结果。")

        documents = await self._extract(search_results)
        evidence_chunks = self._select_evidence(query_text, plan, search_results, documents)
        try:
            answer = await self.llm.synthesize_answer(
                query_text=query_text,
                plan=plan,
                evidence_chunks=evidence_chunks,
                allowed_models=allowed_models,
                requested_model=requested_model,
            )
        except Exception:
            answer = self._fallback_answer(query_text, evidence_chunks)

        content = self._compose_output(answer, evidence_chunks)
        return QianduSearchCommandResult(
            command=QIANDU_SEARCH_COMMAND,
            content=content,
            metadata={
                "query_text": query_text,
                "plan": {
                    "queries": plan.queries,
                    "intent": plan.intent,
                    "topic": plan.topic,
                    "time_range": plan.time_range,
                    "include_domains": plan.include_domains,
                    "exclude_domains": plan.exclude_domains,
                    "preferred_providers": plan.preferred_providers,
                },
                "providers": used_providers,
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

    async def _execute_intel_pipeline(
        self,
        *,
        query_text: str,
        active_providers: list[QianduSearchProvider],
        allowed_models: list[str],
        requested_model: str | None,
    ) -> QianduSearchCommandResult:
        extraction = await self.llm.extract_entities(
            raw_input=query_text,
            allowed_models=allowed_models,
            requested_model=requested_model,
        )
        tasks = await self.llm.generate_search_tasks(
            extraction=extraction,
            allowed_models=allowed_models,
            requested_model=requested_model,
        )

        all_evidence: list[QianduEvidenceChunk] = []
        used_providers: set[str] = set()

        async def _run_task(task: QianduSearchTask) -> None:
            plan = QianduSearchPlan(
                query=task.query,
                queries=[task.query],
                intent=task.task_type,
                include_domains=task.include_domains,
                preferred_providers=task.preferred_providers,
            )
            try:
                # Pass extraction names for strict filtering
                results, p_used = await self._search(active_providers, plan, must_include=extraction.names)
                used_providers.update(p_used)
                docs = await self._extract(results)
                chunks = self._select_evidence(task.query, plan, results, docs)
                all_evidence.extend(chunks)
            except Exception:
                pass

        if tasks:
            await asyncio.gather(*[_run_task(t) for t in tasks])

        # Deduplicate evidence
        unique_evidence: dict[str, QianduEvidenceChunk] = {}
        for item in all_evidence:
            if item.url not in unique_evidence:
                unique_evidence[item.url] = item
        final_evidence = list(unique_evidence.values())

        report_text = await self.llm.fuse_intel_report(
            extraction=extraction,
            search_results=final_evidence,
            allowed_models=allowed_models,
            requested_model=requested_model,
        )

        download = await self.download_service.create_download(text=report_text, file_name="qiandu_intel_report.md", mime_type="text/markdown")
        content = f"情报分析报告已生成：\n{download['url']}\n\n（由于内容较长，请点击链接查看或下载）"

        return QianduSearchCommandResult(
            command=QIANDU_SEARCH_COMMAND,
            content=content,
            metadata={
                "query_text": "结构化查询转储",
                "pipeline": "intel_fusion",
                "tasks": [{"query": t.query, "type": t.task_type} for t in tasks],
                "providers": list(used_providers),
                "download_url": download["url"],
            },
        )

    async def _search(
        self,
        providers: list[QianduSearchProvider],
        plan: QianduSearchPlan,
        must_include: list[str] | None = None,
    ) -> tuple[list[QianduSearchResult], list[str]]:
        ordered = self._sort_providers(providers, plan.preferred_providers)
        merged_results: list[QianduSearchResult] = []
        used_providers: list[str] = []
        errors: list[AppException] = []

        for provider in ordered:
            provider_results: list[QianduSearchResult] = []
            for query in plan.queries[: settings.qiandu_max_queries]:
                try:
                    provider_results.extend(await provider.search(plan.with_query(query)))
                except AppException as exc:
                    errors.append(exc)
                    provider_results = []
                    break
                except Exception as exc:
                    errors.append(
                        AppException(
                            502,
                            "QIANDU_PROVIDER_FAILED",
                            f"{provider.name} provider failed unexpectedly: {exc}",
                        )
                    )
                    provider_results = []
                    break
            if provider_results:
                merged_results.extend(provider_results)
                used_providers.append(provider.name)

        filtered = self._rank_and_filter_results(plan.query, plan.intent, merged_results, must_include=must_include)
        if filtered:
            return filtered[: settings.qiandu_max_results], used_providers
        if errors:
            raise errors[-1]
        return [], used_providers

    async def _extract(self, search_results: list[QianduSearchResult]) -> list[QianduExtractedDocument]:
        selected = search_results[: settings.qiandu_max_extract_urls]
        documents: list[QianduExtractedDocument] = []
        remaining = selected

        for extractor in self.extractors:
            if not extractor.is_enabled() or not remaining:
                continue
            try:
                extracted = await extractor.extract(remaining)
            except Exception:
                continue
            if extracted:
                documents.extend(extracted)
                covered_urls = {item.url for item in extracted}
                remaining = [item for item in remaining if item.url not in covered_urls]

        if remaining:
            documents.extend(await self.fallback_extractor.extract(remaining))

        return self._dedupe_documents(documents)

    def _select_evidence(
        self,
        query_text: str,
        plan: QianduSearchPlan,
        search_results: list[QianduSearchResult],
        documents: list[QianduExtractedDocument],
    ) -> list[QianduEvidenceChunk]:
        chunks: list[QianduEvidenceChunk] = []
        for document in documents:
            chunks.extend(self._chunk_document(query_text, plan.intent, document))
        if not chunks:
            chunks.extend(self._chunk_search_results(query_text, plan.intent, search_results))

        ranked = sorted(chunks, key=lambda item: item.rank_score, reverse=True)
        selected: list[QianduEvidenceChunk] = []
        seen_urls: set[str] = set()
        total_chars = 0

        for item in ranked:
            if item.url in seen_urls and len(selected) >= 3:
                continue
            projected = total_chars + len(item.text)
            if projected > settings.qiandu_max_context_chars and selected:
                continue
            selected.append(item)
            seen_urls.add(item.url)
            total_chars = projected
            if len(selected) >= settings.qiandu_max_evidence_chunks:
                break

        return selected or self._chunk_search_results(query_text, plan.intent, search_results)[:4]

    def _chunk_document(
        self,
        query_text: str,
        intent: str,
        document: QianduExtractedDocument,
    ) -> list[QianduEvidenceChunk]:
        paragraphs = [
            segment.strip()
            for segment in re.split(r"\n{2,}|(?<=[。！？!?])\s+", document.content)
            if segment.strip()
        ]
        if not paragraphs:
            paragraphs = [document.content.strip()]

        chunks: list[QianduEvidenceChunk] = []
        for segment in paragraphs[:50]:
            text = segment.replace("\r", " ").replace("\n", " ").strip()
            if len(text) < 60:
                continue
            if len(text) > 1000:
                text = f"{text[:997]}..."
            chunks.append(
                QianduEvidenceChunk(
                    title=document.title,
                    url=document.url,
                    text=text,
                    provider=document.provider,
                    rank_score=self._score_text(query_text, intent, text, document.title, base=1.2),
                    metadata={"kind": "document"},
                )
            )
        return chunks

    def _chunk_search_results(
        self,
        query_text: str,
        intent: str,
        search_results: list[QianduSearchResult],
    ) -> list[QianduEvidenceChunk]:
        chunks: list[QianduEvidenceChunk] = []
        for item in search_results:
            text = item.snippet.strip()
            if not text:
                continue
            chunks.append(
                QianduEvidenceChunk(
                    title=item.title,
                    url=item.url,
                    text=text[:800],
                    provider=item.provider,
                    rank_score=self._score_text(query_text, intent, text, item.title, base=max(item.score, 0.5)),
                    metadata={"kind": "search-result"},
                )
            )
        return chunks

    @staticmethod
    def _compose_output(answer: str, evidence_chunks: list[QianduEvidenceChunk]) -> str:
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
            lines.append(f"{index}. {item.title} ({urlsplit(item.url).netloc or item.provider})")
            lines.append(item.url)
            index += 1
            if index > 6:
                break
        return "\n".join(lines).strip()

    @staticmethod
    def _fallback_answer(query_text: str, evidence_chunks: list[QianduEvidenceChunk]) -> str:
        if not evidence_chunks:
            return f"已完成检索，但暂时没有足够证据来回答“{query_text}”。"

        lines = [f"已完成检索。以下是和“{query_text}”最相关的证据摘要：", ""]
        for index, item in enumerate(evidence_chunks[:3], start=1):
            preview = item.text.strip().replace("\n", " ")
            if len(preview) > 220:
                preview = f"{preview[:217]}..."
            lines.append(f"{index}. {item.title}: {preview}")
        return "\n".join(lines).strip()

    def _rank_and_filter_results(
        self,
        query_text: str,
        intent: str,
        results: list[QianduSearchResult],
        must_include: list[str] | None = None,
    ) -> list[QianduSearchResult]:
        seen: dict[str, QianduSearchResult] = {}
        for item in results:
            url = item.url or ""
            domain = self._domain_of(url)
            if self._is_blocked_domain(domain):
                continue

            reranked_score = self._score_result(query_text, intent, item, must_include=must_include)
            item.score = reranked_score
            
            # Massive penalty for non-matching names in person/legal search
            if reranked_score <= -50.0:
                continue

            current = seen.get(url)
            if not current or item.score > current.score:
                seen[url] = item

        ranked = sorted(seen.values(), key=lambda item: item.score, reverse=True)
        selected: list[QianduSearchResult] = []
        seen_domains: set[str] = set()
        for item in ranked:
            domain = self._domain_of(item.url)
            if domain and domain in seen_domains and len(selected) >= 4:
                continue
            selected.append(item)
            if domain:
                seen_domains.add(domain)
            if len(selected) >= settings.qiandu_max_results:
                break
        return selected

    def _score_result(self, query_text: str, intent: str, result: QianduSearchResult, must_include: list[str] | None = None) -> float:
        domain = self._domain_of(result.url)
        score = self._score_text(query_text, intent, result.snippet, result.title, base=max(result.score, 0.2))

        # Strict Name Matching for Mainland OSINT
        if must_include and (intent in ["person", "legal_entity"]):
            matches_any = any(name in result.title or name in result.snippet for name in must_include)
            if not matches_any:
                return -100.0  # Fatal penalty for irrelevant person results
            else:
                score += 5.0  # Bonus for confirmed target match

        if result.provider == "snoop":
            score += 4.0 if intent == "social_id" else 1.0
        if result.provider == "snoop_fallback":
            score += 2.5 if intent == "social_id" else 0.5
        if result.provider == "wechat_crawler":
            score += 4.0 if intent == "wechat" else 1.0
        if result.provider == "exa":
            score += 1.5
        if result.provider == "tavily":
            score += 1.0

        legal_domains = {
            "qcc.com", "court.gov.cn", "aiqicha.baidu.com", "tianyancha.com",
            "zgcpws.com", "zxgk.court.gov.cn", "wenshu.court.gov.cn", "judicourt.com"
        }
        if intent == "legal_entity" and any(ld in domain for ld in legal_domains):
            score += 10.0  # Final massive boost

        # HEAVY PENALTY for global social sites in mainland OSINT context
        global_false_positives = {"linkedin.com", "facebook.com", "twitter.com", "x.com", "instagram.com"}
        if (intent in ["legal_entity", "person"]) and any(gfp in domain for gfp in global_false_positives):
            score -= 8.0
        if intent == "wechat" and domain.endswith("mp.weixin.qq.com"):
            score += 4.0
        if intent == "social_id":
            if any(social_domain in domain for social_domain in {"weibo.com", "xiaohongshu.com", "douyin.com", "bilibili.com"}):
                score += 3.0
            if result.provider in {"snoop", "snoop_fallback"}:
                score += 3.0
        if self._is_trusted_domain(domain):
            score += 1.5
        if self._looks_like_low_value_wrapper(domain):
            score -= 3.0
        return score

    @staticmethod
    def _score_text(query_text: str, intent: str, text: str, title: str, *, base: float) -> float:
        query_tokens = QianduSearchService._tokenize(query_text)
        text_tokens = QianduSearchService._tokenize(text)
        title_tokens = QianduSearchService._tokenize(title)
        overlap = len(query_tokens.intersection(text_tokens))
        title_overlap = len(query_tokens.intersection(title_tokens))
        score = base + overlap * 1.4 + title_overlap * 1.8
        if intent == "social_id" and any(token in text_tokens for token in {"uid", "账号", "微博", "username"}):
            score += 1.5
        if intent == "wechat" and any(token in text_tokens for token in {"公众号", "微信", "公号"}):
            score += 1.5
        if intent == "legal_entity" and any(token in text_tokens for token in {"法人", "股东", "注册资本", "信用代码"}):
            score += 1.5
        return score

    def _refine_plan(self, query_text: str, plan: QianduSearchPlan) -> QianduSearchPlan:
        del query_text
        include_domains = [item for item in plan.include_domains if not self._is_blocked_domain(item)]
        exclude_domains = list(plan.exclude_domains)
        if plan.intent == "wechat" and "mp.weixin.qq.com" not in include_domains:
            include_domains.append("mp.weixin.qq.com")
        if plan.intent == "legal_entity":
            if "qcc.com" not in include_domains:
                include_domains.append("qcc.com")
            if "court.gov.cn" not in include_domains:
                include_domains.append("court.gov.cn")
        for domain in {"codecanyon.net", "mcpmarket.com", "mindstudio.ai"}:
            if domain not in exclude_domains:
                exclude_domains.append(domain)
        if not plan.preferred_providers:
            plan.preferred_providers = ["tavily", "exa", "searxng"]
        return QianduSearchPlan(
            query=plan.query,
            queries=plan.queries[: settings.qiandu_max_queries],
            intent=plan.intent,
            topic=plan.topic,
            time_range=plan.time_range,
            include_domains=include_domains[:20],
            exclude_domains=exclude_domains[:50],
            preferred_providers=plan.preferred_providers[:5],
        )

    @staticmethod
    def _sort_providers(
        providers: list[QianduSearchProvider],
        preferred_order: list[str],
    ) -> list[QianduSearchProvider]:
        if not preferred_order:
            return providers
        ranking = {name: index for index, name in enumerate(preferred_order)}
        return sorted(providers, key=lambda item: ranking.get(item.name, 999))

    @staticmethod
    def _dedupe_documents(documents: list[QianduExtractedDocument]) -> list[QianduExtractedDocument]:
        seen: dict[str, QianduExtractedDocument] = {}
        for item in documents:
            current = seen.get(item.url)
            if not current or len(item.content) > len(current.content):
                seen[item.url] = item
        return list(seen.values())

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        return {token.lower() for token in re.findall(r"[\u4e00-\u9fffA-Za-z0-9_]+", text) if token.strip()}

    @staticmethod
    def _domain_of(url: str) -> str:
        if url.startswith("local://"):
            return ""
        return urlsplit(url).netloc.lower().strip()

    @staticmethod
    def _is_trusted_domain(domain: str) -> bool:
        return domain.endswith((".gov.cn", ".gov", ".edu", ".org")) or domain in {
            "qcc.com",
            "aiqicha.baidu.com",
            "tianyancha.com",
            "wenshu.court.gov.cn",
            "zxgk.court.gov.cn",
            "mp.weixin.qq.com",
            "weibo.com",
            "developers.openai.com",
            "openai.com",
            "linkedin.com",
            "github.com",
        }

    @staticmethod
    def _looks_like_low_value_wrapper(domain: str) -> bool:
        return domain in {"codecanyon.net", "mcpmarket.com", "mindstudio.ai"}

    def _is_blocked_domain(self, domain: str) -> bool:
        blocked = {"codecanyon.net", "mcpmarket.com", "mindstudio.ai"}
        return domain in blocked or any(domain.endswith(f".{item}") for item in blocked)
