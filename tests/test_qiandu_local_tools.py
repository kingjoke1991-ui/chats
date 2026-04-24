from pathlib import Path

from app.services.qiandu_search import local_tools
from app.services.qiandu_search.local_tools import _normalize_search_results, _parse_snoop_csv


def test_parse_snoop_csv_extracts_profile_rows(tmp_path: Path) -> None:
    csv_path = tmp_path / "demo.csv"
    csv_path.write_text(
        "Resource,Geo,Url,Url_username,Status,Http_code,Deceleration/s,Response/s,Time/s,Session/kB\n"
        "weibo,CN,https://weibo.com,https://weibo.com/example,found,200,0,0,0,1\n"
        "bad,CN,https://bad.example,********,not found,404,0,0,0,0\n",
        encoding="utf-8-sig",
    )

    parsed = _parse_snoop_csv(csv_path)

    assert parsed == [
        {
            "title": "weibo",
            "url": "https://weibo.com/example",
            "profile": "https://weibo.com/example",
            "snippet": "geo=CN status=found http=200 source=https://weibo.com",
            "score": 1.0,
        }
    ]


def test_normalize_search_results_filters_invalid_urls() -> None:
    raw_results = [
        {"title": "A", "url": "https://mp.weixin.qq.com/s/abc", "content": "first", "score": 0.9},
        {"title": "B", "url": "javascript:alert(1)", "content": "bad"},
    ]

    parsed = _normalize_search_results(raw_results, provider="wechat_crawler")

    assert parsed == [
        {
            "title": "A",
            "url": "https://mp.weixin.qq.com/s/abc",
            "snippet": "first",
            "score": 0.9,
            "provider": "wechat_crawler",
        }
    ]


def test_fallback_social_search_returns_warning(monkeypatch) -> None:
    monkeypatch.setattr(
        local_tools,
        "_search_with_tavily",
        lambda **kwargs: [
            {
                "title": "weibo result",
                "url": "https://weibo.com/example",
                "snippet": "hit",
                "score": 1.0,
                "provider": kwargs["provider"],
            }
        ],
    )

    payload = local_tools._fallback_social_search("jack", warning="demo mode")

    assert payload["warning"] == "demo mode"
    assert payload["results"][0]["provider"] == "snoop_fallback"
