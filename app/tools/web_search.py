"""
Web search tools.

web_search      – single query against Tavily (primary) or Serper (fallback).
research_topic  – generates multiple queries, searches, and synthesises a
                  fact-based research brief using the LLM.

Configure via .env:
  TAVILY_API_KEY   – preferred (purpose-built for LLM agents)
  SERPER_API_KEY   – fallback (Google Search results)
"""
import json
from typing import Any

import httpx
import structlog

from app.agent.llm_client import call_llm_json
from app.config import get_settings

log = structlog.get_logger(__name__)
settings = get_settings()

_TAVILY_URL = "https://api.tavily.com/search"
_SERPER_URL  = "https://google.serper.dev/search"

_QUERY_GEN_SYSTEM = """\
You are a research assistant. Generate focused search queries to fully cover a topic.

Return ONLY a JSON object – no markdown fences:
{"queries": ["<query 1>", "<query 2>", "<query 3>"]}

Rules:
- Each query must be specific and search-engine friendly.
- Cover different angles: facts, recent news, opinions/stats.
- Avoid redundancy between queries.
"""

_SYNTHESIS_SYSTEM = """\
You are a senior research analyst. Synthesise search results into a clear,
fact-based research brief that a writer can use immediately.

Return ONLY a JSON object – no markdown fences:
{
  "summary":     "<2-3 sentence executive summary>",
  "key_facts":   ["<fact with source>", "…"],
  "recent_news": ["<recent development>", "…"],
  "statistics":  ["<stat with source>", "…"],
  "brief":       "<full research brief in Markdown – ~300 words>",
  "sources":     [{"title": "…", "url": "…"}]
}
"""


async def _search_tavily(query: str, num_results: int) -> dict[str, Any]:
    payload = {
        "api_key": settings.tavily_api_key,
        "query": query,
        "search_depth": "basic",
        "max_results": num_results,
        "include_answer": True,
        "include_raw_content": False,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(_TAVILY_URL, json=payload)
        r.raise_for_status()
        data = r.json()

    results = [
        {
            "title":   item.get("title", ""),
            "url":     item.get("url", ""),
            "snippet": item.get("content", "")[:400],
        }
        for item in data.get("results", [])
    ]
    return {
        "query":   query,
        "answer":  data.get("answer", ""),
        "results": results,
        "source":  "tavily",
    }


async def _search_serper(query: str, num_results: int) -> dict[str, Any]:
    headers = {
        "X-API-KEY":    settings.serper_api_key,
        "Content-Type": "application/json",
    }
    payload = {"q": query, "num": num_results}
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(_SERPER_URL, json=payload, headers=headers)
        r.raise_for_status()
        data = r.json()

    results = [
        {
            "title":   item.get("title", ""),
            "url":     item.get("link", ""),
            "snippet": item.get("snippet", "")[:400],
        }
        for item in data.get("organic", [])
    ]
    answer = data.get("answerBox", {}).get("answer", "")
    return {
        "query":   query,
        "answer":  answer,
        "results": results,
        "source":  "serper",
    }


async def _search(query: str, num_results: int) -> dict[str, Any]:
    """Route to Tavily or Serper depending on which key is configured."""
    if settings.tavily_api_key:
        return await _search_tavily(query, num_results)
    if settings.serper_api_key:
        return await _search_serper(query, num_results)
    raise RuntimeError(
        "No search API key configured. Set TAVILY_API_KEY or SERPER_API_KEY in .env."
    )


async def web_search(
    query: str,
    num_results: int = 5,
) -> str:
    """
    Search the web for real-time information.

    Args:
        query:       Search query string.
        num_results: Number of results to return (1–10).

    Returns:
        JSON string with results (title, url, snippet) and an AI-generated answer.
    """
    num_results = max(1, min(num_results, 10))
    log.info("web_search", query=query[:80], num_results=num_results)

    data = await _search(query, num_results)
    log.info("web_search_done", source=data["source"], hits=len(data["results"]))
    return json.dumps(data, indent=2)


async def research_topic(
    topic: str,
    context: str = "",
    num_queries: int = 3,
) -> str:
    """
    Deep-research a topic: auto-generates search queries, runs them, then
    synthesises findings into a structured research brief.

    Args:
        topic:       Topic to research (e.g. "impact of AI on marketing in 2024").
        context:     Any existing context or specific angles to focus on.
        num_queries: Number of search queries to generate (2–4 recommended).

    Returns:
        JSON string with key facts, statistics, recent news, and a full brief.
    """
    num_queries = max(1, min(num_queries, 4))
    log.info("research_topic", topic=topic[:80], num_queries=num_queries)

    # Step 1: Generate search queries
    query_messages = [
        {"role": "system", "content": _QUERY_GEN_SYSTEM},
        {
            "role": "user",
            "content": f"Topic: {topic}\nContext: {context or 'None'}\n"
                       f"Generate exactly {num_queries} search queries.",
        },
    ]
    query_result = await call_llm_json(query_messages, temperature=0.3)
    queries: list[str] = query_result.get("queries", [topic])[:num_queries]
    log.info("research_queries_generated", queries=queries)

    # Step 2: Execute each query
    all_results: list[dict] = []
    seen_urls: set[str] = set()
    for q in queries:
        try:
            data = await _search(q, num_results=5)
            for item in data.get("results", []):
                if item["url"] not in seen_urls:
                    seen_urls.add(item["url"])
                    all_results.append(item)
        except Exception as exc:
            log.warning("research_search_failed", query=q, error=str(exc))

    if not all_results:
        return json.dumps({
            "status": "error",
            "message": "No search results found. Check your TAVILY_API_KEY or SERPER_API_KEY.",
        }, indent=2)

    # Step 3: Synthesise with LLM
    results_text = "\n\n".join(
        f"[{i+1}] {r['title']}\nURL: {r['url']}\n{r['snippet']}"
        for i, r in enumerate(all_results[:15])  # cap at 15 to stay within token limits
    )
    synthesis_messages = [
        {"role": "system", "content": _SYNTHESIS_SYSTEM},
        {
            "role": "user",
            "content": f"Topic: {topic}\n\nSearch results:\n{results_text}\n\nSynthesise now.",
        },
    ]
    brief = await call_llm_json(synthesis_messages, temperature=0.3)
    brief["topic"] = topic
    brief["queries_used"] = queries
    brief["total_sources_found"] = len(all_results)

    log.info("research_complete", topic=topic[:60], sources=len(all_results))
    return json.dumps(brief, indent=2)
