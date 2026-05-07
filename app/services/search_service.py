from dataclasses import dataclass

import httpx

from ..config import settings


@dataclass
class SearchResult:
    title: str
    url: str
    content: str
    score: float


async def search_web(query: str, max_results: int | None = None) -> list[SearchResult]:
    if not settings.TAVILY_API_KEY:
        return []

    max_results = max_results or settings.WEB_SEARCH_MAX_RESULTS

    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            "https://api.tavily.com/search",
            json={
                "api_key": settings.TAVILY_API_KEY,
                "query": query,
                "max_results": max_results,
                "include_answer": False,
            },
        )
        response.raise_for_status()
        data = response.json()

    results = []
    for item in data.get("results", []):
        results.append(
            SearchResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                content=item.get("content", ""),
                score=item.get("score", 0.0),
            )
        )
    return results


def format_search_results(results: list[SearchResult]) -> str:
    if not results:
        return "未找到相关搜索结果。"

    parts = []
    for i, result in enumerate(results, 1):
        parts.append(f"[{i}] {result.title}\n来源: {result.url}\n{result.content}")
    return "\n\n".join(parts)
