from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from urllib.parse import urlsplit

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AppException
from app.services.qiandu_search.dimensions import (
    DOMAIN_ALLOWLIST as QIANDU_DOMAIN_ALLOWLIST,
    INTEL_DIMENSIONS as _INTEL_DIMENSIONS,
    INTENT_TO_DIMENSION as _TASK_TYPE_ALIASES,
    canonical_dimension,
)
from app.services.qiandu_search.llm import QianduSearchLLMOrchestrator
from app.services.qiandu_search.models import (
    QianduEvidenceChunk,
    QianduExtractedDocument,
    QianduIntelExtraction,
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

logger = logging.getLogger(__name__)


# Low-quality page markers — if a fetched document is dominated by these
# strings, it almost certainly wraps a login wall or captcha and should not be
# used as evidence.
_LOW_VALUE_MARKERS: tuple[str, ...] = (
    "登录后查看",
    "请先登录",
    "请登录",
    "扫码登录",
    "未登录",
    "滑动验证",
    "人机验证",
    "verify you are human",
    "captcha",
    "access denied",
    "403 forbidden",
    "404 not found",
)


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

    # Accepts `#千 ...`, `#千度 ...`, and `#千问 ...` — historically the
    # README and some chat clients have used different spellings for the
    # same综合查询 command, so we normalise them all to one handler.
    _COMMAND_PATTERN = re.compile(
        r"^#千(?:度|问)?[\s\u3000](.+)$",
        flags=re.DOTALL | re.IGNORECASE,
    )

    def match_command(self, content: str) -> dict[str, str] | None:
        stripped = content.strip()
        matched = self._COMMAND_PATTERN.match(stripped)
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

        router = self._classify_pipeline(query_text)
        degradations: list[str] = []

        if router["pipeline"] == "intel_fusion":
            budget = max(30, int(getattr(settings, "qiandu_total_budget_seconds", 240)))
            try:
                result = await asyncio.wait_for(
                    self._execute_intel_pipeline(
                        query_text=query_text,
                        active_providers=active_providers,
                        allowed_models=allowed_models,
                        requested_model=requested_model,
                        degradations=degradations,
                    ),
                    timeout=budget,
                )
                self._attach_router_metadata(result, router, degradations)
                return result
            except AppException:
                raise
            except TimeoutError:
                logger.warning(
                    "qiandu intel pipeline exceeded %ss budget; falling back to simple plan",
                    budget,
                )
                degradations.append(f"intel_timeout:{budget}s")
            except Exception as exc:
                logger.exception("qiandu intel pipeline crashed, falling back to simple plan: %s", exc)
                degradations.append(f"intel_crash:{type(exc).__name__}")

        result = await self._execute_simple_pipeline(
            query_text=query_text,
            active_providers=active_providers,
            allowed_models=allowed_models,
            requested_model=requested_model,
            degradations=degradations,
        )
        self._attach_router_metadata(result, router, degradations)
        return result

    @staticmethod
    def _attach_router_metadata(
        result: QianduSearchCommandResult,
        router: dict[str, object],
        degradations: list[str],
    ) -> None:
        result.metadata["pipeline_router"] = dict(router)
        if degradations:
            existing = result.metadata.get("degradations")
            if isinstance(existing, list):
                existing.extend(degradations)
            else:
                result.metadata["degradations"] = list(degradations)

    # ------------------------------------------------------------------
    # Pipeline selection
    # ------------------------------------------------------------------

    def _should_use_intel_pipeline(self, query_text: str) -> bool:
        return self._classify_pipeline(query_text)["pipeline"] == "intel_fusion"

    def _classify_pipeline(self, query_text: str) -> dict[str, object]:
        """Return routing metadata `{pipeline, score, threshold, reason}`.

        The routing decision is made by the LLM orchestrator (which holds
        the signal-scoring logic) where possible, but we gracefully fall
        back to a legacy detector or a hard "simple" default so tests and
        custom orchestrators without the new API still work.
        """

        if not hasattr(self.llm, "extract_entities") or not hasattr(self.llm, "generate_search_tasks"):
            return {"pipeline": "simple", "score": 0, "threshold": 0, "reason": "intel_api_missing"}

        classifier = getattr(self.llm, "classify_trigger", None)
        if callable(classifier):
            try:
                verdict = classifier(query_text)
            except Exception:
                logger.exception("qiandu classify_trigger crashed; defaulting to simple pipeline")
                return {"pipeline": "simple", "score": 0, "threshold": 0, "reason": "classifier_error"}
            if isinstance(verdict, dict) and verdict.get("pipeline") in {"simple", "intel_fusion"}:
                return verdict

        detector = getattr(self.llm, "should_trigger_intel_pipeline", None)
        if callable(detector):
            try:
                fired = bool(detector(query_text))
            except Exception:
                logger.exception("qiandu should_trigger_intel_pipeline crashed; defaulting to simple")
                fired = False
            return {
                "pipeline": "intel_fusion" if fired else "simple",
                "score": 1 if fired else 0,
                "threshold": 1,
                "reason": "legacy_detector",
            }

        legacy = getattr(self.llm, "detect_structured_input", None)
        if callable(legacy):
            try:
                fired = bool(legacy(query_text))
            except Exception:
                fired = False
            return {
                "pipeline": "intel_fusion" if fired else "simple",
                "score": 1 if fired else 0,
                "threshold": 1,
                "reason": "detect_structured_input",
            }
        return {"pipeline": "simple", "score": 0, "threshold": 0, "reason": "no_detector"}

    # ------------------------------------------------------------------
    # Simple (single-intent) pipeline — retained for backwards compatibility.
    # ------------------------------------------------------------------

    async def _execute_simple_pipeline(
        self,
        *,
        query_text: str,
        active_providers: list[QianduSearchProvider],
        allowed_models: list[str],
        requested_model: str | None,
        degradations: list[str] | None = None,
    ) -> QianduSearchCommandResult:
        degradations = degradations if degradations is not None else []
        plan = await self.llm.build_plan(
            query_text=query_text,
            allowed_models=allowed_models,
            requested_model=requested_model,
        )
        plan = self._refine_plan(query_text, plan)

        search_results, used_providers = await self._search(
            active_providers, plan, degradations=degradations
        )
        if not search_results:
            raise AppException(404, "QIANDU_NO_RESULTS", "没有检索到相关结果。")

        documents = await self._extract(search_results, degradations=degradations)
        evidence_chunks = self._select_evidence(query_text, plan, search_results, documents)
        try:
            answer = await self.llm.synthesize_answer(
                query_text=query_text,
                plan=plan,
                evidence_chunks=evidence_chunks,
                allowed_models=allowed_models,
                requested_model=requested_model,
            )
        except Exception as exc:
            logger.warning("qiandu synthesize_answer failed; using fallback summary: %s", exc)
            degradations.append(f"synthesize_fallback:{type(exc).__name__}")
            answer = self._fallback_answer(query_text, evidence_chunks)

        content = await self._finalize_simple_content(answer, evidence_chunks, degradations)
        return QianduSearchCommandResult(
            command=QIANDU_SEARCH_COMMAND,
            content=content,
            metadata={
                "query_text": query_text,
                "pipeline": "simple",
                "degradations": list(degradations),
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

    # ------------------------------------------------------------------
    # Intel (multi-dimension 综合查询) pipeline
    # ------------------------------------------------------------------

    async def _execute_intel_pipeline(
        self,
        *,
        query_text: str,
        active_providers: list[QianduSearchProvider],
        allowed_models: list[str],
        requested_model: str | None,
        degradations: list[str] | None = None,
    ) -> QianduSearchCommandResult:
        degradations = degradations if degradations is not None else []
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

        if not tasks:
            # Nothing structured to work with — degrade to simple pipeline so the
            # user at least sees some result for the raw query.
            degradations.append("no_tasks_generated")
            return await self._execute_simple_pipeline(
                query_text=query_text,
                active_providers=active_providers,
                allowed_models=allowed_models,
                requested_model=requested_model,
                degradations=degradations,
            )

        tasks = self._normalize_task_types(tasks)

        # Strong identifiers — keep hard `must_include` filtering only for
        # identifiers that uniquely pick out a person (phone / id / email /
        # social handle). Pure 姓名 is too ambiguous and previously wiped out
        # all results for common Chinese names.
        must_include_terms = self._strong_identifiers(extraction)

        all_evidence: list[QianduEvidenceChunk] = []
        used_providers: set[str] = set()
        task_errors: list[str] = []
        task_stats: list[dict[str, object]] = []

        task_concurrency = max(1, int(getattr(settings, "qiandu_intel_task_concurrency", 3)))
        task_semaphore = asyncio.Semaphore(task_concurrency)

        async def _run_task(task: QianduSearchTask) -> None:
            async with task_semaphore:
                plan = self._plan_from_task(task, extraction)
                try:
                    results, provider_names = await self._search(
                        active_providers,
                        plan,
                        must_include=must_include_terms or None,
                        degradations=degradations,
                    )
                    used_providers.update(provider_names)
                    documents = await self._extract(results, degradations=degradations)
                    chunks = self._select_evidence(task.query, plan, results, documents)
                    # tag each chunk with its task dimension so the fuse step can
                    # structure the output correctly.
                    for chunk in chunks:
                        chunk.metadata.setdefault("task_id", task.task_id)
                        chunk.metadata.setdefault("task_type", task.task_type)
                    all_evidence.extend(chunks)
                    task_stats.append(
                        {
                            "task_id": task.task_id,
                            "task_type": task.task_type,
                            "query": task.query,
                            "results": len(results),
                            "chunks": len(chunks),
                        }
                    )
                except AppException as exc:
                    task_errors.append(f"{task.task_id}:{exc.error_code}:{exc.message}")
                    degradations.append(f"task_app_error:{task.task_id}:{exc.error_code}")
                except Exception as exc:
                    logger.exception("qiandu intel task %s failed: %s", task.task_id, exc)
                    task_errors.append(f"{task.task_id}:UNEXPECTED:{exc}")
                    degradations.append(f"task_crashed:{task.task_id}:{type(exc).__name__}")

        await asyncio.gather(*[_run_task(task) for task in tasks])

        evidence = self._dedupe_evidence_cross_task(all_evidence)

        if not evidence:
            summary_lines = [
                f"已按 {len(tasks)} 个维度执行综合查询，但暂未拿到可信证据。",
                "建议补充更精准的关键词（如组织全称、手机号、身份证前 6 位）或换用其他 provider。",
            ]
            if task_errors:
                summary_lines.append("内部错误样例：" + "; ".join(task_errors[:3]))
            content = "\n".join(summary_lines)
            return QianduSearchCommandResult(
                command=QIANDU_SEARCH_COMMAND,
                content=content,
                metadata={
                    "query_text": query_text,
                    "pipeline": "intel_fusion",
                    "tasks": [self._task_to_dict(task) for task in tasks],
                    "task_stats": task_stats,
                    "errors": task_errors,
                    "providers": sorted(used_providers),
                    "extraction": self._extraction_to_dict(extraction),
                },
            )

        try:
            report_text = await self.llm.fuse_intel_report(
                extraction=extraction,
                search_results=evidence,
                allowed_models=allowed_models,
                requested_model=requested_model,
            )
        except Exception as exc:
            logger.warning("qiandu fuse_intel_report failed; using heuristic report: %s", exc)
            degradations.append(f"fuse_fallback:{type(exc).__name__}")
            report_text = ""

        content = await self._finalize_intel_content(report_text, evidence, query_text)

        return QianduSearchCommandResult(
            command=QIANDU_SEARCH_COMMAND,
            content=content,
            metadata={
                "query_text": query_text,
                "pipeline": "intel_fusion",
                "tasks": [self._task_to_dict(task) for task in tasks],
                "task_stats": task_stats,
                "errors": task_errors,
                "providers": sorted(used_providers),
                "extraction": self._extraction_to_dict(extraction),
                "degradations": list(degradations),
                "evidence": [
                    {
                        "title": chunk.title,
                        "url": chunk.url,
                        "provider": chunk.provider,
                        "score": chunk.rank_score,
                        "task_type": chunk.metadata.get("task_type"),
                        "text_preview": chunk.text[:400],
                    }
                    for chunk in evidence
                ],
            },
        )

    async def _finalize_intel_content(
        self,
        report_text: str,
        evidence: list[QianduEvidenceChunk],
        query_text: str,
    ) -> str:
        del query_text  # kept for future correlation IDs; unused here.
        report = (report_text or "").strip()
        if not report:
            report = "综合查询未能生成结构化报告，请结合下方来源线索自行研判。"

        sources_block = self._render_sources_block(evidence)
        combined = f"{report}\n\n{sources_block}".strip()

        inline_limit = getattr(settings, "qiandu_report_inline_max_chars", 6000)
        if len(combined) <= inline_limit:
            return combined

        # Long report — generate a download link and inline a short preview so
        # the chat remains immediately useful.
        try:
            download = await self.download_service.create_download(
                text=combined,
                file_name="qiandu_intel_report.md",
                mime_type="text/markdown",
            )
        except Exception:
            logger.exception("qiandu download service unavailable; falling back to truncated inline report")
            return combined[:inline_limit].rstrip() + "\n\n（报告过长且下载服务不可用，已截断。）"

        preview_limit = max(1200, min(inline_limit // 2, 3000))
        preview = report[:preview_limit].rstrip()
        return (
            f"{preview}\n\n"
            f"（完整综合查询报告较长，已生成下载链接：{download['url']}）\n\n"
            f"{sources_block}"
        ).strip()

    def _render_sources_block(self, evidence: list[QianduEvidenceChunk]) -> str:
        if not evidence:
            return ""
        lines = ["## 证据来源"]
        seen: set[str] = set()
        for index, chunk in enumerate(evidence, start=1):
            if chunk.url in seen:
                continue
            seen.add(chunk.url)
            domain = urlsplit(chunk.url).netloc or chunk.provider
            task_type = chunk.metadata.get("task_type") or chunk.metadata.get("kind") or ""
            lines.append(
                f"[{index}] {chunk.title} ({domain})"
                + (f" · {task_type}" if task_type else "")
            )
            lines.append(chunk.url)
            if len(seen) >= 20:
                break
        return "\n".join(lines).strip()

    def _plan_from_task(
        self,
        task: QianduSearchTask,
        extraction: QianduIntelExtraction,
    ) -> QianduSearchPlan:
        # Default allowlist for the dimension, augmented with task-specific hints.
        include = list(dict.fromkeys((task.include_domains or []) + QIANDU_DOMAIN_ALLOWLIST.get(task.task_type, [])))
        queries = [task.query]
        # Add a strong-identifier variant where useful.
        phone = extraction.phones[0] if extraction.phones else ""
        if phone and task.task_type in {"business", "judicial", "social"}:
            queries.append(f"{task.query} {phone}")
        organizations = extraction.organizations[:1]
        if organizations and task.task_type in {"profession", "education"}:
            queries.append(f"{task.query} {organizations[0]}")

        preferred = task.preferred_providers or ["tavily", "exa", "searxng"]

        plan = QianduSearchPlan(
            query=task.query,
            queries=queries[: settings.qiandu_max_queries],
            intent=task.task_type,
            topic="news" if task.task_type == "news" else "general",
            include_domains=include,
            preferred_providers=preferred,
        )
        return self._refine_plan(task.query, plan)

    def _normalize_task_types(self, tasks: list[QianduSearchTask]) -> list[QianduSearchTask]:
        for task in tasks:
            task.task_type = canonical_dimension(task.task_type)
        return tasks

    @staticmethod
    def _strong_identifiers(extraction: QianduIntelExtraction) -> list[str]:
        identifiers: list[str] = []
        identifiers.extend(extraction.phones)
        identifiers.extend(extraction.id_numbers)
        if isinstance(extraction.other_fields, dict):
            for key in ("邮箱", "email", "社交账号", "handles"):
                value = extraction.other_fields.get(key)
                if isinstance(value, list):
                    identifiers.extend(str(item).strip() for item in value if item)
        return [item for item in dict.fromkeys(identifiers) if item]

    @staticmethod
    def _task_to_dict(task: QianduSearchTask) -> dict[str, object]:
        return {
            "task_id": task.task_id,
            "task_type": task.task_type,
            "query": task.query,
            "goal": task.goal,
            "priority": task.priority,
            "include_domains": list(task.include_domains),
            "preferred_providers": list(task.preferred_providers),
        }

    @staticmethod
    def _extraction_to_dict(extraction: QianduIntelExtraction) -> dict[str, object]:
        return {
            "summary": extraction.summary,
            "names": list(extraction.names),
            "phones": list(extraction.phones),
            "id_numbers": list(extraction.id_numbers),
            "organizations": list(extraction.organizations),
            "addresses": list(extraction.addresses),
            "other_fields": dict(extraction.other_fields) if isinstance(extraction.other_fields, dict) else {},
            "data_quality": extraction.data_quality,
        }

    @staticmethod
    def _dedupe_evidence_cross_task(
        evidence: list[QianduEvidenceChunk],
    ) -> list[QianduEvidenceChunk]:
        """Collapse duplicate chunks produced by multiple tasks hitting the
        same URL or near-identical text, while preserving domain diversity.
        """

        by_url: dict[str, QianduEvidenceChunk] = {}
        for chunk in evidence:
            existing = by_url.get(chunk.url)
            if existing is None or chunk.rank_score > existing.rank_score:
                by_url[chunk.url] = chunk

        seen_hashes: set[str] = set()
        result: list[QianduEvidenceChunk] = []
        for chunk in sorted(by_url.values(), key=lambda item: item.rank_score, reverse=True):
            digest = hashlib.sha1(chunk.text.strip().encode("utf-8", "ignore")).hexdigest()
            if digest in seen_hashes:
                continue
            seen_hashes.add(digest)
            result.append(chunk)
            if len(result) >= settings.qiandu_max_evidence_chunks * 3:
                break
        return result

    # ------------------------------------------------------------------
    # Search / extract / rank primitives shared by both pipelines
    # ------------------------------------------------------------------

    async def _search(
        self,
        providers: list[QianduSearchProvider],
        plan: QianduSearchPlan,
        must_include: list[str] | None = None,
        degradations: list[str] | None = None,
    ) -> tuple[list[QianduSearchResult], list[str]]:
        degradations = degradations if degradations is not None else []
        ordered = self._sort_providers(providers, plan.preferred_providers)
        merged_results: list[QianduSearchResult] = []
        used_providers: list[str] = []
        errors: list[AppException] = []

        for provider in ordered:
            provider_results: list[QianduSearchResult] = []
            semaphore = self._semaphore_for_provider(provider.name)
            for query in plan.queries[: settings.qiandu_max_queries]:
                try:
                    async with semaphore:
                        hits = await provider.search(plan.with_query(query))
                    provider_results.extend(hits)
                except AppException as exc:
                    errors.append(exc)
                    degradations.append(f"provider_app_error:{provider.name}:{exc.error_code}")
                    provider_results = []
                    break
                except Exception as exc:
                    logger.warning(
                        "qiandu provider %s failed on query=%r: %s",
                        provider.name,
                        query,
                        exc,
                    )
                    errors.append(
                        AppException(
                            502,
                            "QIANDU_PROVIDER_FAILED",
                            f"{provider.name} provider failed unexpectedly: {exc}",
                        )
                    )
                    degradations.append(
                        f"provider_crashed:{provider.name}:{type(exc).__name__}"
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

    async def _extract(
        self,
        search_results: list[QianduSearchResult],
        degradations: list[str] | None = None,
    ) -> list[QianduExtractedDocument]:
        degradations = degradations if degradations is not None else []
        selected = search_results[: settings.qiandu_max_extract_urls]
        documents: list[QianduExtractedDocument] = []
        remaining = selected

        for extractor in self.extractors:
            if not extractor.is_enabled() or not remaining:
                continue
            try:
                extracted = await extractor.extract(remaining)
            except Exception as exc:
                logger.warning(
                    "qiandu extractor %s failed: %s",
                    getattr(extractor, "name", type(extractor).__name__),
                    exc,
                )
                degradations.append(
                    f"extractor_crashed:{getattr(extractor, 'name', 'unknown')}:{type(exc).__name__}"
                )
                continue
            if extracted:
                documents.extend(extracted)
                covered_urls = {item.url for item in extracted}
                remaining = [item for item in remaining if item.url not in covered_urls]

        if remaining:
            try:
                documents.extend(await self.fallback_extractor.extract(remaining))
            except Exception as exc:
                logger.warning("qiandu fallback extractor failed: %s", exc)
                degradations.append(f"fallback_extractor_crashed:{type(exc).__name__}")

        return self._dedupe_documents(documents)

    # Per-provider semaphores are shared across all tasks of a single
    # ``QianduSearchService`` instance so the intel pipeline cannot stampede
    # upstream APIs when many tasks run concurrently.
    @classmethod
    def _semaphore_for_provider(cls, provider_name: str) -> asyncio.Semaphore:
        registry = cls._provider_semaphores()
        if provider_name not in registry:
            registry[provider_name] = asyncio.Semaphore(cls._default_provider_limit(provider_name))
        return registry[provider_name]

    @classmethod
    def _provider_semaphores(cls) -> dict[str, asyncio.Semaphore]:
        if not hasattr(cls, "_provider_sem_registry"):
            cls._provider_sem_registry = {}  # type: ignore[attr-defined]
        return cls._provider_sem_registry  # type: ignore[attr-defined]

    @staticmethod
    def _default_provider_limit(provider_name: str) -> int:
        local_tool_names = {"snoop", "wechat_crawler"}
        if provider_name in local_tool_names:
            return max(1, int(getattr(settings, "qiandu_local_tool_concurrency", 1)))
        return max(1, int(getattr(settings, "qiandu_provider_concurrency", 2)))

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

        if selected:
            return selected
        return self._chunk_search_results(query_text, plan.intent, search_results)[:4]

    def _chunk_document(
        self,
        query_text: str,
        intent: str,
        document: QianduExtractedDocument,
    ) -> list[QianduEvidenceChunk]:
        if self._looks_like_login_wall(document.content):
            return []
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
            if self._looks_like_login_wall(text):
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
            if self._looks_like_login_wall(text):
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
    def _looks_like_login_wall(text: str) -> bool:
        if not text:
            return False
        lowered = text.lower()
        marker_hits = sum(1 for marker in _LOW_VALUE_MARKERS if marker in lowered or marker in text)
        if marker_hits >= 2:
            return True
        return marker_hits >= 1 and len(text) < 200

    async def _finalize_simple_content(
        self,
        answer: str,
        evidence_chunks: list[QianduEvidenceChunk],
        degradations: list[str],
    ) -> str:
        """Apply the same inline-vs-download overflow handling the intel
        pipeline uses, so a long LLM answer with many sources no longer
        blows past the chat UI's reasonable message length."""

        combined = self._compose_output(answer, evidence_chunks)
        inline_limit = max(1000, int(getattr(settings, "qiandu_report_inline_max_chars", 6000)))
        if len(combined) <= inline_limit:
            return combined

        try:
            download = await self.download_service.create_download(
                text=combined,
                file_name="qiandu_simple_report.md",
                mime_type="text/markdown",
            )
        except Exception as exc:
            logger.warning("qiandu download service unavailable for simple report: %s", exc)
            degradations.append(f"download_unavailable:{type(exc).__name__}")
            return combined[:inline_limit].rstrip() + "\n\n（结果过长且下载服务不可用，已截断。）"

        preview_limit = max(800, min(inline_limit // 2, 2400))
        preview = (answer or "").strip()[:preview_limit].rstrip()
        sources_block = "\n".join(
            line for line in combined.splitlines() if line.startswith("来源：") or line
        )
        return (
            f"{preview}\n\n"
            f"（结果较长，已生成完整下载链接：{download['url']}）\n\n"
            f"{sources_block[:inline_limit // 2]}"
        ).strip()

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

    def _score_result(
        self,
        query_text: str,
        intent: str,
        result: QianduSearchResult,
        must_include: list[str] | None = None,
    ) -> float:
        domain = self._domain_of(result.url)
        score = self._score_text(query_text, intent, result.snippet, result.title, base=max(result.score, 0.2))

        # Strong identifier weighting — only applied when caller passed
        # concrete identifiers such as a phone number, id number, email or
        # ``@handle``. Bare personal names are deliberately NOT treated as
        # strong identifiers because they are far too noisy on Chinese web
        # pages.
        #
        # This used to be a hard filter returning ``-100`` and dropping the
        # result, but provider snippets are often truncated so a genuine
        # match on the underlying page was being silently filtered out. We
        # now apply a soft weight: a big bonus on match, a moderate penalty
        # on miss. Together with the trusted-domain and provider bonuses
        # below this lets high-quality sources (.gov / 企查查 / 微信公众号)
        # survive a miss while crowding out obvious spam.
        if must_include:
            haystack = f"{result.title}\n{result.snippet}\n{result.url}"
            matched = any(term and term in haystack for term in must_include)
            if matched:
                score += 6.0
            else:
                score -= 4.0

        score += self._domain_bonus_for_intent(domain, intent)

        if result.provider == "snoop":
            score += 4.0 if intent in {"social_id", "social"} else 1.0
        if result.provider == "snoop_fallback":
            score += 2.5 if intent in {"social_id", "social"} else 0.5
        if result.provider == "wechat_crawler":
            score += 4.0 if intent == "wechat" else 1.0
        if result.provider == "exa":
            score += 1.5
        if result.provider == "tavily":
            score += 1.0

        if self._is_trusted_domain(domain):
            score += 1.5
        if self._looks_like_low_value_wrapper(domain):
            score -= 3.0
        return score

    @staticmethod
    def _domain_bonus_for_intent(domain: str, intent: str) -> float:
        if not domain:
            return 0.0

        def matches(allowlist: list[str]) -> bool:
            return any(entry in domain for entry in allowlist)

        bonus = 0.0
        # Primary-intent alignment — strongest boost.
        intent_to_buckets: dict[str, list[str]] = {
            "business": ["business"],
            "legal_entity": ["business"],
            "company": ["business"],
            "judicial": ["judicial"],
            "education": ["education"],
            "profession": ["profession"],
            "social": ["social"],
            "social_id": ["social"],
            "wechat": ["wechat"],
            "news": ["news"],
            "person": ["social", "business", "judicial"],
            "general": [],
        }
        primary = intent_to_buckets.get(intent, [])
        for bucket in primary:
            if matches(QIANDU_DOMAIN_ALLOWLIST.get(bucket, [])):
                bonus += 10.0
                break

        # Secondary cross-dimension familiarity — small boost so a 工商 result
        # surfaced during a 司法 query is still preferred over random spam.
        for bucket in ("business", "judicial", "education", "profession", "social", "wechat", "news"):
            if bucket in primary:
                continue
            if matches(QIANDU_DOMAIN_ALLOWLIST[bucket]):
                bonus += 1.5
                break

        # Overseas social footprints previously had a blanket penalty. Now we
        # only penalise them when we are explicitly targeting mainland data
        # sources and the result is not a profession lookup.
        global_sites = ("linkedin.com", "facebook.com", "twitter.com", "x.com", "instagram.com")
        if any(site in domain for site in global_sites):
            if intent == "profession":
                bonus += 2.0
            elif intent in {"business", "judicial", "education", "social", "wechat", "news", "legal_entity", "company"}:
                bonus -= 3.0

        return bonus

    @staticmethod
    def _score_text(query_text: str, intent: str, text: str, title: str, *, base: float) -> float:
        query_tokens = QianduSearchService._tokenize(query_text)
        text_tokens = QianduSearchService._tokenize(text)
        title_tokens = QianduSearchService._tokenize(title)
        overlap = len(query_tokens.intersection(text_tokens))
        title_overlap = len(query_tokens.intersection(title_tokens))
        score = base + overlap * 1.4 + title_overlap * 1.8

        if intent in {"social_id", "social"} and any(
            token in text_tokens for token in {"uid", "账号", "微博", "username", "小红书", "抖音"}
        ):
            score += 1.5
        if intent == "wechat" and any(token in text_tokens for token in {"公众号", "微信", "公号"}):
            score += 1.5
        if intent in {"legal_entity", "business", "company"} and any(
            token in text_tokens for token in {"法人", "股东", "注册资本", "信用代码"}
        ):
            score += 1.5
        if intent == "judicial" and any(
            token in text_tokens for token in {"裁判", "文书", "判决", "执行", "失信", "案号"}
        ):
            score += 1.5
        if intent == "education" and any(
            token in text_tokens for token in {"学历", "学籍", "毕业", "院校", "学位"}
        ):
            score += 1.5
        if intent == "profession" and any(
            token in text_tokens for token in {"任职", "履历", "职位", "简历", "招聘"}
        ):
            score += 1.5
        return score

    def _refine_plan(self, query_text: str, plan: QianduSearchPlan) -> QianduSearchPlan:
        del query_text
        include_domains = [item for item in plan.include_domains if not self._is_blocked_domain(item)]
        exclude_domains = list(plan.exclude_domains)

        bucket_map = {
            "wechat": "wechat",
            "business": "business",
            "legal_entity": "business",
            "company": "business",
            "judicial": "judicial",
            "education": "education",
            "profession": "profession",
            "social": "social",
            "social_id": "social",
            "news": "news",
        }
        bucket = bucket_map.get(plan.intent)
        if bucket:
            for domain in QIANDU_DOMAIN_ALLOWLIST.get(bucket, []):
                if domain not in include_domains:
                    include_domains.append(domain)

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
        if not domain:
            return False
        if domain.endswith((".gov.cn", ".gov", ".edu", ".org", ".edu.cn")):
            return True
        trusted = {
            "qcc.com",
            "aiqicha.baidu.com",
            "tianyancha.com",
            "wenshu.court.gov.cn",
            "zxgk.court.gov.cn",
            "mp.weixin.qq.com",
            "weibo.com",
            "xiaohongshu.com",
            "douyin.com",
            "zhihu.com",
            "bilibili.com",
            "chsi.com.cn",
            "linkedin.com",
            "maimai.cn",
            "zhipin.com",
            "liepin.com",
            "github.com",
        }
        return domain in trusted

    @staticmethod
    def _looks_like_low_value_wrapper(domain: str) -> bool:
        return domain in {"codecanyon.net", "mcpmarket.com", "mindstudio.ai"}

    def _is_blocked_domain(self, domain: str) -> bool:
        blocked = {"codecanyon.net", "mcpmarket.com", "mindstudio.ai"}
        return domain in blocked or any(domain.endswith(f".{item}") for item in blocked)
