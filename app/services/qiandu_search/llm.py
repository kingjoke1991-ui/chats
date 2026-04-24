from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.providers.openai_compat import OpenAICompatProvider
from app.repos.model_node_repo import ModelNodeRepo
from app.schemas.chat import ChatCompletionRequest, ChatMessageInput
from app.services.qiandu_search.models import (
    QianduEvidenceChunk,
    QianduIntelExtraction,
    QianduSearchPlan,
    QianduSearchTask,
)


class QianduSearchLLMOrchestrator:
    def __init__(self, session: AsyncSession):
        self.model_nodes = ModelNodeRepo(session)
        self.provider = OpenAICompatProvider()

    async def build_plan(
        self,
        *,
        query_text: str,
        allowed_models: list[str],
        requested_model: str | None,
    ) -> QianduSearchPlan:
        node = await self._select_node(requested_model=requested_model, allowed_models=allowed_models)
        if not node:
            return self._heuristic_plan(query_text)

        prompt = (
            "You are a China-focused search planner for an intelligence assistant. Output JSON only.\n"
            "Return this schema:\n"
            '{'
            '"queries":["..."],'
            '"intent":"general|social_id|wechat|legal_entity|person|company",'
            '"topic":"general|news",'
            '"time_range":"day|week|month|year|null",'
            '"include_domains":["..."],'
            '"exclude_domains":["..."],'
            '"preferred_providers":["snoop","wechat_crawler","tavily","exa","searxng"]'
            '}\n'
            "Rules:\n"
            "- Keep 1 to 4 queries.\n"
            "- If the target looks like a Chinese social-media handle, username, phone, or account ID, prefer intent=social_id and add Weibo-style queries.\n"
            "- If the target mentions 公众号, 微信, 微信公众号, 或公号, prefer intent=wechat and include mp.weixin.qq.com.\n"
            "- If the target is a company, 法人, 股东, enterprise info, or judicial/court records (诉讼, 判决, 法院), prefer intent=legal_entity and prioritize qcc.com and court.gov.cn.\n"
            "- Use snoop and wechat_crawler only when the target matches their strengths.\n"
            "- Avoid spam, mirrors, SEO wrappers, and marketplaces.\n"
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
                max_tokens=400,
            )
        except Exception:
            return self._heuristic_plan(query_text)
        response_text = self._clean_llm_response(response_text)
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
        ][: settings.qiandu_max_queries]
        if not normalized_queries:
            return self._heuristic_plan(query_text)

        fallback = self._heuristic_plan(query_text)
        intent = str(parsed.get("intent") or fallback.intent).strip().lower()
        if intent not in {"general", "social_id", "wechat", "legal_entity", "person", "company"}:
            intent = fallback.intent

        topic = str(parsed.get("topic") or fallback.topic).strip().lower()
        if topic not in {"general", "news"}:
            topic = fallback.topic

        time_range = parsed.get("time_range")
        if time_range is not None:
            time_range = str(time_range).strip().lower() or None
        if time_range not in {None, "day", "week", "month", "year"}:
            time_range = fallback.time_range

        include_domains = self._normalize_domains(parsed.get("include_domains"))
        exclude_domains = self._normalize_domains(parsed.get("exclude_domains"))
        preferred_providers = self._normalize_providers(parsed.get("preferred_providers"))

        if not preferred_providers:
            preferred_providers = fallback.preferred_providers

        return QianduSearchPlan(
            query=query_text.strip(),
            queries=normalized_queries,
            intent=intent,
            topic=topic,
            time_range=time_range,
            include_domains=include_domains,
            exclude_domains=exclude_domains,
            preferred_providers=preferred_providers,
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
        if not evidence_chunks:
            return "没有抓到足够的证据，暂时无法给出可靠结论。"

        node = await self._select_node(requested_model=requested_model, allowed_models=allowed_models)
        if not node:
            return self._fallback_answer(query_text, evidence_chunks)

        evidence_text = "\n\n".join(
            f"[{index}] {item.title}\nURL: {item.url}\n{item.text}"
            for index, item in enumerate(evidence_chunks, start=1)
        )
        prompt = (
            "你是一个犀利、克制、以证据为中心的中文检索分析助手。\n"
            "只允许基于给定证据回答，不要编造。\n"
            "先给直接结论，再给关键依据，再给不确定点。\n"
            "引用证据时使用 [1] [2] 编号。\n"
            "如果对象可能是社交账号、公众号或企业主体，优先指出可核实字段。"
        )

        try:
            result_text = await self._run_prompt(
                node=node,
                messages=[
                    ChatMessageInput(role="system", content=prompt),
                    ChatMessageInput(
                        role="user",
                        content=(
                            f"用户问题：{query_text}\n"
                            f"推断意图：{plan.intent}\n\n"
                            f"证据：\n{evidence_text}"
                        ),
                    ),
                ],
                temperature=0.2,
                max_tokens=1200,
            )
            return self._clean_llm_response(result_text)
        except Exception:
            return self._fallback_answer(query_text, evidence_chunks)

    @staticmethod
    def detect_structured_input(text: str) -> bool:
        if not text or len(text) < 50:
            return False
        if "数据来源" in text or text.count("\n") > 5:
            keywords = ["姓名", "证件", "手机", "地址", "归属", "企业", "公司"]
            matches = sum(1 for kw in keywords if kw in text)
            if matches >= 3:
                return True
        return False

    async def extract_entities(
        self,
        *,
        raw_input: str,
        allowed_models: list[str],
        requested_model: str | None,
    ) -> QianduIntelExtraction:
        node = await self._select_node(requested_model=requested_model, allowed_models=allowed_models)
        if not node:
             raise ValueError("No valid LLM node available for extraction")

        prompt = (
            "你是一个“信息解析与任务规划引擎”，你的目标不是回答问题，而是：\n"
            "1. 提取输入中的所有关键信息\n"
            "2. 去除重复和明显冗余\n"
            "3. 识别信息类型\n"
            "【严格要求】不要猜测、不要补充、只基于输入内容、输出必须是JSON，字段匹配如下结构：\n"
            "{\n"
            '  "summary": "高度压缩总结（不要超过100字）",\n'
            '  "names": [],\n'
            '  "phones": [],\n'
            '  "id_numbers": [],\n'
            '  "addresses": [{"province": "", "city": "", "district": "", "detail": ""}],\n'
            '  "organizations": [],\n'
            '  "other_fields": {"邮箱": [], "车牌": []},\n'
            '  "data_quality": "low/medium/high"\n'
            "}\n"
        )

        response_text = await self._run_prompt(
            node=node,
            messages=[
                ChatMessageInput(role="system", content=prompt),
                ChatMessageInput(role="user", content=f"【输入数据】\n{raw_input}"),
            ],
            temperature=0.1,
            max_tokens=1000,
        )
        response_text = self._clean_llm_response(response_text)
        parsed = self._parse_json_object(response_text) or {}
        return QianduIntelExtraction(
            summary=parsed.get("summary", ""),
            names=self._ensure_str_list(parsed.get("names", [])),
            phones=self._ensure_str_list(parsed.get("phones", [])),
            id_numbers=self._ensure_str_list(parsed.get("id_numbers", [])),
            addresses=parsed.get("addresses", []),
            organizations=self._ensure_str_list(parsed.get("organizations", [])),
            other_fields=parsed.get("other_fields", {}),
            data_quality=parsed.get("data_quality", "medium"),
            raw_input=raw_input,
        )

    async def generate_search_tasks(
        self,
        *,
        extraction: QianduIntelExtraction,
        allowed_models: list[str],
        requested_model: str | None,
    ) -> list[QianduSearchTask]:
        node = await self._select_node(requested_model=requested_model, allowed_models=allowed_models)
        if not node:
             raise ValueError("No valid LLM node available for task generation")

        normalized_data = json.dumps({
            "names": extraction.names,
            "phones": extraction.phones,
            "id_numbers": extraction.id_numbers,
            "organizations": extraction.organizations,
            "addresses": extraction.addresses,
        }, ensure_ascii=False)

        prompt = (
            "你是一个“大陆OSINT搜索策略引擎”。目标：基于已有结构化数据，定位目标在大陆的网络足迹与商业/司法关联。\n"
            "【关键策略 - 必须执行】\n"
            "- 必须使用大陆特定术语：如“法定代表人”、“股东情况”、“执行信息”、“失信记录”作为查询关键词。\n"
            "- 强制生成组合查询：[姓名 + 精准地理位置]、[姓名 + 身份证前6位]、[姓名 + 手机前3后4]。\n"
            "- 禁止生成过于笼统的查询（如只搜姓名）。\n"
            "- 识别：LinkedIn/Facebook等海外站点在大陆重名率极高且价值极低，必须通过增加组合关键词来过滤。\n"
            "内置自我反思：检查任务是否更偏向大陆本土数据源（爱企查/裁判文书/微博/小红书）。\n"
            "【输出格式】必须是JSON：\n"
            "{\n"
            '  "tasks": [\n'
            '    {\n'
            '      "task_id": "t1",\n'
            '      "task_type": "legal_entity",\n'
            '      "query": "姓名 + 地域/公司 裁判文书",\n'
            '      "goal": "核实大陆司法记录与商业关联",\n'
            '      "priority": 1,\n'
            '      "include_domains": ["court.gov.cn", "qcc.com", "aiqicha.baidu.com"],\n'
            '      "preferred_providers": ["searxng", "tavily"]\n'
            '    }\n'
            "  ]\n"
            "}\n"
        )

        response_text = await self._run_prompt(
            node=node,
            messages=[
                ChatMessageInput(role="system", content=prompt),
                ChatMessageInput(role="user", content=f"【可用数据】\n{normalized_data}"),
            ],
            temperature=0.2,
            max_tokens=1000,
        )
        response_text = self._clean_llm_response(response_text)
        parsed = self._parse_json_object(response_text) or {}
        tasks_data = parsed.get("tasks", [])
        results: list[QianduSearchTask] = []
        for index, item in enumerate(tasks_data):
            if not isinstance(item, dict):
                continue
            query = str(item.get("query") or "").strip()
            if not query:
                continue
            results.append(
                QianduSearchTask(
                    task_id=str(item.get("task_id") or f"task_{index}"),
                    task_type=str(item.get("task_type") or "entity_lookup"),
                    query=query,
                    goal=str(item.get("goal") or ""),
                    priority=int(item.get("priority") or 2),
                    include_domains=self._normalize_domains(item.get("include_domains")),
                    preferred_providers=self._normalize_providers(item.get("preferred_providers")),
                )
            )
        return results[:settings.qiandu_max_search_tasks]

    async def fuse_intel_report(
        self,
        *,
        extraction: QianduIntelExtraction,
        search_results: list[QianduEvidenceChunk],
        allowed_models: list[str],
        requested_model: str | None,
    ) -> str:
        node = await self._select_node(requested_model=requested_model, allowed_models=allowed_models)
        if not node:
             return "无法合成最终情报报告"

        evidence_text = "\n\n".join(
            f"[{index}] {item.title}\nURL: {item.url}\n{item.text}"
            for index, item in enumerate(search_results, start=1)
        )

        prompt = (
            "你是一个“大陆情报深度分析引擎”。\n"
            "任务：汇总原始数据与最新的外部搜索结果，生成一份【针对大陆背景】的增量式情报报告。\n"
            "【报告指引】\n"
            "1. 优先级：优先呈现来自 爱企查、天眼查、裁判文书网、微博、知乎、小红书 等大陆本土平台的新事实。\n"
            "2. 噪音剔除：LinkedIn、Facebook 等全球性站点的结果在搜索“张三、李四”类常见中文名时极易产生误报。如果证据[n]中的人员职位与原始数据环境不符，必须果断剔除或标记为“高度疑似误报”。\n"
            "3. 核心新发现：不仅要列出姓名，更要列出其名下的公司占股、司法纠纷的具体案号、或是某个社交平台的精准UID。\n"
            "4. 逻辑：利用搜索到的“新关联”来补完原始数据的“空白点”。\n"
            "输出一份极具深度的大陆背景情报报告。使用 Markdown 格式，引用证据请使用 [1] [2] 编号。"
        )

        response_text = await self._run_prompt(
            node=node,
            messages=[
                ChatMessageInput(role="system", content=prompt),
                ChatMessageInput(
                    role="user",
                    content=(
                        f"【原始结构化数据摘要】\n{extraction.summary}\n\n"
                        f"【外部证据检索结果】\n{evidence_text}"
                    )
                ),
            ],
            temperature=0.3,
            max_tokens=3000,
        )
        return self._clean_llm_response(response_text)

    def _clean_llm_response(self, text: str) -> str:
        if not text:
            return ""
        # Remove common thought/reasoning tags
        text = re.sub(r'<(?:thought|reasoning|thinking|details)>.*?</(?:thought|reasoning|thinking|details)>', '', text, flags=re.DOTALL | re.IGNORECASE)
        # Remove markers like "Thought:", "Reasoning:", etc. at the start of blocks
        text = re.sub(r'^(?:Thought|Reasoning|Thinking|Analysis):\s*.*?(?=\n\n|\n[#\d])', '', text, flags=re.DOTALL | re.IGNORECASE | re.MULTILINE)
        return text.strip()

    @staticmethod
    def _ensure_str_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(v).strip() for v in value if v]

    async def _select_node(self, *, requested_model: str | None, allowed_models: list[str]):
        del requested_model
        del allowed_models
        preferred_code = settings.resolved_qiandu_llm_node_code
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
    def _normalize_providers(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        allowed = {"snoop", "wechat_crawler", "tavily", "exa", "searxng"}
        return [item.strip().lower() for item in value if isinstance(item, str) and item.strip().lower() in allowed][:5]

    @staticmethod
    def _fallback_answer(query_text: str, evidence_chunks: list[QianduEvidenceChunk]) -> str:
        lines = [f"针对“{query_text}”，基于当前抓到的证据，先给出关键线索："]
        for index, item in enumerate(evidence_chunks[:4], start=1):
            preview = item.text.replace("\n", " ").strip()
            if len(preview) > 280:
                preview = f"{preview[:277]}..."
            lines.append(f"{index}. {item.title}: {preview}")
        lines.append("结论仍需结合来源链接进一步核实。")
        return "\n".join(lines)

    @staticmethod
    def _heuristic_plan(query_text: str) -> QianduSearchPlan:
        normalized = query_text.strip()
        lowered = normalized.lower()
        queries = [normalized]
        intent = "general"
        topic = "general"
        time_range: str | None = None
        include_domains: list[str] = []
        preferred_providers = ["tavily", "exa", "searxng"]

        social_keywords = ("微博", "抖音", "快手", "小红书", "账号", "id", "uid", "@")
        wechat_keywords = ("公众号", "微信", "公号", "wechat")
        legal_keywords = ("法人", "股东", "注册资本", "统一社会信用代码", "公司", "企业", "工商", "企查查", "裁判", "文书", "判决书", "法院", "执行")
        news_keywords = ("最新", "今天", "最近", "新闻", "近况", "最新进展", "latest", "today", "news", "recent")

        if any(keyword in normalized for keyword in wechat_keywords):
            intent = "wechat"
            preferred_providers = ["wechat_crawler", "tavily", "searxng", "exa"]
            include_domains = ["mp.weixin.qq.com"]
            queries.extend([f"{normalized} 公众号", f"{normalized} site:mp.weixin.qq.com"])
        elif any(keyword in normalized for keyword in legal_keywords):
            intent = "legal_entity"
            preferred_providers = ["tavily", "exa", "searxng"]
            include_domains = ["qcc.com", "court.gov.cn"]
            queries.extend([f"{normalized} 企查查", f"{normalized} 法院 判决书"])
        elif any(keyword in normalized for keyword in social_keywords) or re.search(r"[@_A-Za-z0-9]{4,}", normalized):
            intent = "social_id"
            preferred_providers = ["snoop", "tavily", "searxng", "exa"]
            include_domains = ["weibo.com"]
            queries.extend([f"{normalized} 微博", f"{normalized} 账号"])

        if any(keyword in lowered for keyword in news_keywords) or any(keyword in normalized for keyword in news_keywords):
            topic = "news"
            time_range = "week"

        deduped_queries: list[str] = []
        seen_queries: set[str] = set()
        for item in queries:
            compact = item.strip()
            if not compact or compact in seen_queries:
                continue
            deduped_queries.append(compact)
            seen_queries.add(compact)
            if len(deduped_queries) >= settings.qiandu_max_queries:
                break

        return QianduSearchPlan(
            query=normalized,
            queries=deduped_queries or [normalized],
            intent=intent,
            topic=topic,
            time_range=time_range,
            include_domains=include_domains,
            preferred_providers=preferred_providers,
        )
