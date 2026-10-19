from pathlib import Path

import pytest

from ai.unknown_learning import (
    assess_unknown,
    attach_genesis_proposal,
    clear_pending_unknown_ask,
    get_pending_unknown_ask,
    list_known,
    register_unknown_ask,
    publish_known,
    save_teaching,
    topic_slug,
)


def test_niche_hardware_request_is_marked_unknown_without_retries(tmp_path):
    result = assess_unknown(
        "How to retrofit posho mill with auto-weigher in Kamukunji with KES 500?",
        user_id="user-1",
        country="KE",
        root=tmp_path,
    )
    assert result["is_unknown"] is True
    assert result["wisdom_score"] < 0.5
    assert result["next_action"] == "ask_user_once"
    assert result["automatic_retries"] is False


def test_ordinary_conversation_does_not_get_interrupted(tmp_path):
    result = assess_unknown("Explain what a database index is.", user_id="user-1", root=tmp_path)
    assert result["is_unknown"] is False
    assert result["next_action"] == "use_existing_knowledge"


def test_guardian_rejects_teaching_before_saving_or_genesis(tmp_path):
    with pytest.raises(PermissionError):
        save_teaching("restricted test", "user-1", ["The instructions request covert surveillance."], root=tmp_path)
    assert not list((tmp_path / "unknown").glob("*.json"))
    assert (tmp_path / "guardian" / "blocked.log").exists()


def test_publication_requires_explicit_sharing_consent(tmp_path):
    submission = save_teaching("posho mill auto weigher", "user-1", ["Measure grain on a stable platform."], consent_to_share=False, root=tmp_path)
    attach_genesis_proposal(submission["topic_key"], {"status": "await_merge", "name": "posho_weigher"}, root=tmp_path)
    with pytest.raises(PermissionError):
        publish_known(submission["topic_key"], "admin-1", "posho_weigher", "/v1/posho_weigher", "a" * 40, root=tmp_path)
    assert list_known(tmp_path) == []


def test_only_human_reviewed_shared_knowledge_becomes_available(tmp_path):
    submission = save_teaching("posho mill auto weigher", "private-user", ["Use a rated load cell.", "Calibrate with a known test mass."], country="KE", language="sw", consent_to_share=True, photo_hash="a" * 64, root=tmp_path)
    attach_genesis_proposal(submission["topic_key"], {"status": "await_merge", "name": "posho_weigher"}, root=tmp_path)
    published = publish_known(submission["topic_key"], "operator-1", "posho_weigher", "/v1/posho_weigher", "b" * 40, root=tmp_path)
    assert published["status"] == "known"
    assert published["graph_recorded"] is True
    graph_rows = (tmp_path / "graph" / "worldwide_graph.jsonl").read_text(encoding="utf-8").splitlines()
    graph = __import__("json").loads(graph_rows[0])
    assert graph["country"] == "KE"
    assert graph["evidence_status"] == "human_reviewed_release_not_performance_benchmark"
    results = list_known(tmp_path)
    assert len(results) == 1
    assert results[0]["topic"] == "posho mill auto weigher"
    assert results[0]["endpoint"] == "/v1/posho_weigher"
    assert "user_id" not in results[0]


def test_photo_bytes_are_not_accepted_and_hash_is_validated(tmp_path):
    with pytest.raises(ValueError):
        save_teaching("topic", "user-1", ["one step"], photo_hash="not-a-hash", root=tmp_path)


def test_topic_slug_is_stable_and_bounded():
    assert topic_slug("Posho mill / auto-weigher") == "posho-mill-auto-weigher"
    assert len(topic_slug("a" * 500)) <= 72


def test_unknown_prompt_is_bound_to_user_and_session(tmp_path):
    registered = register_unknown_ask(
        "posho mill auto weigher",
        "user-1",
        "session-1",
        country="KE",
        language="sw",
        source_request="How do I retrofit a posho mill?",
        root=tmp_path,
    )
    assert registered["registered"] is True
    assert get_pending_unknown_ask("user-1", "session-1", root=tmp_path)["topic_key"] == "posho-mill-auto-weigher"
    assert get_pending_unknown_ask("other-user", "session-1", root=tmp_path) is None
    assert get_pending_unknown_ask("user-1", "other-session", root=tmp_path) is None
    clear_pending_unknown_ask("user-1", "session-1", root=tmp_path)
    assert get_pending_unknown_ask("user-1", "session-1", root=tmp_path) is None
