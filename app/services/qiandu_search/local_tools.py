from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

SNOOP_ROOT = Path("/opt/snoop")
SNOOP_CSV_DIR = SNOOP_ROOT / "results" / "nicknames" / "csv"
SOCIAL_ACCOUNT_DOMAINS = [
    "weibo.com",
    "www.weibo.com",
    "bilibili.com",
    "www.bilibili.com",
    "zhihu.com",
    "www.zhihu.com",
    "xiaohongshu.com",
    "www.xiaohongshu.com",
    "douyin.com",
    "www.douyin.com",
    "github.com",
]


def run_snoop_search(query: str) -> dict[str, Any]:
    if not query.strip():
        return {"results": []}
    if not SNOOP_ROOT.exists():
        return _fallback_social_search(query, warning="Snoop is not installed in the current runtime.")

    before_files = {path.resolve() for path in SNOOP_CSV_DIR.glob("*.csv")} if SNOOP_CSV_DIR.exists() else set()
    command = [
        sys.executable,
        "snoop.py",
        "--no-func",
        "--found-print",
        "--time-out",
        "6",
        "--web-base",
        query,
    ]
    completed = subprocess.run(
        command,
        cwd=SNOOP_ROOT,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="ignore",
        timeout=max(settings.qiandu_timeout_seconds, 60),
        check=False,
    )
    if completed.returncode != 0:
        preview = completed.stderr.strip() or completed.stdout.strip() or f"snoop exited with {completed.returncode}"
        return _fallback_social_search(query, warning=preview[:1000])

    csv_path = _find_latest_snoop_csv(before_files)
    results = _parse_snoop_csv(csv_path) if csv_path else []
    if not results:
        warning = completed.stdout.strip()[:1000] if completed.stdout.strip() else "Snoop returned no structured hits."
        return _fallback_social_search(query, warning=warning)
    return {
        "results": results,
        "stdout_preview": completed.stdout[:4000],
        "csv_path": str(csv_path) if csv_path else "",
    }


def run_wechat_public_search(query: str) -> dict[str, Any]:
    if not query.strip():
        return {"results": []}

    searxng_base = (settings.qiandu_searxng_base_url or settings.web_search_searxng_base_url or "").rstrip("/")
    if searxng_base:
        try:
            params = {
                "q": f"site:mp.weixin.qq.com {query}",
                "format": "json",
                "language": settings.qiandu_searxng_language,
                "engines": ",".join(settings.qiandu_searxng_engines or ["baidu", "sogou"]),
            }
            with httpx.Client(timeout=settings.qiandu_timeout_seconds) as client:
                response = client.get(f"{searxng_base}/search", params=params)
                response.raise_for_status()
                payload = response.json()
            raw_results = payload.get("results") if isinstance(payload, dict) else []
            normalized = _normalize_search_results(raw_results, provider="wechat_crawler")
            if normalized:
                return {"results": normalized}
        except Exception as exc:
            logger.warning("SearXNG WeChat lookup failed, falling back to Tavily: %s", exc)

    tavily_key = settings.qiandu_tavily_api_key or settings.web_search_tavily_api_key
    if tavily_key:
        with httpx.Client(timeout=settings.qiandu_timeout_seconds) as client:
            response = client.post(
                f"{settings.qiandu_tavily_base_url.rstrip('/')}/search",
                headers={
                    "Authorization": f"Bearer {tavily_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "query": f"{query} 公众号",
                    "search_depth": "advanced",
                    "topic": "general",
                    "include_domains": ["mp.weixin.qq.com"],
                    "max_results": settings.qiandu_max_results,
                },
            )
            response.raise_for_status()
            payload = response.json()
        raw_results = payload.get("results") if isinstance(payload, dict) else []
        return {"results": _normalize_search_results(raw_results, provider="wechat_crawler")}

    return {"results": [], "warning": "Neither SearXNG nor Tavily is configured for WeChat public search."}


def _fallback_social_search(query: str, *, warning: str | None = None) -> dict[str, Any]:
    results = _search_with_tavily(
        query=f"{query} 社交账号",
        include_domains=SOCIAL_ACCOUNT_DOMAINS,
        provider="snoop_fallback",
    )
    payload: dict[str, Any] = {"results": results}
    if warning:
        payload["warning"] = warning
    return payload


def _search_with_tavily(
    *,
    query: str,
    include_domains: list[str],
    provider: str,
) -> list[dict[str, Any]]:
    tavily_key = settings.qiandu_tavily_api_key or settings.web_search_tavily_api_key
    if not tavily_key:
        return []
    with httpx.Client(timeout=settings.qiandu_timeout_seconds) as client:
        response = client.post(
            f"{settings.qiandu_tavily_base_url.rstrip('/')}/search",
            headers={
                "Authorization": f"Bearer {tavily_key}",
                "Content-Type": "application/json",
            },
            json={
                "query": query,
                "search_depth": "advanced",
                "topic": "general",
                "include_domains": include_domains,
                "max_results": settings.qiandu_max_results,
            },
        )
        response.raise_for_status()
        payload = response.json()
    raw_results = payload.get("results") if isinstance(payload, dict) else []
    return _normalize_search_results(raw_results, provider=provider)


def _find_latest_snoop_csv(before_files: set[Path]) -> Path | None:
    if not SNOOP_CSV_DIR.exists():
        return None
    after_files = {path.resolve() for path in SNOOP_CSV_DIR.glob("*.csv")}
    candidates = list(after_files - before_files) or list(after_files)
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _parse_snoop_csv(path: Path | None) -> list[dict[str, Any]]:
    if not path or not path.exists():
        return []
    results: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        for row in reader:
            if len(row) < 6:
                continue
            if row[0] in {"Resource", "袪械褋褍褉褋"}:
                continue
            resource, geo, base_url, profile_url, status, http_code = row[:6]
            profile_url = profile_url.strip()
            if not profile_url.startswith(("http://", "https://")):
                continue
                
            title = resource.strip() or "Snoop result"
            snippet = f"geo={geo.strip()} status={status.strip()} http={http_code.strip()} source={base_url.strip()}"
            
            if match := re.search(r"xiaohongshu\.com/user/profile/([A-Za-z0-9]+)", profile_url):
                title = f"{title} [Xiaohongshu: {match.group(1)}]"
                snippet += f" Platform=Xiaohongshu ID={match.group(1)}"
            elif match := re.search(r"douyin\.com/user/([A-Za-z0-9_-]+)", profile_url):
                title = f"{title} [Douyin: {match.group(1)}]"
                snippet += f" Platform=Douyin SecUID={match.group(1)}"
            elif match := re.search(r"weibo\.com/(?:u|n)/([A-Za-z0-9_-]+)", profile_url):
                title = f"{title} [Weibo: {match.group(1)}]"
                snippet += f" Platform=Weibo UID={match.group(1)}"
            elif match := re.search(r"space\.bilibili\.com/(\d+)", profile_url):
                title = f"{title} [Bilibili: {match.group(1)}]"
                snippet += f" Platform=Bilibili UID={match.group(1)}"

            results.append(
                {
                    "title": title,
                    "url": profile_url,
                    "profile": profile_url,
                    "snippet": snippet,
                    "score": 1.0,
                }
            )
    return results[: settings.qiandu_max_results]


def _normalize_search_results(raw_results: Any, *, provider: str) -> list[dict[str, Any]]:
    if not isinstance(raw_results, list):
        return []
    parsed: list[dict[str, Any]] = []
    for item in raw_results:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            continue
        title = str(item.get("title") or url).strip()
        snippet = str(item.get("content") or item.get("snippet") or "").strip()
        score_value = item.get("score")
        try:
            score = float(score_value)
        except (TypeError, ValueError):
            score = 1.0
        parsed.append(
            {
                "title": title,
                "url": url,
                "snippet": snippet[:1200],
                "score": score,
                "provider": provider,
            }
        )
    return parsed[: settings.qiandu_max_results]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("tool", choices=["snoop", "wechat"])
    parser.add_argument("--query", required=True)
    args = parser.parse_args()

    try:
        if args.tool == "snoop":
            payload = run_snoop_search(args.query)
        else:
            payload = run_wechat_public_search(args.query)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
