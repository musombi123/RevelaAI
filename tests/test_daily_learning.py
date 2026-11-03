from __future__ import annotations

import json
from datetime import date

from ai import daily_learning


class FakeResearchStore:
    def __init__(self):
        self.documents = []

    def count_documents(self, query):
        return sum(
            1 for item in self.documents
            if all(item.get(key) == value for key, value in query.items())
        )

    def insert_one(self, document):
        self.documents.append(dict(document))
        return type("InsertResult", (), {"inserted_id": len(self.documents)})()


def _fake_search_results(query, limit=5, realtime=True, force_refresh=True):
    topic = next((name for name, text in daily_learning.TRACKS if text == query), "general")
    return {
        "available": True,
        "status": "active",
        "sources": [
            {
                "title": f"{topic} source {index}",
                "url": f"https://research.example/{topic}/{index}",
                "snippet": "Official API documentation and implementation guidance.",
                "published_at": "2026-11-03",
                "provider": "official-docs",
            }
            for index in range(5)
        ],
    }


def test_daily_learning_covers_every_track_and_caps_each_at_three_sources(monkeypatch):
    store = FakeResearchStore()
    search_queries = []

    def fake_search(query, **kwargs):
        search_queries.append(query)
        return _fake_search_results(query, **kwargs)

    monkeypatch.setattr("revelai.sci_core.storage.collection", lambda _name: store)
    monkeypatch.setattr("services.scraper.get_live_research", fake_search)

    candidate_json = {
        "candidates": [{
            "area": "tool interoperability",
            "finding": "A documented MCP capability can be integrated as a typed tool adapter.",
            "why_it_matters": "It gives Gemini an interoperable, source-backed tool contract.",
            "tool_or_build_pattern": "Validate schemas and dispatch through an authorized adapter.",
            "source_urls": ["https://research.example/gemini-platform/0"],
            "confidence": "high",
        }]
    }
    monkeypatch.setattr(
        daily_learning,
        "ask_gemini",
        lambda **_kwargs: {
            "success": True,
            "model": "gemini-test",
            "response": json.dumps(candidate_json),
        },
    )

    result = daily_learning.run_daily_learning_cycle(
        run_date=date(2026, 11, 3),
        force=True,
    )

    assert result["status"] == "candidates_ready"
    assert result["source_count"] == 24
    assert result["candidate_count"] == 1
    assert len(search_queries) == len(daily_learning.TRACKS) == 8
    stored = store.documents[-1]
    assert stored["learning_mode"] == "retrieval_and_review_not_model_weight_training"
    assert stored["review_required"] is True
    assert stored["production_change_performed"] is False
    assert len(stored["topics"]) == 8
    assert all(item["sources"] <= 3 for item in stored["topics"])
    assert stored["candidates"][0]["review_status"] == "pending_review"


def test_daily_learning_persists_gemini_failure_instead_of_losing_run_status(monkeypatch):
    store = FakeResearchStore()
    monkeypatch.setattr("revelai.sci_core.storage.collection", lambda _name: store)
    monkeypatch.setattr("services.scraper.get_live_research", _fake_search_results)

    def fail_gemini(**_kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(daily_learning, "ask_gemini", fail_gemini)
    result = daily_learning.run_daily_learning_cycle(
        run_date=date(2026, 11, 3),
        force=True,
    )

    assert result["status"] == "gemini_unavailable"
    assert store.documents[-1]["candidate_count"] == 0
    assert store.documents[-1]["production_change_performed"] is False
    assert store.documents[-1]["error_code"] == "gemini_daily_learning_failed"


def test_daily_learning_does_not_repeat_a_completed_day_without_force(monkeypatch):
    store = FakeResearchStore()
    store.documents.append({
        "kind": "daily_gemini_learning",
        "run_date": "2026-11-03",
        "status": "candidates_ready",
    })
    monkeypatch.setattr("revelai.sci_core.storage.collection", lambda _name: store)

    result = daily_learning.run_daily_learning_cycle(
        run_date=date(2026, 11, 3),
        force=False,
    )

    assert result == {"status": "already_completed", "run_date": "2026-11-03"}
