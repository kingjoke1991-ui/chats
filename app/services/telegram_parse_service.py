from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.constants import PROVIDER_TYPE_OPENAI_COMPAT
from app.core.exceptions import AppException
from app.providers.openai_compat import OpenAICompatProvider
from app.repos.model_node_repo import ModelNodeRepo
from app.schemas.chat import ChatCompletionRequest, ChatMessageInput

TELEGRAM_PARSE_SYSTEM_PROMPT = """
You are a data parser.
Extract structured data from noisy text and return JSON only.
Rules:
1. Return exactly one JSON object, with no markdown and no explanation.
2. Use snake_case field names.
3. Preserve important identifiers, dates, phone numbers, account numbers, amounts, statuses, and notes when present.
4. If a field is uncertain, omit it or place it under extra.
5. Always include raw_text with the original text.
""".strip()

TELEGRAM_AUDIT_SYSTEM_PROMPT = """
任务目标：请对提供的文档进行数据清洗与结构化提取。以“xxx”为唯一核心实体，识别并聚合出所有互不相同的个体，并对每个个体的相关资料进行去重聚合。

清洗逻辑指南：
	1.	身份判定（唯一性）：
		* 优先通过身份证号判定是否为同一人。
		* 若无身份证号，通过手机号进行关联。
		* 若手机号和证件号均无交集，但户籍地址、就读学校或工作单位高度重合，可视为同一人。
	2.	资料聚合：
		将同一人的手机号（可能多个）、邮箱、地址、账号密码、教育经历、家庭关系等所有碎片信息合并。
	3.	内容去重：
		相同的信息（如重复的地址或手机号）仅保留一条。

输出格式要求（Markdown表格或列表）：
[个体编号]：xxx- [特征简述，如：江苏镇江 76年/某大学学生]
•	基本信息： 身份证号、出生日期、性别、民族等等。
•	联系方式： 手机号（去重列表）、电子邮箱等等。
•	地理信息： 户籍地、常住地址、快递收货地址等等。
•	教育/工作： 就读学校、学号、单位名称等等。
•	网络账号： 平台名称、账号/昵称、密码（MD5或明文）等等。
•	关联关系： 配偶姓名、同户人员、户主关系等等

约束限制：
1. 仅输出数据清洗提取后的 Markdown 结果，严禁包含任何前言、导语、处理流程说明或结束语。
2. 直接从第一个个体开始输出，不要复述任务目标或清洗逻辑。
3. 如果文档内容较多，请务必完整输出所有识别到的个体，不得截断。
""".strip()

ID_PATTERN = re.compile(r"(?<!\d)(\d{17}[\dXx])(?!\d)")
PHONE_PATTERN = re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)")
NAME_PATTERNS = [
    re.compile(r"(?:姓名|名字|收件人|联系人|户主|本人)[:：\s]*([^\s,，;；|]{2,8})"),
]
ADDRESS_PATTERNS = [
    re.compile(r"(?:收货地址|收件地址|家庭住址|住址|地址)[:：\s]*([^\n]{6,120})"),
]
HOMETOWN_PATTERNS = [
    re.compile(r"(?:籍贯|出生地|户籍地|户籍地址|老家)[:：\s]*([^\n]{2,80})"),
]
GENDER_PATTERNS = [
    re.compile(r"(?:性别)[:：\s]*(男|女)"),
]
AGE_PATTERNS = [
    re.compile(r"(?:年龄)[:：\s]*(\d{1,3})"),
]
BIRTH_PATTERNS = [
    re.compile(r"(?:生日|出生日期|出生)[:：\s]*(\d{4}[./-]\d{1,2}[./-]\d{1,2})"),
]
ZODIAC_PATTERNS = [
    re.compile(r"(?:生肖)[:：\s]*([鼠牛虎兔龙蛇马羊猴鸡狗猪])"),
]
CONSTELLATION_PATTERNS = [
    re.compile(r"(?:星座)[:：\s]*([白羊金牛双子巨蟹狮子处女天秤天蝎射手摩羯水瓶双鱼]{2,4})"),
]

PROVINCE_BY_CODE = {
    "11": "北京",
    "12": "天津",
    "13": "河北",
    "14": "山西",
    "15": "内蒙古",
    "21": "辽宁",
    "22": "吉林",
    "23": "黑龙江",
    "31": "上海",
    "32": "江苏",
    "33": "浙江",
    "34": "安徽",
    "35": "福建",
    "36": "江西",
    "37": "山东",
    "41": "河南",
    "42": "湖北",
    "43": "湖南",
    "44": "广东",
    "45": "广西",
    "46": "海南",
    "50": "重庆",
    "51": "四川",
    "52": "贵州",
    "53": "云南",
    "54": "西藏",
    "61": "陕西",
    "62": "甘肃",
    "63": "青海",
    "64": "宁夏",
    "65": "新疆",
    "71": "台湾",
    "81": "香港",
    "82": "澳门",
}

ZODIAC_ANIMALS = ["猴", "鸡", "狗", "猪", "鼠", "牛", "虎", "兔", "龙", "蛇", "马", "羊"]
CONSTELLATIONS = [
    ((1, 20), "摩羯"),
    ((2, 19), "水瓶"),
    ((3, 21), "双鱼"),
    ((4, 20), "白羊"),
    ((5, 21), "金牛"),
    ((6, 22), "双子"),
    ((7, 23), "巨蟹"),
    ((8, 23), "狮子"),
    ((9, 23), "处女"),
    ((10, 24), "天秤"),
    ((11, 23), "天蝎"),
    ((12, 22), "射手"),
    ((12, 32), "摩羯"),
]


@dataclass(slots=True)
class TelegramParsedResult:
    parsed_json: dict[str, Any]
    raw_model_output: str
    parser_model: str
    parser_provider: str
    parser_node_id: str


@dataclass(slots=True)
class TelegramAuditedResult:
    content: str
    raw_model_output: str
    parser_model: str
    parser_provider: str
    parser_node_id: str


class TelegramParseService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.model_nodes = ModelNodeRepo(session)
        self.providers = {
            PROVIDER_TYPE_OPENAI_COMPAT: OpenAICompatProvider(),
        }

    async def parse_raw_reply(
        self,
        *,
        raw_text: str,
        allowed_models: list[str],
        requested_model: str | None,
    ) -> TelegramParsedResult:
        node, response_model = await self._select_node(requested_model=requested_model, allowed_models=allowed_models)
        if not node:
            raise AppException(503, "MODEL_ROUTE_NOT_FOUND", "no active model node is currently available")

        provider = self.providers.get(node.provider_type)
        if not provider:
            raise AppException(500, "PROVIDER_NOT_IMPLEMENTED", f"provider `{node.provider_type}` is not implemented")

        payload = ChatCompletionRequest(
            model=response_model,
            stream=False,
            temperature=0,
            max_tokens=1200,
            messages=[
                ChatMessageInput(role="system", content=TELEGRAM_PARSE_SYSTEM_PROMPT),
                ChatMessageInput(role="user", content=f"Extract JSON from the following text:\n\n{raw_text}"),
            ],
        )
        result = await provider.create_chat_completion(node=node, payload=payload)
        parsed_json = self._coerce_json(result.content, raw_text)

        return TelegramParsedResult(
            parsed_json=parsed_json,
            raw_model_output=result.content,
            parser_model=response_model,
            parser_provider=node.provider_code,
            parser_node_id=node.id,
        )

    async def audit_identity_text(
        self,
        *,
        query_text: str | None = None,
        raw_text: str,
        allowed_models: list[str],
        requested_model: str | None,
    ) -> TelegramAuditedResult:
        normalized = self._normalize_text(raw_text)
        node, response_model = await self._select_audit_node(
            requested_model=requested_model,
            allowed_models=allowed_models,
        )

        if node:
            provider = self.providers.get(node.provider_type)
            if provider:
                model_candidates = self._audit_model_candidates(node.provider_code, response_model)
                last_error: Exception | None = None
                for model_name in model_candidates:
                    try:
                        system_prompt = TELEGRAM_AUDIT_SYSTEM_PROMPT
                        if query_text:
                            system_prompt = system_prompt.replace("“xxx”", f"“{query_text}”")

                        payload = ChatCompletionRequest(
                            model=model_name,
                            stream=False,
                            temperature=0,
                            max_tokens=8192,
                            messages=[
                                ChatMessageInput(role="system", content=system_prompt),
                                ChatMessageInput(
                                    role="user",
                                    content=f"请直接输出对以下文本的清洗结果，严禁输出任何多余解释：\n\n{normalized}",
                                ),
                            ],
                        )
                        result = await provider.create_chat_completion(node=node, payload=payload)
                        content = str(result.content or "").strip()
                        if content:
                            return TelegramAuditedResult(
                                content=content,
                                raw_model_output=result.content,
                                parser_model=model_name,
                                parser_provider=node.provider_code,
                                parser_node_id=node.id,
                            )
                    except Exception as exc:
                        last_error = exc
                        if not self._should_try_next_audit_model(exc):
                            break

                fallback = self.build_local_identity_audit(
                    normalized,
                    error_detail=str(last_error) if last_error else "gemini audit failed",
                )
                return TelegramAuditedResult(
                    content=fallback,
                    raw_model_output=str(last_error) if last_error else "",
                    parser_model="local-fallback",
                    parser_provider="local-fallback",
                    parser_node_id="telegram-audit-fallback",
                )

        fallback = self.build_local_identity_audit(normalized, error_detail="no audit node available")
        return TelegramAuditedResult(
            content=fallback,
            raw_model_output="",
            parser_model="local-fallback",
            parser_provider="local-fallback",
            parser_node_id="telegram-audit-fallback",
        )

    async def _select_audit_node(self, *, requested_model: str | None, allowed_models: list[str]):
        preferred_codes = [
            settings.telegram_audit_node_code,
            settings.llm_fallback_node_code,
            settings.resolved_web_search_llm_node_code,
            settings.resolved_qiandu_llm_node_code,
        ]
        seen: set[str] = set()
        for code in preferred_codes:
            compact = (code or "").strip()
            if not compact or compact in seen:
                continue
            seen.add(compact)
            node = await self.model_nodes.get_by_code(compact)
            if node and node.enabled:
                return node, node.model_name
        return await self._select_node(requested_model=requested_model, allowed_models=allowed_models)

    @staticmethod
    def _should_try_next_audit_model(exc: Exception) -> bool:
        if isinstance(exc, AppException):
            detail = (exc.detail or "").lower()
            return "not found" in detail or "unsupported" in detail or exc.error_code in {
                "UPSTREAM_ERROR",
                "MODEL_UNAVAILABLE",
            }
        return False

    @staticmethod
    def _audit_model_candidates(provider_code: str, primary_model: str) -> list[str]:
        candidates = [primary_model]
        if provider_code == settings.telegram_audit_provider_code:
            candidates.extend(settings.telegram_audit_gemini_fallback_models)
        deduped: list[str] = []
        seen: set[str] = set()
        for item in candidates:
            compact = (item or "").strip()
            if compact and compact not in seen:
                seen.add(compact)
                deduped.append(compact)
        return deduped

    async def _select_node(self, requested_model: str | None, allowed_models: list[str]):
        if requested_model:
            node = await self.model_nodes.get_routable_for_model(requested_model)
            if node:
                return node, requested_model
            if requested_model in {settings.llm_default_model, settings.llm_default_model_name}:
                fallback_node = await self.model_nodes.get_best_available_for_models(allowed_models)
                if fallback_node:
                    return fallback_node, fallback_node.model_name
            return None, requested_model

        node = await self.model_nodes.get_best_available_for_models(allowed_models)
        if node:
            return node, node.model_name
        return None, settings.llm_default_model

    @classmethod
    def build_local_identity_audit(cls, raw_text: str, error_detail: str | None = None) -> str:
        text = cls._normalize_text(raw_text)
        identities = cls._extract_identities(text)
        if not identities:
            return cls._build_unknown_markdown(text, error_detail)
        return cls._render_identity_markdown(identities, error_detail)

    @classmethod
    def _extract_identities(cls, text: str) -> list[dict[str, Any]]:
        matches = list(ID_PATTERN.finditer(text))
        contexts_by_id: dict[str, list[str]] = {}
        for matched in matches:
            id_number = matched.group(1).upper()
            snippet = text[max(0, matched.start() - 500) : min(len(text), matched.end() + 900)]
            contexts_by_id.setdefault(id_number, []).append(snippet)

        if not contexts_by_id:
            phones = sorted(set(PHONE_PATTERN.findall(text)))
            if not phones:
                return []
            return [
                cls._build_identity_record(
                    id_number=None,
                    context=text[:12000],
                    fallback_phones=phones,
                )
            ]

        identities: list[dict[str, Any]] = []
        for id_number, snippets in contexts_by_id.items():
            deduped_context = "\n".join(dict.fromkeys(snippets))
            identities.append(cls._build_identity_record(id_number=id_number, context=deduped_context))
        identities.sort(key=lambda item: item.get("name") or item.get("id_number") or "")
        return identities

    @classmethod
    def _build_identity_record(
        cls,
        *,
        id_number: str | None,
        context: str,
        fallback_phones: list[str] | None = None,
    ) -> dict[str, Any]:
        name = cls._search_first(context, NAME_PATTERNS)
        hometown = cls._search_first(context, HOMETOWN_PATTERNS)
        addresses = cls._extract_addresses(context)
        phones = cls._extract_phones(context, fallback_phones=fallback_phones or [])

        id_birth = cls._birth_from_id(id_number) if id_number else None
        id_gender = cls._gender_from_id(id_number) if id_number else None
        id_province = cls._province_from_id(id_number) if id_number else None
        id_age = cls._age_from_birth(id_birth) if id_birth else None
        id_zodiac = cls._zodiac_from_birth(id_birth) if id_birth else None
        id_constellation = cls._constellation_from_birth(id_birth) if id_birth else None

        stated_birth = cls._parse_date(cls._search_first(context, BIRTH_PATTERNS))
        stated_age = cls._search_int(context, AGE_PATTERNS)
        stated_gender = cls._search_first(context, GENDER_PATTERNS)
        stated_zodiac = cls._search_first(context, ZODIAC_PATTERNS)
        stated_constellation = cls._search_first(context, CONSTELLATION_PATTERNS)

        anomaly_notes: list[str] = []
        if id_birth and stated_birth and id_birth != stated_birth:
            anomaly_notes.append(
                f"身份证生日 {id_birth.isoformat()} 与文本生日 {stated_birth.isoformat()} 不一致"
            )
        if id_age is not None and stated_age is not None and abs(id_age - stated_age) > 1:
            anomaly_notes.append(f"身份证推算年龄 {id_age} 与文本年龄 {stated_age} 不一致")
        if id_gender and stated_gender and id_gender != stated_gender:
            anomaly_notes.append(f"身份证推断性别 {id_gender} 与文本性别 {stated_gender} 不一致")
        if id_zodiac and stated_zodiac and id_zodiac != stated_zodiac:
            anomaly_notes.append(f"身份证推算生肖 {id_zodiac} 与文本生肖 {stated_zodiac} 不一致")
        if id_constellation and stated_constellation and id_constellation != stated_constellation:
            anomaly_notes.append(f"身份证推算星座 {id_constellation} 与文本星座 {stated_constellation} 不一致")
        if id_province and hometown and id_province not in hometown:
            anomaly_notes.append(f"身份证地区码推断省份 {id_province} 与文本籍贯/出生地 {hometown} 不一致")

        birth_value = stated_birth or id_birth
        age_value = stated_age if stated_age is not None else id_age
        gender_value = stated_gender or id_gender
        zodiac_value = stated_zodiac or id_zodiac
        constellation_value = stated_constellation or id_constellation

        return {
            "name": name or "待核验人员",
            "id_number": id_number,
            "birth_date": birth_value.isoformat() if birth_value else "未识别",
            "age": str(age_value) if age_value is not None else "未识别",
            "gender": gender_value or "未识别",
            "zodiac": zodiac_value or "未识别",
            "constellation": constellation_value or "未识别",
            "hometown": hometown or (id_province or "未识别"),
            "phones": phones or ["未识别"],
            "addresses": addresses or ["未识别"],
            "anomaly_notes": anomaly_notes,
        }

    @classmethod
    def _render_identity_markdown(cls, identities: list[dict[str, Any]], error_detail: str | None) -> str:
        sections: list[str] = []
        for index, identity in enumerate(identities, start=1):
            title_name = identity.get("name") or f"人员 {index}"
            id_tail = ""
            id_number = identity.get("id_number")
            if isinstance(id_number, str) and id_number:
                id_tail = f"（身份证尾号 {id_number[-4:]}）"

            anomaly_notes = list(identity.get("anomaly_notes") or [])
            if error_detail and index == 1:
                anomaly_notes.append("模型清洗失败，当前结果由本地规则清洗生成")

            sections.append(f"## 人员 {index}：{title_name}{id_tail}")
            sections.append("| 字段 | 值 |")
            sections.append("| --- | --- |")
            sections.append(f"| 姓名 | {cls._md(identity.get('name'))} |")
            sections.append(f"| 身份证 | {cls._md(identity.get('id_number') or '未识别')} |")
            sections.append(f"| 出生日期 | {cls._md(identity.get('birth_date') or '未识别')} |")
            sections.append(f"| 年龄 | {cls._md(identity.get('age') or '未识别')} |")
            sections.append(f"| 性别 | {cls._md(identity.get('gender') or '未识别')} |")
            sections.append(f"| 生肖 | {cls._md(identity.get('zodiac') or '未识别')} |")
            sections.append(f"| 星座 | {cls._md(identity.get('constellation') or '未识别')} |")
            sections.append(f"| 籍贯/出生地 | {cls._md(identity.get('hometown') or '未识别')} |")
            sections.append(f"| 手机号 | {cls._md('；'.join(identity.get('phones') or ['未识别']))} |")
            sections.append(f"| 收货地址 | {cls._md('；'.join(identity.get('addresses') or ['未识别']))} |")
            sections.append(f"| 异常备注 | {cls._md('；'.join(anomaly_notes) if anomaly_notes else '无明显异常')} |")
            sections.append("")
        return "\n".join(sections).strip()

    @classmethod
    def _build_unknown_markdown(cls, text: str, error_detail: str | None) -> str:
        phones = sorted(set(PHONE_PATTERN.findall(text))) or ["未识别"]
        addresses = cls._extract_addresses(text) or ["未识别"]
        notes = ["未识别到身份证号，无法按主键完成精确归并"]
        if error_detail:
            notes.append("模型清洗失败，当前结果由本地规则清洗生成")
        return "\n".join(
            [
                "## 人员 1：待核验人员",
                "| 字段 | 值 |",
                "| --- | --- |",
                "| 姓名 | 待核验人员 |",
                "| 身份证 | 未识别 |",
                "| 出生日期 | 未识别 |",
                "| 年龄 | 未识别 |",
                "| 性别 | 未识别 |",
                "| 生肖 | 未识别 |",
                "| 星座 | 未识别 |",
                "| 籍贯/出生地 | 未识别 |",
                f"| 手机号 | {cls._md('；'.join(phones))} |",
                f"| 收货地址 | {cls._md('；'.join(addresses))} |",
                f"| 异常备注 | {cls._md('；'.join(notes))} |",
            ]
        )

    @staticmethod
    def _normalize_text(raw_text: str) -> str:
        text = str(raw_text or "").replace("\r\n", "\n").replace("\r", "\n")
        text = text.replace("\x00", "")
        return text.strip()

    @staticmethod
    def _search_first(text: str, patterns: list[re.Pattern[str]]) -> str | None:
        for pattern in patterns:
            matched = pattern.search(text)
            if matched:
                value = matched.group(1).strip(" \t|;；,，")
                if value:
                    return value
        return None

    @staticmethod
    def _search_int(text: str, patterns: list[re.Pattern[str]]) -> int | None:
        value = TelegramParseService._search_first(text, patterns)
        if not value:
            return None
        try:
            return int(value)
        except ValueError:
            return None

    @staticmethod
    def _extract_addresses(text: str) -> list[str]:
        items: list[str] = []
        for pattern in ADDRESS_PATTERNS:
            for matched in pattern.findall(text):
                compact = str(matched).strip(" \t|;；,，")
                if compact and compact not in items:
                    items.append(compact)
        return items[:8]

    @staticmethod
    def _extract_phones(text: str, fallback_phones: list[str]) -> list[str]:
        values: list[str] = []
        for number in fallback_phones + PHONE_PATTERN.findall(text):
            compact = str(number).strip()
            if not compact or compact in values:
                continue
            location_note = None
            for line in text.splitlines():
                if compact not in line:
                    continue
                location_match = re.search(r"(?:归属地|属地|地区|运营商)[:：\s]*([^\s,，;；|]{2,24})", line)
                if location_match:
                    location_note = location_match.group(1).strip()
                    break
            values.append(f"{compact}（{location_note}）" if location_note else compact)
        return values[:12]

    @staticmethod
    def _birth_from_id(id_number: str | None) -> date | None:
        if not id_number or len(id_number) != 18:
            return None
        try:
            return datetime.strptime(id_number[6:14], "%Y%m%d").date()
        except ValueError:
            return None

    @staticmethod
    def _province_from_id(id_number: str | None) -> str | None:
        if not id_number or len(id_number) < 2:
            return None
        return PROVINCE_BY_CODE.get(id_number[:2])

    @staticmethod
    def _gender_from_id(id_number: str | None) -> str | None:
        if not id_number or len(id_number) != 18 or not id_number[16].isdigit():
            return None
        return "男" if int(id_number[16]) % 2 else "女"

    @staticmethod
    def _parse_date(value: str | None) -> date | None:
        if not value:
            return None
        normalized = value.replace(".", "-").replace("/", "-")
        try:
            return datetime.strptime(normalized, "%Y-%m-%d").date()
        except ValueError:
            return None

    @staticmethod
    def _age_from_birth(birth_date: date | None) -> int | None:
        if not birth_date:
            return None
        today = date.today()
        return today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))

    @staticmethod
    def _zodiac_from_birth(birth_date: date | None) -> str | None:
        if not birth_date:
            return None
        return ZODIAC_ANIMALS[birth_date.year % 12]

    @staticmethod
    def _constellation_from_birth(birth_date: date | None) -> str | None:
        if not birth_date:
            return None
        month_day = (birth_date.month, birth_date.day)
        for boundary, name in CONSTELLATIONS:
            if month_day < boundary:
                return name
        return "摩羯"

    @staticmethod
    def _md(value: Any) -> str:
        compact = str(value or "").replace("\n", "<br>")
        return compact.replace("|", "\\|")

    @classmethod
    def _coerce_json(cls, model_output: str, raw_text: str) -> dict[str, Any]:
        for candidate in cls._candidate_json_strings(model_output):
            try:
                parsed = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                parsed.setdefault("raw_text", raw_text)
                return parsed

        return {
            "raw_text": raw_text,
            "unparsed_model_output": model_output.strip(),
            "parse_error": "model did not return valid JSON",
        }

    @staticmethod
    def _candidate_json_strings(model_output: str) -> list[str]:
        content = model_output.strip()
        candidates = [content]

        fenced_blocks = re.findall(r"```(?:json)?\s*(.*?)```", content, flags=re.DOTALL | re.IGNORECASE)
        candidates.extend(block.strip() for block in fenced_blocks if block.strip())

        object_match = re.search(r"\{.*\}", content, flags=re.DOTALL)
        if object_match:
            candidates.append(object_match.group(0).strip())

        array_match = re.search(r"\[.*\]", content, flags=re.DOTALL)
        if array_match:
            candidates.append(array_match.group(0).strip())

        deduped: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            if candidate and candidate not in seen:
                seen.add(candidate)
                deduped.append(candidate)
        return deduped
