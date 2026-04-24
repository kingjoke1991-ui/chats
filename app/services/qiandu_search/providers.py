from __future__ import annotations

import asyncio
import html
import json
import re
import shlex
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import quote, urlsplit, urlunsplit

import httpx

from app.core.config import settings
from app.core.exceptions import AppException
from app.services.qiandu_search.models import QianduExtractedDocument, QianduSearchPlan, QianduSearchResult


class QianduSearchProvider(Protocol):
    name: str

    def is_enabled(self) -> bool: ...

    async def search(self, plan: QianduSearchPlan) -> list[QianduSearchResult]: ...


class QianduDocumentExtractor(Protocol):
    name: str

    def is_enabled(self) -> bool: ...

    async def extract(self, results: list[QianduSearchResult]) -> list[QianduExtractedDocument]: ...


@dataclass(slots=True)
class TavilyQianduProvider:
    name: str = "tavily"

    def is_enabled(self) -> bool:
        return bool(settings.qiandu_tavily_api_key or settings.web_search_tavily_api_key)

    async def search(self, plan: QianduSearchPlan) -> list[QianduSearchResult]:
        payload: dict[str, Any] = {
            "query": plan.query,
            "search_depth": "advanced",
            "topic": plan.topic,
            "max_results": settings.qiandu_max_results,
            "include_domains": plan.include_domains,
            "exclude_domains": plan.exclude_domains,
        }
        if plan.time_range:
            payload["time_range"] = plan.time_range

        data = await self._request(
            "POST",
            "/search",
            json=payload,
            timeout_seconds=settings.qiandu_timeout_seconds,
        )
        raw_results = data.get("results")
        if not isinstance(raw_results, list):
            return []

        parsed: list[QianduSearchResult] = []
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            url = _normalize_url(str(item.get("url") or ""))
            if not url:
                continue
            parsed.append(
                QianduSearchResult(
                    title=str(item.get("title") or url).strip(),
                    url=url,
                    snippet=str(item.get("content") or "").strip(),
                    score=_safe_float(item.get("score")),
                    provider=self.name,
                    metadata={"raw": item},
                )
            )
        return parsed

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any],
        timeout_seconds: int,
    ) -> dict[str, Any]:
        api_key = settings.qiandu_tavily_api_key or settings.web_search_tavily_api_key
        base_url = settings.qiandu_tavily_base_url.rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                response = await client.request(
                    method,
                    f"{base_url}{path}",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json=json,
                )
        except httpx.HTTPError as exc:
            raise AppException(502, "QIANDU_UPSTREAM_UNAVAILABLE", f"Tavily request failed: {exc}") from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise AppException(502, "QIANDU_INVALID_RESPONSE", "Tavily returned invalid JSON") from exc

        if response.status_code >= 400:
            detail = ""
            if isinstance(data, dict):
                detail = str(data.get("detail") or data.get("message") or "").strip()
            raise AppException(502, "QIANDU_UPSTREAM_ERROR", detail or f"Tavily returned status {response.status_code}")
        if not isinstance(data, dict):
            raise AppException(502, "QIANDU_INVALID_RESPONSE", "Tavily returned unexpected payload")
        return data


@dataclass(slots=True)
class ExaQianduProvider:
    name: str = "exa"

    def is_enabled(self) -> bool:
        return bool(settings.resolved_qiandu_exa_api_key)

    async def search(self, plan: QianduSearchPlan) -> list[QianduSearchResult]:
        payload: dict[str, Any] = {
            "query": plan.query,
            "type": "auto",
            "numResults": settings.qiandu_max_results,
            "contents": {
                "highlights": {
                    "maxCharacters": 1200,
                }
            },
        }
        if plan.intent == "social_id":
            payload["category"] = "people"
        elif plan.intent == "legal_entity":
            payload["category"] = "company"
        elif plan.topic == "news":
            payload["category"] = "news"

        if plan.include_domains and payload.get("category") != "people":
            payload["includeDomains"] = plan.include_domains
        if plan.exclude_domains and payload.get("category") not in {"people", "company"}:
            payload["excludeDomains"] = plan.exclude_domains

        try:
            async with httpx.AsyncClient(timeout=settings.qiandu_timeout_seconds) as client:
                response = await client.post(
                    f"{settings.qiandu_exa_base_url.rstrip('/')}/search",
                    headers={
                        "x-api-key": str(settings.resolved_qiandu_exa_api_key),
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
        except httpx.HTTPError as exc:
            raise AppException(502, "QIANDU_UPSTREAM_UNAVAILABLE", f"Exa request failed: {exc}") from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise AppException(502, "QIANDU_INVALID_RESPONSE", "Exa returned invalid JSON") from exc

        if response.status_code >= 400:
            detail = ""
            if isinstance(data, dict):
                detail = str(data.get("message") or data.get("detail") or "").strip()
            raise AppException(502, "QIANDU_UPSTREAM_ERROR", detail or f"Exa returned status {response.status_code}")

        raw_results = data.get("results") if isinstance(data, dict) else None
        if not isinstance(raw_results, list):
            return []

        parsed: list[QianduSearchResult] = []
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            url = _normalize_url(str(item.get("url") or item.get("id") or ""))
            if not url:
                continue
            highlights = item.get("highlights")
            snippet = ""
            if isinstance(highlights, list):
                snippet = " ".join(str(value).strip() for value in highlights if isinstance(value, str) and value.strip())
            if not snippet:
                snippet = _coalesce_text(item.get("text"), item.get("summary"))
            parsed.append(
                QianduSearchResult(
                    title=str(item.get("title") or url).strip(),
                    url=url,
                    snippet=snippet[:1200],
                    score=_safe_float(item.get("score") or item.get("searchScore") or 0.5),
                    provider=self.name,
                    metadata={"raw": item},
                )
            )
        return parsed


@dataclass(slots=True)
class SearXNGQianduProvider:
    name: str = "searxng"

    def is_enabled(self) -> bool:
        return bool(settings.qiandu_searxng_base_url or settings.web_search_searxng_base_url)

    async def search(self, plan: QianduSearchPlan) -> list[QianduSearchResult]:
        base_url = (settings.qiandu_searxng_base_url or settings.web_search_searxng_base_url or "").rstrip("/")
        params: dict[str, Any] = {
            "q": plan.query,
            "format": "json",
            "language": settings.qiandu_searxng_language,
        }
        if settings.qiandu_searxng_engines:
            params["engines"] = ",".join(settings.qiandu_searxng_engines)
        if plan.time_range:
            params["time_range"] = plan.time_range

        try:
            async with httpx.AsyncClient(timeout=settings.qiandu_timeout_seconds) as client:
                response = await client.get(f"{base_url}/search", params=params)
        except httpx.HTTPError as exc:
            raise AppException(502, "QIANDU_UPSTREAM_UNAVAILABLE", f"SearXNG request failed: {exc}") from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise AppException(502, "QIANDU_INVALID_RESPONSE", "SearXNG returned invalid JSON") from exc

        if response.status_code >= 400:
            raise AppException(502, "QIANDU_UPSTREAM_ERROR", f"SearXNG returned status {response.status_code}")

        raw_results = data.get("results") if isinstance(data, dict) else None
        if not isinstance(raw_results, list):
            return []

        parsed: list[QianduSearchResult] = []
        for item in raw_results[: settings.qiandu_max_results]:
            if not isinstance(item, dict):
                continue
            url = _normalize_url(str(item.get("url") or ""))
            if not url:
                continue
            parsed.append(
                QianduSearchResult(
                    title=str(item.get("title") or url).strip(),
                    url=url,
                    snippet=_coalesce_text(item.get("content"), item.get("snippet")),
                    score=_safe_float(item.get("score")),
                    provider=self.name,
                    metadata={"engine": item.get("engine"), "raw": item},
                )
            )
        return parsed


@dataclass(slots=True)
class LocalCommandSearchProvider:
    name: str
    command_template: str | None

    def is_enabled(self) -> bool:
        return bool(self.command_template)

    async def search(self, plan: QianduSearchPlan) -> list[QianduSearchResult]:
        if not self.command_template:
            return []

        rendered = self._render_command(plan.query)
        process = await asyncio.create_subprocess_shell(
            rendered,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(),
                timeout=settings.qiandu_timeout_seconds,
            )
        except TimeoutError:
            process.kill()
            await process.communicate()
            raise AppException(504, "QIANDU_LOCAL_TOOL_TIMEOUT", f"{self.name} command timed out")
        stdout = stdout_bytes.decode("utf-8", errors="ignore").strip()
        stderr = stderr_bytes.decode("utf-8", errors="ignore").strip()

        if process.returncode != 0:
            raise AppException(
                502,
                "QIANDU_LOCAL_TOOL_FAILED",
                f"{self.name} command failed: {stderr or f'exit code {process.returncode}'}",
            )

        return self._parse_output(plan.query, stdout, stderr)

    def _render_command(self, query: str) -> str:
        escaped_query = shlex.quote(query)
        template = self.command_template or ""
        if "{query}" in template:
            return template.format(query=escaped_query)
        return f"{template} {escaped_query}".strip()

    def _parse_output(self, query: str, stdout: str, stderr: str) -> list[QianduSearchResult]:
        del stderr
        if not stdout:
            return []
        try:
            parsed = json.loads(stdout)
        except ValueError:
            parsed = None

        results: list[QianduSearchResult] = []
        if isinstance(parsed, dict) and isinstance(parsed.get("results"), list):
            parsed = parsed["results"]
        if isinstance(parsed, list):
            for index, item in enumerate(parsed, start=1):
                if not isinstance(item, dict):
                    continue
                title = str(item.get("title") or item.get("name") or item.get("username") or f"{self.name} result {index}").strip()
                url = str(item.get("url") or item.get("profile") or f"local://{self.name}/{quote(query)}#{index}").strip()
                snippet = _coalesce_text(item.get("snippet"), item.get("content"), item.get("description"))
                results.append(
                    QianduSearchResult(
                        title=title,
                        url=url,
                        snippet=snippet[:1600],
                        score=_safe_float(item.get("score") or 1.0),
                        provider=self.name,
                        metadata={"raw_content": stdout, "raw": item},
                    )
                )
        if results:
            return results
        return [
            QianduSearchResult(
                title=f"{self.name} result",
                url=f"local://{self.name}/{quote(query)}",
                snippet=stdout[:1600],
                score=1.0,
                provider=self.name,
                metadata={"raw_content": stdout},
            )
        ]


@dataclass(slots=True)
class Crawl4AIMarkdownExtractor:
    name: str = "crawl4ai"

    def is_enabled(self) -> bool:
        if not settings.qiandu_crawl4ai_enabled:
            return False
        try:
            import crawl4ai  # noqa: F401
        except ImportError:
            return False
        return True

    async def extract(self, results: list[QianduSearchResult]) -> list[QianduExtractedDocument]:
        try:
            from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig
        except ImportError:
            return []

        browser_config = BrowserConfig(
            headless=settings.qiandu_crawl4ai_headless,
            text_mode=True,
            verbose=False,
            use_managed_browser=bool(settings.qiandu_crawl4ai_profile_dir),
            user_data_dir=settings.qiandu_crawl4ai_profile_dir,
            cookies=self._parse_json_value(settings.qiandu_crawl4ai_cookies_json, expected_type=list),
            headers=self._parse_json_value(settings.qiandu_crawl4ai_headers_json, expected_type=dict),
            enable_stealth=True,
        )
        run_config = CrawlerRunConfig()
        documents: list[QianduExtractedDocument] = []

        try:
            async with AsyncWebCrawler(config=browser_config) as crawler:
                for item in results:
                    if item.url.startswith("local://"):
                        continue
                    try:
                        result = await asyncio.wait_for(
                            crawler.arun(url=item.url, config=run_config),
                            timeout=settings.qiandu_extract_timeout_seconds,
                        )
                    except Exception:
                        continue

                    content = self._extract_markdown(result)
                    if not content:
                        continue
                    documents.append(
                        QianduExtractedDocument(
                            title=item.title,
                            url=item.url,
                            content=content[: settings.qiandu_max_document_chars],
                            provider=self.name,
                            metadata={"source_provider": item.provider},
                        )
                    )
        except Exception:
            return []
        return documents

    @staticmethod
    def _parse_json_value(raw: str | None, *, expected_type):
        if not raw:
            return None
        try:
            value = json.loads(raw)
        except ValueError:
            return None
        return value if isinstance(value, expected_type) else None

    @staticmethod
    def _extract_markdown(result: Any) -> str:
        for attr in ("markdown", "fit_markdown", "cleaned_html", "html"):
            value = getattr(result, attr, None)
            if isinstance(value, str) and value.strip():
                return value.strip()
            raw_markdown = getattr(value, "raw_markdown", None)
            if isinstance(raw_markdown, str) and raw_markdown.strip():
                return raw_markdown.strip()
        return ""


@dataclass(slots=True)
class HttpFallbackExtractor:
    name: str = "http-fetch"

    def is_enabled(self) -> bool:
        return True

    async def extract(self, results: list[QianduSearchResult]) -> list[QianduExtractedDocument]:
        documents: list[QianduExtractedDocument] = []
        for item in results:
            if item.url.startswith("local://"):
                raw_content = str(item.metadata.get("raw_content") or item.snippet or "").strip()
                if raw_content:
                    documents.append(
                        QianduExtractedDocument(
                            title=item.title,
                            url=item.url,
                            content=raw_content[: settings.qiandu_max_document_chars],
                            provider=self.name,
                            metadata={"source_provider": item.provider, "kind": "local-tool"},
                        )
                    )
                continue

            content = await self._fetch_text(item.url)
            if not content:
                continue
            documents.append(
                QianduExtractedDocument(
                    title=item.title,
                    url=item.url,
                    content=content,
                    provider=self.name,
                    metadata={"source_provider": item.provider},
                )
            )
        return documents

    async def _fetch_text(self, url: str) -> str:
        try:
            async with httpx.AsyncClient(
                timeout=settings.qiandu_extract_timeout_seconds,
                follow_redirects=True,
                headers={"User-Agent": settings.web_search_user_agent},
            ) as client:
                response = await client.get(url)
        except httpx.HTTPError:
            return ""

        if response.status_code >= 400:
            return ""

        content_type = response.headers.get("content-type", "")
        text = response.text
        if "html" not in content_type.lower():
            return text[: settings.qiandu_max_document_chars].strip()

        cleaned = re.sub(r"(?is)<script.*?>.*?</script>", " ", text)
        cleaned = re.sub(r"(?is)<style.*?>.*?</style>", " ", cleaned)
        cleaned = re.sub(r"(?is)<noscript.*?>.*?</noscript>", " ", cleaned)
        cleaned = re.sub(r"(?s)<[^>]+>", " ", cleaned)
        cleaned = html.unescape(cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned[: settings.qiandu_max_document_chars]


def build_qiandu_search_providers() -> list[QianduSearchProvider]:
    default_snoop_command = "python -m app.services.qiandu_search.local_tools snoop --query {query}"
    default_wechat_command = "python -m app.services.qiandu_search.local_tools wechat --query {query}"
    provider_map: dict[str, QianduSearchProvider] = {
        "tavily": TavilyQianduProvider(),
        "exa": ExaQianduProvider(),
        "searxng": SearXNGQianduProvider(),
        "snoop": LocalCommandSearchProvider(
            name="snoop",
            command_template=settings.qiandu_snoop_command or default_snoop_command,
        ),
        "wechat_crawler": LocalCommandSearchProvider(
            name="wechat_crawler",
            command_template=settings.qiandu_wechat_crawler_command or default_wechat_command,
        ),
    }
    providers: list[QianduSearchProvider] = []
    for name in settings.qiandu_provider_preference:
        provider = provider_map.get(name.lower().strip())
        if provider:
            providers.append(provider)
    return providers


def build_qiandu_extractors() -> list[QianduDocumentExtractor]:
    return [
        Crawl4AIMarkdownExtractor(),
        HttpFallbackExtractor(),
    ]


def _normalize_url(url: str) -> str:
    if not url:
        return ""
    if url.startswith("local://"):
        return url
    parts = urlsplit(url.strip())
    if not parts.scheme or not parts.netloc:
        return ""
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))


def _coalesce_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
