from flask import Blueprint, request, jsonify
from services.ai_service import process_message, build_source_prompt
from services.rss_fetcher import fetch_rss_sources
from services.cache import get_cached_results, cache_results

research_bp = Blueprint("research_bp", __name__)

@research_bp.route("/", methods=["POST"])
def research():
    payload = request.get_json(silent=True) or {}
    query = (payload.get("query") or "").strip()

    if not query:
        return jsonify({"status": "error", "message": "query is required"}), 400

    # ✅ Check cache first
    cached = get_cached_results(query)
    if cached:
        return jsonify({"status": "success", "data": cached, "cached": True})

    # ✅ Fetch realtime RSS sources
    sources = fetch_rss_sources(query=query, limit=8)

    # Sort by date if available
    sources.sort(key=lambda x: x.get("published_parsed", 0), reverse=True)

    # Build strict prompt
    prompt = build_source_prompt(query, sources)

    # Ask AI to answer only using sources
    ai_result = process_message(
        message=prompt,
        context=[],
        intent="research",
        session_id=None
    )

    summary = ai_result.get("response", "Not enough info from sources.")

    result = {
        "query": query,
        "sources": sources,
        "summary": summary
    }

    # ✅ Cache results
    cache_results(query, result)

    return jsonify({"status": "success", "data": result, "cached": False})
