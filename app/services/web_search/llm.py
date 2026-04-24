from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.providers.openai_compat import OpenAICompatProvider
from app.repos.model_node_repo import ModelNodeRepo
from app.schemas.chat import ChatCompletionRequest, ChatMessageInput
from app.services.web_search.models import EvidenceChunk, SearchPlan


class WebSearchLLMOrchestrator:
    def __init__(self, session: AsyncSession):
        self.model_nodes = ModelNodeRepo(session)
        self.provider = OpenAICompatProvider()

    async def build_plan(
        self,
        *,
        query_text: str,
        allowed_models: list[str],
        requested_model: str | None,
    ) -> SearchPlan:
        node = await self._select_node(requested_model=requested_model, allowed_models=allowed_models)
        if not node:
            return self._heuristic_plan(query_text)

        prompt = (
            "You are a web search planner. Output JSON only.\n"
            "Return this schema:\n"
            '{'
            '"queries":["..."],'
            '"topic":"general|news|finance",'
            '"time_range":"day|week|month|year|null",'
            '"include_domains":["..."],'
            '"exclude_domains":["..."],'
            '"search_depth":"basic|advanced"'
            '}\n'
            "Rules:\n"
            "- Keep 1 to 3 queries.\n"
            "- Prefer concise, high-recall search queries.\n"
            "- Use topic=news only for clearly time-sensitive questions.\n"
            "- When the query targets a company, product, API, library, or changelog, prefer official domains.\n"
            "- Exclude marketplaces, SEO spam, mirrors, and third-party wrappers when they are not primary sources.\n"
            "- Return valid JSON and nothing else."
        )

        try:
            response_text = await self._run_prompt(
                node=node,
                messages=[
                    ChatMessageInput(role="system", content=prompt),
                    ChatMessageInput(role="user", content=f"Original query: {query_text}"),
                ],
                temperature=0.1,
                max_tokens=300,
            )
        except Exception:
            return self._heuristic_plan(query_text)

        parsed = self._parse_json_object(response_text)
        if not isinstance(parsed, dict):
            return self._heuristic_plan(query_text)

        queries = parsed.get("queries")
        if not isinstance(queries, list):
            return self._heuristic_plan(query_text)

        normalized_queries = [
            str(item).strip()
            for item in queries
            if isinstance(item, str) and item.strip()
        ][: settings.web_search_max_queries]
        if not normalized_queries:
            return self._heuristic_plan(query_text)

        fallback = self._heuristic_plan(query_text)
        topic = str(parsed.get("topic") or fallback.topic).strip().lower()
        if topic not in {"general", "news", "finance"}:
            topic = fallback.topic

        time_range = parsed.get("time_range")
        if time_range is not None:
            time_range = str(time_range).strip().lower() or None
        if time_range not in {None, "day", "week", "month", "year"}:
            time_range = fallback.time_range

        search_depth = str(parsed.get("search_depth") or fallback.search_depth).strip().lower()
        if search_depth not in {"basic", "advanced"}:
            search_depth = fallback.search_depth

        return SearchPlan(
            query=query_text.strip(),
            queries=normalized_queries,
            topic=topic,
            time_range=time_range,
            include_domains=self._normalize_domains(parsed.get("include_domains")),
            exclude_domains=self._normalize_domains(parsed.get("exclude_domains")),
            search_depth=search_depth,
        )

    async def synthesize_answer(
        self,
        *,
        query_text: str,
        evidence_chunks: list[EvidenceChunk],
        allowed_models: list[str],
        requested_model: str | None,
    ) -> str:
        if not evidence_chunks:
            return "没有抓到足够的网页证据，暂时无法给出可靠结论。"

        node = await self._select_node(requested_model=requested_model, allowed_models=allowed_models)
        if not node:
            return self._fallback_answer(query_text, evidence_chunks)

        evidence_text = "\n\n".join(
            f"[{index}] {item.title}\nURL: {item.url}\n{item.text}"
            for index, item in enumerate(evidence_chunks, start=1)
        )
        prompt = (
            "你是一个强硬、准确、以证据为中心的中文研究助手。\n"
            "只允许基于给定证据回答，不要编造。\n"
            "如果证据不足，要明确指出。\n"
            "引用证据时使用 [1] [2] 这种编号。\n"
            "先给结论，再给关键依据。"
        )

        try:
            return await self._run_prompt(
                node=node,
                messages=[
                    ChatMessageInput(role="system", content=prompt),
                    ChatMessageInput(role="user", content=f"用户问题：{query_text}\n\n证据：\n{evidence_text}"),
                ],
                temperature=0.2,
                max_tokens=1000,
            )
        except Exception:
            return self._fallback_answer(query_text, evidence_chunks)

    async def _select_node(self, *, requested_model: str | None, allowed_models: list[str]):
        del requested_model
        del allowed_models
        preferred_code = settings.resolved_web_search_llm_node_code
        node = await self.model_nodes.get_by_code(preferred_code)
        if node and node.enabled:
            return node
        return None

    async def _run_prompt(
        self,
        *,
        node,
        messages: list[ChatMessageInput],
        temperature: float,
        max_tokens: int,
    ) -> str:
        payload = ChatCompletionRequest(
            messages=messages,
            model=node.model_name,
            stream=False,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        result = await self.provider.create_chat_completion(node=node, payload=payload)
        return str(result.content or "").strip()

    @staticmethod
    def _parse_json_object(text: str) -> dict[str, Any] | None:
        if not text:
            return None
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            matched = re.search(r"\{.*\}", text, flags=re.DOTALL)
            if not matched:
                return None
            try:
                parsed = json.loads(matched.group(0))
            except json.JSONDecodeError:
                return None
        return parsed if isinstance(parsed, dict) else None

    @staticmethod
    def _normalize_domains(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if isinstance(item, str) and item.strip()][:20]

    @staticmethod
    def _fallback_answer(query_text: str, evidence_chunks: list[EvidenceChunk]) -> str:
        lines = [f"针对“{query_text}”，基于当前抓到的网页证据，关键信息如下："]
        for index, item in enumerate(evidence_chunks[:3], start=1):
            preview = item.text.replace("\n", " ").strip()
            if len(preview) > 280:
                preview = f"{preview[:277]}..."
            lines.append(f"{index}. {item.title}: {preview}")
        return "\n".join(lines)

    @staticmethod
    def _heuristic_plan(query_text: str) -> SearchPlan:
        normalized = query_text.strip()
        topic = "general"
        time_range: str | None = None
        lowered = normalized.lower()
        if any(keyword in lowered for keyword in ("latest", "today", "news", "recent")):
            topic = "news"
            time_range = "week"
        if any(keyword in normalized for keyword in ("最新", "今天", "新闻", "近况", "最近")):
            topic = "news"
            time_range = "week"
        return SearchPlan(
            query=normalized,
            queries=[normalized],
            topic=topic,
            time_range=time_range,
            search_depth=settings.web_search_default_search_depth,
        )
