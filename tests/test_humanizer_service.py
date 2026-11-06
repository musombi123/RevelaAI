"""Tests for the deterministic, selective, model-free Humanizer."""
import pytest

from services.humanizer_service import apply_accepted_replacements, suggest_selected_text


def test_suggestions_are_local_and_only_cover_selected_text():
    result = suggest_selected_text("We make use of this method in order to improve results.")
    assert result["model_used"] is False
    assert result["engine"] == "revelacode-local-humanizer"
    assert result["suggestion_count"] >= 2
    assert all(item["original"] in "We make use of this method in order to improve results." for item in result["suggestions"])


def test_empty_selection_is_rejected():
    with pytest.raises(ValueError):
        suggest_selected_text("   ")


def test_selection_limit_is_enforced():
    with pytest.raises(ValueError):
        suggest_selected_text("x" * 4001)


def test_protected_year_is_not_suggested():
    result = suggest_selected_text("The 2024 report was published.")
    assert all(item["original"] != "2024" for item in result["suggestions"])


def test_case_is_preserved():
    result = suggest_selected_text("UTILIZE this method.")
    assert any(item["replacement"] == "USE" for item in result["suggestions"])


def test_apply_only_explicit_accepted_replacements():
    source = "We make use of tools."
    result = apply_accepted_replacements(source, [
        {"start": 3, "end": 14, "original": "make use of", "replacement": "use"}
    ])
    assert result == "We use tools."


def test_apply_rejects_stale_or_forged_offsets():
    with pytest.raises(ValueError):
        apply_accepted_replacements("Original text", [
            {"start": 0, "end": 8, "original": "Different", "replacement": "Changed"}
        ])


def test_apply_rejects_overlapping_replacements():
    with pytest.raises(ValueError):
        apply_accepted_replacements("abcdefghij", [
            {"start": 0, "end": 4, "original": "abcd", "replacement": "AB"},
            {"start": 2, "end": 6, "original": "cdef", "replacement": "CD"},
        ])
