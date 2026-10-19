"""Native FastAPI research endpoint.

The implementation reuses the existing RSS, cache, and AI service layer; those
services are shared with the old Flask modules but do not require Flask request
or response objects.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

logger = logging.getLogger("revelaai.fastapi.research")
router = APIRouter(prefix="/api/research", tags=["Research"])


def _run_research(query: str) -> tuple[dict[str, Any], bool]:
    """Run blocking RSS/cache/provider work off the ASGI event loop."""
    from services.ai_service import build_source_prompt, process_message
    from services.cache import cache_results, get_cached_results
    from services.rss_fetcher import fetch_rss_sources

    cached = get_cached_results(query)
    if cached:
        return cached, True

    sources = fetch_rss_sources(query=query, limit=8) or []
    if not isinstance(sources, list):
        sources = []
    sources.sort(
        key=lambda item: item.get("published_parsed", 0) or 0
        if isinstance(item, dict)
        else 0,
        reverse=True,
    )

    prompt = str(build_source_prompt(query, sources))
    ai_result = process_message(
        message=prompt,
        context=[],
        intent="research",
        session_id=None,
    ) or {}
    summary = (
        ai_result.get("response", "Not enough info from sources.")
        if isinstance(ai_result, dict)
        else "Not enough info from sources."
    )

    result = {"query": query, "sources": sources, "summary": summary}
    cache_results(query, result)
    return result, False


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
        return JSONResponse(
            {"status": "error", "message": "query is required"},
            status_code=400,
        )

    try:
        data, cached = await run_in_threadpool(_run_research, query)
    except Exception as exc:
        logger.warning(
            "Research request failed | error_type=%s",
            type(exc).__name__,
        )
        return JSONResponse(
            {"status": "error", "message": "Research is temporarily unavailable."},
            status_code=503,
        )

    return {"status": "success", "data": data, "cached": cached}
