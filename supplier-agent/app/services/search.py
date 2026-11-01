"""Web search through the `ddgs` metasearch library (MIT). Swappable via SEARCH_BACKENDS."""

from __future__ import annotations

import time

from .logs import syslog


class SearchError(Exception):
    pass


def ddgs_search(query: str, max_results: int = 10, region: str = "wt-wt") -> list[dict]:
    from ddgs import DDGS

    last = None
    for attempt in range(3):
        try:
            res = DDGS(timeout=20).text(query, region=region, max_results=max_results) or []
            return [{"url": r.get("href", ""), "title": r.get("title", ""), "snippet": r.get("body", "")}
                    for r in res if r.get("href", "").startswith("http")]
        except Exception as e:  # ddgs raises its own exception types for rate limits / no results
            last = e
            if "No results" in str(e):
                return []
            time.sleep(2 * (attempt + 1))
    syslog("WARNING", "search", f"搜索失败 '{query}': {last}")
    raise SearchError(str(last))


SEARCH_BACKENDS = {"ddgs": ddgs_search}


def search(query: str, max_results: int = 10, engine: str = "ddgs", region: str = "wt-wt") -> list[dict]:
    return SEARCH_BACKENDS[engine](query, max_results=max_results, region=region)
