from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any


@dataclass(slots=True)
class SearchPlan:
    query: str
    queries: list[str]
    topic: str = "general"
    time_range: str | None = None
    include_domains: list[str] = field(default_factory=list)
    exclude_domains: list[str] = field(default_factory=list)
    search_depth: str = "advanced"

    def with_query(self, query: str) -> "SearchPlan":
        return replace(self, query=query)


@dataclass(slots=True)
class SearchResult:
    title: str
    url: str
    snippet: str
    score: float
    provider: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ExtractedDocument:
    title: str
    url: str
    content: str
    provider: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class EvidenceChunk:
    title: str
    url: str
    text: str
    provider: str
    rank_score: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class WebSearchCommandResult:
    command: str
    content: str
    metadata: dict[str, Any]
