from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any


@dataclass(slots=True)
class QianduSearchPlan:
    query: str
    queries: list[str]
    intent: str = "general"
    topic: str = "general"
    time_range: str | None = None
    include_domains: list[str] = field(default_factory=list)
    exclude_domains: list[str] = field(default_factory=list)
    preferred_providers: list[str] = field(default_factory=list)

    def with_query(self, query: str) -> "QianduSearchPlan":
        return replace(self, query=query)


@dataclass(slots=True)
class QianduSearchResult:
    title: str
    url: str
    snippet: str
    score: float
    provider: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class QianduExtractedDocument:
    title: str
    url: str
    content: str
    provider: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class QianduEvidenceChunk:
    title: str
    url: str
    text: str
    provider: str
    rank_score: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class QianduSearchCommandResult:
    command: str
    content: str
    metadata: dict[str, Any]


@dataclass(slots=True)
class QianduIntelExtraction:
    summary: str
    names: list[str]
    phones: list[str]
    id_numbers: list[str]
    addresses: list[dict[str, str]]
    organizations: list[str]
    other_fields: dict[str, list[str]]
    data_quality: str
    raw_input: str


@dataclass(slots=True)
class QianduSearchTask:
    task_id: str
    task_type: str
    query: str
    goal: str
    priority: int
    include_domains: list[str] = field(default_factory=list)
    preferred_providers: list[str] = field(default_factory=list)
