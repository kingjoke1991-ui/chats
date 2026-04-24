from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.providers.openai_compat import OpenAICompatProvider
from app.repos.model_node_repo import ModelNodeRepo
from app.schemas.chat import ChatCompletionRequest, ChatMessageInput
from app.services.qiandu_search.dimensions import (
    DIMENSION_KEYWORDS as _DIMENSION_KEYWORDS,
    DOMAIN_ALLOWLIST as QIANDU_DOMAIN_ALLOWLIST,
    INTENT_CHOICES as QIANDU_INTENT_CHOICES,
    INTEL_DIMENSIONS,
    canonical_dimension,
)
from app.services.qiandu_search.models import (
    QianduEvidenceChunk,
    QianduIntelExtraction,
    QianduSearchPlan,
    QianduSearchTask,
)

__all__ = [
    "QianduSearchLLMOrchestrator",
    "QIANDU_DOMAIN_ALLOWLIST",
    "QIANDU_INTENT_CHOICES",
]


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
            "{"
            '"queries":["..."],'
            '"intent":"general|social|social_id|wechat|business|legal_entity|judicial|education|profession|person|company|news",'
            '"topic":"general|news",'
            '"time_range":"day|week|month|year|null",'
            '"include_domains":["..."],'
            '"exclude_domains":["..."],'
            '"preferred_providers":["snoop","wechat_crawler","tavily","exa","searxng"]'
            "}\n"
            "Rules:\n"
            "- Keep 1 to 4 queries.\n"
            "- For social account / handle lookups use intent=social (or social_id).\n"
            "- For 公众号 use intent=wechat and prefer mp.weixin.qq.com.\n"
            "- For 工商 / 法人 / 股东 / 企业 info use intent=business and prefer qcc.com, tianyancha.com, aiqicha.baidu.com.\n"
            "- For 诉讼 / 判决 / 执行 / 失信 use intent=judicial and prefer wenshu.court.gov.cn and zxgk.court.gov.cn.\n"
            "- For 教育 / 学历 / 院校 / 毕业 use intent=education.\n"
            "- For 职业 / 任职 / 履历 use intent=profession.\n"
            "- For 新闻 / 舆情 use topic=news.\n"
            "- Avoid spam, mirrors, SEO wrappers, and marketplaces.\n"
            "- Return valid JSON only."
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
        if intent not in QIANDU_INTENT_CHOICES:
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
            "你是一个以证据为中心的中文综合查询分析助手。\n"
            "只允许基于给定证据回答，不要编造。\n"
            "先给直接结论，再给关键依据，再给不确定点。\n"
            "引用证据时使用 [1] [2] 编号。\n"
            "如果目标是社交账号、公众号、企业主体、司法记录、教育背景或职业信息，"
            "优先指出该维度下可核实的字段。"
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

    def should_trigger_intel_pipeline(self, text: str) -> bool:
        """Decide whether to fire the multi-dimension intel pipeline.

        Thin wrapper over :meth:`classify_trigger` — see that method's
        docstring for the full signal list and scoring rules. The intel
        pipeline spends 3 LLM calls and up to ``qiandu_max_search_tasks``
        parallel provider hits, so we only fire it when the input carries
        enough signal that a multi-dimensional OSINT sweep is worth the
        cost. Otherwise we fall through to the cheaper simple pipeline.
        """

        return self.classify_trigger(text)["pipeline"] == "intel_fusion"

    def classify_trigger(self, text: str) -> dict[str, object]:
        """Expose the routing decision and its score for observability.

        Signals (each worth 1 point unless noted; threshold configurable
        via ``QIANDU_INTEL_SIGNAL_THRESHOLD``, default 2):

        * phone number (+2) / id number (+2) / email / ``@handle``
        * an organization mention (公司 / 集团 / 学校 / 医院 / …)
        * a dimension keyword hit (工商 / 裁判 / 学历 / 公众号 / …)
        * 2+ distinct Chinese-name-shaped tokens
        * multi-line structured input (>= 3 newlines) or >= 60 chars
        """

        if not text:
            return {"pipeline": "simple", "score": 0, "threshold": 0, "reason": "empty"}
        stripped = text.strip()
        if len(stripped) < 2:
            return {"pipeline": "simple", "score": 0, "threshold": 0, "reason": "too_short"}
        if re.match(r"^https?://\S+$", stripped):
            return {"pipeline": "simple", "score": 0, "threshold": 0, "reason": "bare_url"}

        threshold = max(1, int(getattr(settings, "qiandu_intel_signal_threshold", 2)))
        reasons: list[str] = []
        score = 0
        if re.search(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)", stripped):
            score += 2
            reasons.append("phone")
        if re.search(
            r"\b[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx]\b",
            stripped,
        ):
            score += 2
            reasons.append("id")
        if re.search(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", stripped):
            score += 1
            reasons.append("email")
        if re.search(r"@[A-Za-z0-9_\-.]{3,}", stripped):
            score += 1
            reasons.append("handle")
        if re.search(
            r"[\u4e00-\u9fff]{2,}(?:公司|集团|厂|有限责任公司|股份有限公司|"
            r"事务所|工作室|学校|大学|学院|医院|研究院|协会|基金会)",
            stripped,
        ):
            score += 1
            reasons.append("organization")
        lowered = stripped.lower()
        if any(
            kw.lower() in lowered
            for keywords in _DIMENSION_KEYWORDS.values()
            for kw in keywords
        ):
            score += 1
            reasons.append("dimension_keyword")
        chinese_tokens = re.findall(r"[\u4e00-\u9fff]{2,4}", stripped)
        if len(set(chinese_tokens)) >= 2:
            score += 1
            reasons.append("multi_name")
        if stripped.count("\n") >= 2 or len(stripped) >= 60:
            score += 1
            reasons.append("structured_dump")

        return {
            "pipeline": "intel_fusion" if score >= threshold else "simple",
            "score": score,
            "threshold": threshold,
            "reason": ",".join(reasons) or "no_signal",
        }

    @staticmethod
    def detect_structured_input(text: str) -> bool:
        """Retained for backwards compatibility with legacy tests / callers.

        Fires only for large pasted structured dumps. New callers should use
        `should_trigger_intel_pipeline`.
        """

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
            return self.heuristic_entity_extraction(raw_input)

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
            '  "other_fields": {"邮箱": [], "车牌": [], "社交账号": []},\n'
            '  "data_quality": "low/medium/high"\n'
            "}\n"
        )

        try:
            response_text = await self._run_prompt(
                node=node,
                messages=[
                    ChatMessageInput(role="system", content=prompt),
                    ChatMessageInput(role="user", content=f"【输入数据】\n{raw_input}"),
                ],
                temperature=0.1,
                max_tokens=1000,
            )
        except Exception:
            return self.heuristic_entity_extraction(raw_input)

        response_text = self._clean_llm_response(response_text)
        parsed = self._parse_json_object(response_text) or {}

        fallback = self.heuristic_entity_extraction(raw_input)
        extraction = QianduIntelExtraction(
            summary=str(parsed.get("summary") or "").strip() or fallback.summary,
            names=self._ensure_str_list(parsed.get("names")) or fallback.names,
            phones=self._ensure_str_list(parsed.get("phones")) or fallback.phones,
            id_numbers=self._ensure_str_list(parsed.get("id_numbers")) or fallback.id_numbers,
            addresses=parsed.get("addresses") if isinstance(parsed.get("addresses"), list) else fallback.addresses,
            organizations=self._ensure_str_list(parsed.get("organizations")) or fallback.organizations,
            other_fields=parsed.get("other_fields") if isinstance(parsed.get("other_fields"), dict) else fallback.other_fields,
            data_quality=str(parsed.get("data_quality") or "").strip() or fallback.data_quality,
            raw_input=raw_input,
        )
        return extraction

    async def generate_search_tasks(
        self,
        *,
        extraction: QianduIntelExtraction,
        allowed_models: list[str],
        requested_model: str | None,
    ) -> list[QianduSearchTask]:
        node = await self._select_node(requested_model=requested_model, allowed_models=allowed_models)
        if not node:
            return self.heuristic_generate_tasks(extraction)

        normalized_data = json.dumps(
            {
                "summary": extraction.summary,
                "names": extraction.names,
                "phones": extraction.phones,
                "id_numbers": extraction.id_numbers,
                "organizations": extraction.organizations,
                "addresses": extraction.addresses,
                "other_fields": extraction.other_fields,
                "raw_input": extraction.raw_input,
            },
            ensure_ascii=False,
        )

        prompt = (
            "你是一个“大陆综合 OSINT 搜索策略引擎”。目标：基于已有结构化数据，"
            "覆盖目标在大陆的 工商/司法/教育/职业/社交/微信/新闻 等维度的网络足迹。\n"
            "【关键策略 - 必须执行】\n"
            "- **别名扩展 (Alias Expansion)**：自动提取企业简称（如“北京某某公司” -> “某某公司”）、人名组合、手机号段等变体。\n"
            "- **降维打击 (Mobile First)**：优先构造适用于移动端/H5检索的关键词。\n"
            "- 必须使用大陆特定术语：如“法定代表人”、“股东情况”、“执行信息”、“失信记录”、"
            "“裁判文书”、“学历认证”、“任职”、“简历” 作为查询关键词。\n"
            "- 为 工商/司法/教育/职业/社交/微信/新闻 每个维度**至少生成一个任务**"
            "（如果与目标相关）。\n"
            "- 强制生成组合查询：[姓名 + 精准地理位置]、[姓名 + 组织]、"
            "[姓名 + 手机前3后4]。\n"
            "- 禁止生成过于笼统的查询（如只搜姓名）。\n"
            "- LinkedIn / Facebook 等海外站点在大陆重名率极高，只有 intent=profession 且明确提到"
            "海外履历时才纳入。\n"
            "【输出格式】必须是JSON：\n"
            "{\n"
            '  "tasks": [\n'
            '    {\n'
            '      "task_id": "t1",\n'
            '      "task_type": "business|judicial|education|profession|social|wechat|news",\n'
            '      "query": "姓名 + 地域 法人",\n'
            '      "goal": "",\n'
            '      "priority": 1,\n'
            '      "include_domains": ["qcc.com"],\n'
            '      "preferred_providers": ["tavily", "searxng"]\n'
            "    }\n"
            "  ]\n"
            "}\n"
        )

        try:
            response_text = await self._run_prompt(
                node=node,
                messages=[
                    ChatMessageInput(role="system", content=prompt),
                    ChatMessageInput(role="user", content=f"【可用数据】\n{normalized_data}"),
                ],
                temperature=0.2,
                max_tokens=1200,
            )
        except Exception:
            return self.heuristic_generate_tasks(extraction)

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
            task_type = str(item.get("task_type") or "entity_lookup").strip().lower()
            results.append(
                QianduSearchTask(
                    task_id=str(item.get("task_id") or f"task_{index}"),
                    task_type=task_type,
                    query=query,
                    goal=str(item.get("goal") or ""),
                    priority=int(item.get("priority") or 2),
                    include_domains=self._normalize_domains(item.get("include_domains")),
                    preferred_providers=self._normalize_providers(item.get("preferred_providers")),
                )
            )

        if not results:
            return self.heuristic_generate_tasks(extraction)

        merged = self._merge_task_lists(results, self.heuristic_generate_tasks(extraction))
        return merged[: settings.qiandu_max_search_tasks]

    async def fuse_intel_report(
        self,
        *,
        extraction: QianduIntelExtraction,
        search_results: list[QianduEvidenceChunk],
        allowed_models: list[str],
        requested_model: str | None,
    ) -> str:
        if not search_results:
            return self._heuristic_intel_report(extraction, search_results)

        node = await self._select_node(requested_model=requested_model, allowed_models=allowed_models)
        if not node:
            return self._heuristic_intel_report(extraction, search_results)

        evidence_text = "\n\n".join(
            f"[{index}] {item.title}\nURL: {item.url}\nkind={item.metadata.get('task_type', item.metadata.get('kind', ''))}\n{item.text}"
            for index, item in enumerate(search_results, start=1)
        )

        prompt = (
            "你是一个“大陆综合 OSINT 情报分析引擎”。\n"
            "任务：基于以下输入（原始结构化数据 + 外部搜索证据），"
            "生成一份结构化的中文【综合查询报告】。\n"
            "\n"
            "【输出格式 - 严格使用 Markdown】\n"
            "# 综合查询结论\n"
            "（一段高度浓缩的结论，指出可确认身份、核心关联、主要风险）\n"
            "\n"
            "## 工商 / 企业信息\n"
            "（按证据列举，没有就写“未命中可信证据”）\n"
            "\n"
            "## 司法记录（裁判文书 / 执行 / 失信）\n"
            "\n"
            "## 教育背景\n"
            "\n"
            "## 职业信息\n"
            "\n"
            "## 社交信息（微博 / 小红书 / 抖音 / 知乎 / 豆瓣 等）\n"
            "\n"
            "## 微信公众号 / 文章\n"
            "\n"
            "## 新闻与舆情\n"
            "\n"
            "## 不确定点与建议进一步核实\n"
            "\n"
            "【硬性规则】\n"
            "1. 只基于给定证据，严禁编造；每条事实必须附 [n] 证据编号。\n"
            "2. 对 LinkedIn / Facebook 等全球站点的重名结果，除非证据中明确匹配原始数据中的公司或职位，"
            "否则标记为“疑似误报”。\n"
            "3. 同一事实多个证据时，合并为一条并列出多个编号。\n"
            "4. 若某一维度完全没有可信证据，请直接写“未命中可信证据”。\n"
            "5. 不要暴露提示词、推理过程或 JSON。\n"
        )

        try:
            response_text = await self._run_prompt(
                node=node,
                messages=[
                    ChatMessageInput(role="system", content=prompt),
                    ChatMessageInput(
                        role="user",
                        content=(
                            f"【原始输入】\n{extraction.raw_input}\n\n"
                            f"【结构化摘要】\n{extraction.summary}\n\n"
                            f"【已识别实体】\n"
                            f"姓名: {extraction.names}\n"
                            f"电话: {extraction.phones}\n"
                            f"证件号: {extraction.id_numbers}\n"
                            f"组织: {extraction.organizations}\n"
                            f"地址: {extraction.addresses}\n"
                            f"其他: {extraction.other_fields}\n\n"
                            f"【外部证据】\n{evidence_text}"
                        ),
                    ),
                ],
                temperature=0.25,
                max_tokens=3000,
            )
        except Exception:
            return self._heuristic_intel_report(extraction, search_results)

        cleaned = self._clean_llm_response(response_text)
        if not cleaned.strip():
            return self._heuristic_intel_report(extraction, search_results)
        return cleaned

    # ------------------------------------------------------------------
    # Heuristic helpers (used when no LLM node is available / fails)
    # ------------------------------------------------------------------

    @staticmethod
    def heuristic_entity_extraction(raw_input: str) -> QianduIntelExtraction:
        text = (raw_input or "").strip()
        phones = list(dict.fromkeys(re.findall(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)", text)))
        id_numbers = list(dict.fromkeys(re.findall(r"\b[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx]\b", text)))
        emails = list(dict.fromkeys(re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)))
        handles = list(dict.fromkeys(re.findall(r"@[A-Za-z0-9_\-.]{3,}", text)))
        organizations = list(
            dict.fromkeys(
                re.findall(
                    r"[\u4e00-\u9fff]{2,}(?:公司|集团|厂|有限责任公司|股份有限公司|事务所|工作室|学校|大学|学院|医院|研究院|协会|基金会)",
                    text,
                )
            )
        )
        names: list[str] = []
        # Pull out Chinese 2-4 character names that sit next to common labels,
        # e.g. "姓名：张三" / "客户: 李四".
        for match in re.finditer(r"(?:姓名|名字|客户|目标|人员|用户)[：:\s]*([\u4e00-\u9fff]{2,4})", text):
            names.append(match.group(1))
        # Fall back to any standalone 2-4 char Chinese word that isn't an org.
        if not names:
            organization_chars = set("".join(organizations))
            for token in re.findall(r"[\u4e00-\u9fff]{2,4}", text):
                if token in names:
                    continue
                if any(word in token for word in ("公司", "集团", "学校", "大学", "医院", "学院")):
                    continue
                if set(token).issubset(organization_chars) and organizations:
                    continue
                names.append(token)
                if len(names) >= 4:
                    break
        names = list(dict.fromkeys(names))

        quality = "low"
        if phones or id_numbers:
            quality = "high"
        elif names or organizations or emails or handles:
            quality = "medium"

        summary_bits: list[str] = []
        if names:
            summary_bits.append(f"姓名={','.join(names[:3])}")
        if organizations:
            summary_bits.append(f"组织={','.join(organizations[:3])}")
        if phones:
            summary_bits.append(f"电话={','.join(phones[:2])}")
        if id_numbers:
            summary_bits.append(f"证件={','.join(id_numbers[:1])}")
        summary = "；".join(summary_bits) or text[:80]

        other_fields: dict[str, list[str]] = {}
        if emails:
            other_fields["邮箱"] = emails[:5]
        if handles:
            other_fields["社交账号"] = handles[:10]

        return QianduIntelExtraction(
            summary=summary,
            names=names[:6],
            phones=phones[:4],
            id_numbers=id_numbers[:2],
            addresses=[],
            organizations=organizations[:5],
            other_fields=other_fields,
            data_quality=quality,
            raw_input=text,
        )

    @staticmethod
    def heuristic_generate_tasks(extraction: QianduIntelExtraction) -> list[QianduSearchTask]:
        """Fallback task generator covering the 综合查询 dimensions."""

        targets: list[str] = []
        targets.extend(extraction.names)
        targets.extend(extraction.organizations)
        handles = extraction.other_fields.get("社交账号") if isinstance(extraction.other_fields, dict) else None
        if isinstance(handles, list):
            targets.extend([str(item).strip() for item in handles if item])
        primary = next((t for t in targets if t), "")
        if not primary:
            primary = extraction.raw_input.strip().split("\n", 1)[0][:40]
        if not primary:
            return []

        phone = extraction.phones[0] if extraction.phones else ""
        id_number = extraction.id_numbers[0] if extraction.id_numbers else ""
        org = extraction.organizations[0] if extraction.organizations else ""

        def _task(
            task_id: str,
            task_type: str,
            query: str,
            *,
            preferred_providers: list[str] | None = None,
            include_domains: list[str] | None = None,
            priority: int = 2,
        ) -> QianduSearchTask:
            return QianduSearchTask(
                task_id=task_id,
                task_type=task_type,
                query=query.strip(),
                goal="",
                priority=priority,
                include_domains=include_domains or list(QIANDU_DOMAIN_ALLOWLIST.get(task_type, [])),
                preferred_providers=preferred_providers or ["tavily", "exa", "searxng"],
            )

        tasks: list[QianduSearchTask] = []

        # 工商
        tasks.append(
            _task(
                "biz",
                "business",
                " ".join(filter(None, [primary, org, "法人 股东 企查查"])),
                priority=1,
            )
        )
        # 司法
        tasks.append(
            _task(
                "jud",
                "judicial",
                " ".join(filter(None, [primary, org, "裁判文书 判决书 执行"])),
                priority=1,
            )
        )
        # 教育
        tasks.append(
            _task(
                "edu",
                "education",
                " ".join(filter(None, [primary, org, "学历 毕业 院校"])),
            )
        )
        # 职业
        tasks.append(
            _task(
                "pro",
                "profession",
                " ".join(filter(None, [primary, org, "任职 简历 履历"])),
            )
        )
        # 社交
        tasks.append(
            _task(
                "soc",
                "social",
                " ".join(filter(None, [primary, "微博 小红书 抖音 知乎"])),
                preferred_providers=["tavily", "searxng", "snoop"],
            )
        )
        # 微信
        tasks.append(
            _task(
                "wx",
                "wechat",
                " ".join(filter(None, [primary, org, "公众号"])),
                preferred_providers=["wechat_crawler", "tavily", "searxng"],
                include_domains=["mp.weixin.qq.com"],
            )
        )
        # 新闻
        tasks.append(
            _task(
                "news",
                "news",
                " ".join(filter(None, [primary, org, "新闻 报道"])),
            )
        )

        # Strong identifiers: add targeted follow-up tasks.
        if phone:
            tasks.append(
                _task(
                    "phone",
                    "general",
                    f"{primary} {phone}",
                    priority=1,
                    include_domains=[],
                )
            )
        if id_number:
            tasks.append(
                _task(
                    "id",
                    "general",
                    f"{primary} {id_number[:6]}",
                    priority=1,
                    include_domains=[],
                )
            )

        return tasks[: settings.qiandu_max_search_tasks]

    @staticmethod
    def _merge_task_lists(
        primary: list[QianduSearchTask],
        secondary: list[QianduSearchTask],
    ) -> list[QianduSearchTask]:
        seen_types = {task.task_type for task in primary}
        merged = list(primary)
        for task in secondary:
            if task.task_type in seen_types:
                continue
            merged.append(task)
            seen_types.add(task.task_type)
        return merged

    @staticmethod
    def _heuristic_intel_report(
        extraction: QianduIntelExtraction,
        search_results: list[QianduEvidenceChunk],
    ) -> str:
        from app.services.qiandu_search.dimensions import DIMENSION_LABELS

        buckets: dict[str, list[tuple[int, QianduEvidenceChunk]]] = {
            dim: [] for dim in INTEL_DIMENSIONS
        }
        buckets["other"] = []
        label_map = dict(DIMENSION_LABELS)
        for index, chunk in enumerate(search_results, start=1):
            raw = str(chunk.metadata.get("task_type") or "").lower()
            dim = canonical_dimension(raw)
            if dim == "general" or dim not in buckets:
                dim = "other"
            buckets[dim].append((index, chunk))

        summary = (extraction.summary or extraction.raw_input.strip())[:140]
        lines: list[str] = [
            "# 综合查询结论",
            summary or "基于输入尚未识别到明确实体。",
            "",
        ]

        for key in list(INTEL_DIMENSIONS) + ["other"]:
            items = buckets.get(key) or []
            lines.append(f"## {label_map[key]}")
            if not items:
                lines.append("未命中可信证据。")
            else:
                for index, chunk in items[:5]:
                    preview = chunk.text.strip().replace("\n", " ")
                    if len(preview) > 240:
                        preview = preview[:237] + "..."
                    lines.append(f"- [{index}] {chunk.title}：{preview}")
                    lines.append(f"  - {chunk.url}")
            lines.append("")

        lines.append("## 不确定点与建议进一步核实")
        lines.append(
            "本报告由启发式合成引擎生成，未经过大模型交叉验证。"
            "请结合来源链接核对每条线索，重点关注姓名相近但单位不同的潜在误报。"
        )
        return "\n".join(lines).strip()

    def _clean_llm_response(self, text: str) -> str:
        if not text:
            return ""
        # Remove common thought/reasoning tags
        text = re.sub(r"<(?:thought|reasoning|thinking|details)>.*?</(?:thought|reasoning|thinking|details)>", "", text, flags=re.DOTALL | re.IGNORECASE)
        # Remove markers like "Thought:", "Reasoning:", etc. at the start of blocks
        text = re.sub(r"^(?:Thought|Reasoning|Thinking|Analysis):\s*.*?(?=\n\n|\n[#\d])", "", text, flags=re.DOTALL | re.IGNORECASE | re.MULTILINE)
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

        if any(keyword in normalized for keyword in _DIMENSION_KEYWORDS["wechat"]):
            intent = "wechat"
            preferred_providers = ["wechat_crawler", "tavily", "searxng", "exa"]
            include_domains = list(QIANDU_DOMAIN_ALLOWLIST["wechat"])
            queries.extend([f"{normalized} 公众号", f"{normalized} site:mp.weixin.qq.com"])
        elif any(keyword in normalized for keyword in _DIMENSION_KEYWORDS["judicial"]):
            intent = "judicial"
            preferred_providers = ["tavily", "exa", "searxng"]
            include_domains = list(QIANDU_DOMAIN_ALLOWLIST["judicial"])
            queries.extend([f"{normalized} 裁判文书", f"{normalized} 法院 判决书"])
        elif any(keyword in normalized for keyword in _DIMENSION_KEYWORDS["business"]):
            intent = "business"
            preferred_providers = ["tavily", "exa", "searxng"]
            include_domains = list(QIANDU_DOMAIN_ALLOWLIST["business"])
            queries.extend([f"{normalized} 企查查", f"{normalized} 法定代表人"])
        elif any(keyword in normalized for keyword in _DIMENSION_KEYWORDS["education"]):
            intent = "education"
            preferred_providers = ["tavily", "exa", "searxng"]
            include_domains = list(QIANDU_DOMAIN_ALLOWLIST["education"])
            queries.extend([f"{normalized} 学历", f"{normalized} 毕业院校"])
        elif any(keyword in normalized for keyword in _DIMENSION_KEYWORDS["profession"]):
            intent = "profession"
            preferred_providers = ["tavily", "exa", "searxng"]
            include_domains = list(QIANDU_DOMAIN_ALLOWLIST["profession"])
            queries.extend([f"{normalized} 任职", f"{normalized} 职业 履历"])
        elif any(keyword in normalized for keyword in _DIMENSION_KEYWORDS["social"]) or re.search(r"[@_A-Za-z0-9]{4,}", normalized):
            intent = "social"
            preferred_providers = ["snoop", "tavily", "searxng", "exa"]
            include_domains = list(QIANDU_DOMAIN_ALLOWLIST["social"])
            queries.extend([f"{normalized} 微博", f"{normalized} 小红书"])

        news_keywords = ("最新", "今天", "最近", "新闻", "近况", "最新进展", "latest", "today", "news", "recent")
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
