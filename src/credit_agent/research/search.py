"""Search provider abstraction.

A thin, provider-agnostic layer over web search. The product ships with a
Tavily adapter (LLM-optimised, returns sourced snippets) and a Mock provider
used for tests and offline operation. Additional providers (Brave, Google
Programmable Search, SerpAPI) can be dropped in by implementing `SearchProvider`.
"""

from __future__ import annotations

import json
import os
import urllib.request
from abc import ABC, abstractmethod
from pydantic import BaseModel


class SearchResult(BaseModel):
    query: str
    title: str = ""
    url: str
    content: str = ""
    score: float | None = None
    published_date: str | None = None
    provider: str = ""


class SearchProvider(ABC):
    name: str = "base"

    @abstractmethod
    def search(self, query: str, n: int = 5, topic: str = "general",
               days: int | None = None) -> list[SearchResult]:
        ...


class TavilyProvider(SearchProvider):
    name = "tavily"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("TAVILY_API_KEY")
        if not self.api_key:
            raise RuntimeError("TAVILY_API_KEY is not set (export it or use another provider).")

    def search(self, query: str, n: int = 5, topic: str = "general",
               days: int | None = None) -> list[SearchResult]:
        body = {"api_key": self.api_key, "query": query, "max_results": n, "topic": topic}
        if days:
            body["days"] = days
        req = urllib.request.Request(
            "https://api.tavily.com/search",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=25) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        out = []
        for r in data.get("results", []):
            out.append(SearchResult(
                query=query, title=r.get("title", ""), url=r["url"],
                content=r.get("content", ""), score=r.get("score"),
                published_date=r.get("published_date"), provider=self.name,
            ))
        return out


class MockProvider(SearchProvider):
    name = "mock"

    def __init__(self, results: list[SearchResult] | None = None):
        self._results = results or []

    def search(self, query: str, n: int = 5, topic: str = "general",
               days: int | None = None) -> list[SearchResult]:
        return [r for r in self._results if query.lower() in r.query.lower()][:n]


def get_provider(name: str = "tavily", api_key: str | None = None) -> SearchProvider:
    if name == "mock":
        return MockProvider()
    if name == "tavily":
        return TavilyProvider(api_key)
    raise ValueError(f"Unknown provider: {name}")
