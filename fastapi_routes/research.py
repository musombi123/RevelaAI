"""Native FastAPI RSS research endpoint.

This port deliberately reads only a bounded set of configured feed URLs. It
never follows article links or accepts a user-controlled URL, limiting SSRF risk.
"""
from __future__ import annotations

import json
import logging
import xml.etree.ElementTree as ET
from typing import Any

import requests
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

logger = logging.getLogger("revelaai.fastapi.research")
router = APIRouter(prefix="/api/research", tags=["Research"])

RSS_SOURCES = {
    "BBC News": "https://feeds.bbci.co.uk/news/rss.xml",
    "Reuters Tech": "https://www.reutersagency.com/feed/?best-topics=technology",
    "TechCrunch": "https://techcrunch.com/feed/",
    "Hacker News": "https://news.ycombinator.com/rss",
    "Al Jazeera": "https://www.aljazeera.com/xml/rss/all.xml",
}
MAX_FEED_BYTES = 1_000_000
MAX_RESULTS = 30


def _bounded_feed_bytes(url: str) -> bytes | None:
    """Fetch a configured feed with timeouts, no redirects, and a hard byte cap."""
    try:
        with requests.get(
            url,
            headers={"User-Agent": "RevelaAI-Research/1.0"},
            timeout=(3, 5),
            allow_redirects=False,
            stream=True,
        ) as response:
            if response.status_code != 200:
                return None
            declared_size = response.headers.get("Content-Length")
            if declared_size and int(declared_size) > MAX_FEED_BYTES:
                return None
            data = bytearray()
            for chunk in response.iter_content(chunk_size=16_384):
                if not chunk:
                    continue
                data.extend(chunk)
                if len(data) > MAX_FEED_BYTES:
                    return None
            return bytes(data)
    except (requests.RequestException, ValueError, OSError):
        return None


def _search_feeds(query: str) -> list[dict[str, str]]:
    """Search configured RSS items without browsing or fetching article URLs."""
    needle = query.casefold()
    results: list[dict[str, str]] = []

    for source_name, feed_url in RSS_SOURCES.items():
        content = _bounded_feed_bytes(feed_url)
        if not content:
            continue
        try:
            root = ET.fromstring(content)
        except ET.ParseError:
            continue

        for item in root.findall(".//item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            description = (item.findtext("description") or "").strip()
            if needle not in f"{title} {description}".casefold():
                continue
            results.append({
                "source": source_name,
                "title": title[:500],
                "url": link[:2000],
                "snippet": description[:1500],
            })
            if len(results) >= MAX_RESULTS:
                return results
    return results


async def _read_json_object(request: Request) -> dict[str, Any]:
    try:
        body = json.loads((await request.body()).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return body if isinstance(body, dict) else {}


@router.post("")
async def research(request: Request):
    payload = await _read_json_object(request)
    query = str(payload.get("query") or "").strip()
    if not query:
        return JSONResponse({"error": "query is required"}, status_code=400)
    if len(query) > 500:
        return JSONResponse({"error": "query is too long"}, status_code=400)

    try:
        results = await run_in_threadpool(_search_feeds, query)
    except Exception as exc:
        logger.warning("RSS research failed | error_type=%s", type(exc).__name__)
        return JSONResponse(
            {"error": "Research is temporarily unavailable."},
            status_code=503,
        )
    return {"query": query, "sources": results, "realtime": True}
