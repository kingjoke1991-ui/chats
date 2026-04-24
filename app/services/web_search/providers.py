from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.core.config import settings
from app.core.exceptions import AppException
from app.services.web_search.models import ExtractedDocument, SearchPlan, SearchResult


class WebSearchProvider(Protocol):
    name: str

    def is_enabled(self) -> bool: ...

    async def search(self, plan: SearchPlan) -> list[SearchResult]: ...

    async def extract(self, results: list[SearchResult]) -> list[ExtractedDocument]: ...

    @property
    def supports_extract(self) -> bool: ...


@dataclass(slots=True)
class TavilyProvider:
    name: str = "tavily"

    def is_enabled(self) -> bool:
        return bool(settings.web_search_tavily_api_key)

    @property
    def supports_extract(self) -> bool:
        return self.is_enabled()

    async def search(self, plan: SearchPlan) -> list[SearchResult]:
        payload: dict[str, Any] = {
            "query": plan.query,
            "search_depth": plan.search_depth,
            "topic": plan.topic,
            "max_results": settings.web_search_max_results,
            "include_domains": plan.include_domains,
            "exclude_domains": plan.exclude_domains,
            "include_usage": True,
        }
        if plan.time_range:
            payload["time_range"] = plan.time_range

        data = await self._request(
            "POST",
            "/search",
            json=payload,
            timeout_seconds=settings.web_search_timeout_seconds,
        )
        raw_results = data.get("results")
        if not isinstance(raw_results, list):
            return []

        parsed: list[SearchResult] = []
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            url = _normalize_url(str(item.get("url") or ""))
            if not url:
                continue
            parsed.append(
                SearchResult(
                    title=str(item.get("title") or url).strip(),
                    url=url,
                    snippet=str(item.get("content") or "").strip(),
                    score=_safe_float(item.get("score")),
                    provider=self.name,
                    metadata={
                        "favicon": item.get("favicon"),
                        "images": item.get("images"),
                    },
                )
            )
        return parsed

    async def extract(self, results: list[SearchResult]) -> list[ExtractedDocument]:
        urls = [item.url for item in results if item.url]
        if not urls:
            return []

        payload: dict[str, Any] = {
            "urls": urls,
            "format": "markdown",
            "extract_depth": settings.web_search_tavily_extract_depth,
            "timeout": settings.web_search_extract_timeout_seconds,
            "include_usage": True,
        }
        data = await self._request(
            "POST",
            "/extract",
            json=payload,
            timeout_seconds=settings.web_search_extract_timeout_seconds,
        )
        raw_results = data.get("results")
        if not isinstance(raw_results, list):
            return []

        parsed: list[ExtractedDocument] = []
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            url = _normalize_url(str(item.get("url") or ""))
            content = _coalesce_text(
                item.get("raw_content"),
                item.get("content"),
                item.get("markdown"),
                item.get("text"),
            )
            if not url or not content:
                continue
            parsed.append(
                ExtractedDocument(
                    title=str(item.get("title") or url).strip(),
                    url=url,
                    content=content,
                    provider=self.name,
                    metadata={"favicon": item.get("favicon")},
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
        try:
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                response = await client.request(
                    method,
                    f"{settings.web_search_tavily_base_url.rstrip('/')}{path}",
                    headers={
                        "Authorization": f"Bearer {settings.web_search_tavily_api_key}",
                        "Content-Type": "application/json",
                    },
                    json=json,
                )
        except httpx.HTTPError as exc:
            raise AppException(502, "WEB_SEARCH_UPSTREAM_UNAVAILABLE", f"Tavily request failed: {exc}") from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise AppException(502, "WEB_SEARCH_INVALID_RESPONSE", "Tavily returned invalid JSON") from exc

        if response.status_code >= 400:
            detail = ""
            if isinstance(data, dict):
                detail = str(data.get("detail") or data.get("message") or "").strip()
            raise AppException(
                502,
                "WEB_SEARCH_UPSTREAM_ERROR",
                detail or f"Tavily returned status {response.status_code}",
            )
        if not isinstance(data, dict):
            raise AppException(502, "WEB_SEARCH_INVALID_RESPONSE", "Tavily returned unexpected payload")
        return data


@dataclass(slots=True)
class SearXNGProvider:
    name: str = "searxng"

    def is_enabled(self) -> bool:
        return bool(settings.web_search_searxng_base_url)

    @property
    def supports_extract(self) -> bool:
        return False

    async def search(self, plan: SearchPlan) -> list[SearchResult]:
        params: dict[str, Any] = {
            "q": plan.query,
            "format": "json",
            "language": settings.web_search_searxng_language,
        }
        if plan.time_range:
            params["time_range"] = plan.time_range

        try:
            async with httpx.AsyncClient(timeout=settings.web_search_timeout_seconds) as client:
                response = await client.get(
                    f"{settings.web_search_searxng_base_url.rstrip('/')}/search",
                    params=params,
                )
        except httpx.HTTPError as exc:
            raise AppException(502, "WEB_SEARCH_UPSTREAM_UNAVAILABLE", f"SearXNG request failed: {exc}") from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise AppException(502, "WEB_SEARCH_INVALID_RESPONSE", "SearXNG returned invalid JSON") from exc

        if response.status_code >= 400:
            raise AppException(
                502,
                "WEB_SEARCH_UPSTREAM_ERROR",
                f"SearXNG returned status {response.status_code}",
            )

        raw_results = data.get("results") if isinstance(data, dict) else None
        if not isinstance(raw_results, list):
            return []

        parsed: list[SearchResult] = []
        for item in raw_results[: settings.web_search_max_results]:
            if not isinstance(item, dict):
                continue
            url = _normalize_url(str(item.get("url") or ""))
            if not url:
                continue
            parsed.append(
                SearchResult(
                    title=str(item.get("title") or url).strip(),
                    url=url,
                    snippet=_coalesce_text(item.get("content"), item.get("snippet")),
                    score=_safe_float(item.get("score")),
                    provider=self.name,
                    metadata={"engine": item.get("engine")},
                )
            )
        return parsed

    async def extract(self, results: list[SearchResult]) -> list[ExtractedDocument]:
        del results
        return []


@dataclass(slots=True)
class HttpDocumentExtractor:
    name: str = "http-fetch"

    async def extract(self, results: list[SearchResult]) -> list[ExtractedDocument]:
        documents: list[ExtractedDocument] = []
        for item in results:
            content = await self._fetch_text(item.url)
            if not content:
                continue
            documents.append(
                ExtractedDocument(
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
                timeout=settings.web_search_extract_timeout_seconds,
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
            return text[: settings.web_search_max_document_chars].strip()

        cleaned = re.sub(r"(?is)<script.*?>.*?</script>", " ", text)
        cleaned = re.sub(r"(?is)<style.*?>.*?</style>", " ", cleaned)
        cleaned = re.sub(r"(?is)<noscript.*?>.*?</noscript>", " ", cleaned)
        cleaned = re.sub(r"(?s)<[^>]+>", " ", cleaned)
        cleaned = html.unescape(cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned[: settings.web_search_max_document_chars]


def build_web_search_providers() -> list[WebSearchProvider]:
    provider_map: dict[str, WebSearchProvider] = {
        "tavily": TavilyProvider(),
        "searxng": SearXNGProvider(),
    }
    providers: list[WebSearchProvider] = []
    for name in settings.web_search_provider_preference:
        provider = provider_map.get(name.lower().strip())
        if provider:
            providers.append(provider)
    return providers


def _normalize_url(url: str) -> str:
    if not url:
        return ""
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
