"""Single source of truth for `#千度` intent / dimension vocabulary.

Historically the same constants lived in three places (`service.py`,
`llm.py`, and again inside `_heuristic_intel_report`). Keeping them in one
module avoids drift between the LLM prompt schema, the heuristic
fallbacks, the scoring layer, and the fusion report sections.
"""

from __future__ import annotations

# Canonical output dimensions surfaced in the 综合查询 report.
INTEL_DIMENSIONS: tuple[str, ...] = (
    "business",
    "judicial",
    "education",
    "profession",
    "social",
    "wechat",
    "news",
)


# Human-readable section labels for each dimension (used by the heuristic
# fallback report, and available for any UI layer that wants consistent
# copy).
DIMENSION_LABELS: dict[str, str] = {
    "business": "工商 / 企业信息",
    "judicial": "司法记录（裁判文书 / 执行 / 失信）",
    "education": "教育背景",
    "profession": "职业信息",
    "social": "社交信息",
    "wechat": "微信公众号 / 文章",
    "news": "新闻与舆情",
    "other": "其他线索",
}


# All valid LLM-emitted `intent` / `task_type` values. Includes canonical
# dimensions plus legacy aliases still honoured for backwards compatibility.
INTENT_CHOICES: set[str] = {
    "general",
    "person",
    "social_id",
    "legal_entity",  # alias of business
    "company",       # alias of business
    *INTEL_DIMENSIONS,
}


# Map LLM-emitted intents / task types onto the canonical dimension set.
# Anything missing from this map and not already canonical falls back to
# "general" (handled at the call site).
INTENT_TO_DIMENSION: dict[str, str] = {
    # business aliases
    "business": "business",
    "legal_entity": "business",
    "company": "business",
    "enterprise": "business",
    "corp": "business",
    # judicial aliases
    "judicial": "judicial",
    "court": "judicial",
    "legal": "judicial",
    "wenshu": "judicial",
    "judgement": "judicial",
    "lawsuit": "judicial",
    # education aliases
    "education": "education",
    "edu": "education",
    "school": "education",
    "university": "education",
    # profession aliases
    "profession": "profession",
    "job": "profession",
    "career": "profession",
    "employment": "profession",
    "linkedin": "profession",
    # social aliases
    "social": "social",
    "social_id": "social",
    "handle": "social",
    "weibo": "social",
    "xiaohongshu": "social",
    "douyin": "social",
    "douban": "social",
    "zhihu": "social",
    "person": "social",
    # wechat aliases
    "wechat": "wechat",
    "wechat_public": "wechat",
    # news aliases
    "news": "news",
    "press": "news",
    "media": "news",
}


# Domain allowlists per canonical dimension. Used by the scoring layer to
# boost on-topic sources and by the heuristic planner to pick `include_domains`.
DOMAIN_ALLOWLIST: dict[str, list[str]] = {
    "business": [
        "qcc.com",
        "aiqicha.baidu.com",
        "tianyancha.com",
        "qixin.com",
        "qyjia.com",
        "qianzhan.com",
    ],
    "judicial": [
        "wenshu.court.gov.cn",
        "zxgk.court.gov.cn",
        "court.gov.cn",
        "zgcpws.com",
        "judicourt.com",
        "12309.gov.cn",
        "shixin.court.gov.cn",
    ],
    "education": [
        "xuexin.com",
        "chsi.com.cn",
        "xlcx.chsi.com.cn",
        "edu.cn",
        "moe.gov.cn",
        "cnki.net",
        "wanfangdata.com.cn",
        "hanspub.org",
    ],
    "profession": [
        "linkedin.com",
        "maimai.cn",
        "zhipin.com",
        "liepin.com",
        "zhaopin.com",
        "51job.com",
        "lagou.com",
    ],
    "social": [
        "weibo.com",
        "xiaohongshu.com",
        "douyin.com",
        "bilibili.com",
        "zhihu.com",
        "douban.com",
        "jianshu.com",
        "csdn.net",
    ],
    "wechat": ["mp.weixin.qq.com"],
    "news": [
        "people.com.cn",
        "xinhuanet.com",
        "sina.com.cn",
        "sohu.com",
        "163.com",
        "thepaper.cn",
        "qq.com",
        "ifeng.com",
        "thecover.cn",
    ],
}


# Keywords that hint at each dimension in free-form Chinese input. Used by
# both the heuristic plan builder and the signal-based intel pipeline
# router.
DIMENSION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "business": (
        "法人",
        "股东",
        "注册资本",
        "统一社会信用代码",
        "公司",
        "企业",
        "工商",
        "企查",
        "企查查",
        "天眼查",
        "爱企查",
    ),
    "judicial": (
        "裁判",
        "文书",
        "判决",
        "判决书",
        "法院",
        "执行",
        "失信",
        "被执行人",
        "诉讼",
        "立案",
        "涉诉",
        "老赖",
    ),
    "education": (
        "学历",
        "学籍",
        "毕业",
        "院校",
        "本科",
        "硕士",
        "博士",
        "大学",
        "学校",
        "学信",
        "学位",
        "教育背景",
    ),
    "profession": (
        "任职",
        "职业",
        "职位",
        "工作",
        "履历",
        "简历",
        "从业",
        "linkedin",
        "脉脉",
        "boss",
        "招聘",
    ),
    "social": (
        "微博",
        "小红书",
        "抖音",
        "快手",
        "b站",
        "bilibili",
        "知乎",
        "豆瓣",
        "账号",
        "uid",
        "id",
        "@",
    ),
    "wechat": ("公众号", "微信", "公号", "wechat", "mp.weixin"),
    "news": ("新闻", "舆情", "报道", "媒体", "新闻稿"),
}


def canonical_dimension(raw: str | None) -> str:
    """Normalise an LLM-emitted intent / task_type to a canonical
    dimension name, falling back to ``"general"`` for unknown values."""

    if not raw:
        return "general"
    key = raw.strip().lower()
    mapped = INTENT_TO_DIMENSION.get(key, key)
    if mapped in INTEL_DIMENSIONS:
        return mapped
    return "general"
