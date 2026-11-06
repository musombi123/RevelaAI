"""Local, deterministic, selective humanization suggestions.

This module never calls an LLM or external service. It proposes conservative
word/phrase alternatives for text explicitly selected by the user. It does not
rewrite whole documents, claim to bypass AI detectors, or alter source files.
"""
from __future__ import annotations

import re
from typing import Any

MAX_SELECTION_CHARS = 4_000
MAX_CONTEXT_CHARS = 1_000

# Conservative phrase substitutions. Entries are suggestions, not universal
# synonyms; the API returns rationale and requires explicit user acceptance.
PHRASE_RULES: tuple[tuple[str, tuple[str, ...], str], ...] = (
    (r"\bin order to\b", ("to",), "Shorten a wordy construction."),
    (r"\bdue to the fact that\b", ("because",), "Use a more direct connector."),
    (r"\bat this point in time\b", ("now", "currently"), "Replace a wordy time expression."),
    (r"\bfor the purpose of\b", ("to", "for"), "Use a more concise phrase."),
    (r"\bin the event that\b", ("if",), "Use a direct conditional."),
    (r"\bwith regard to\b", ("about", "regarding"), "Use a clearer connector."),
    (r"\bmake use of\b", ("use",), "Prefer the direct verb."),
    (r"\bhas the ability to\b", ("can",), "Prefer a concise modal verb."),
    (r"\ba large number of\b", ("many",), "Use a concise quantifier."),
    (r"\ba small number of\b", ("few",), "Use a concise quantifier."),
    (r"\bthe majority of\b", ("most",), "Use a concise quantifier."),
    (r"\bin spite of the fact that\b", ("although", "even though"), "Simplify the contrast."),
    (r"\bit is important to note that\b", ("notably,", "Importantly,"), "Remove a stock introductory phrase."),
    (r"\bthere are a number of\b", ("there are several", "several"), "Reduce unnecessary wording."),
    (r"\butilize\b", ("use",), "Prefer a familiar verb."),
    (r"\bdemonstrate\b", ("show", "illustrate"), "Offer a more natural verb."),
    (r"\bcommence\b", ("begin", "start"), "Prefer a familiar verb."),
    (r"\bterminate\b", ("end", "stop"), "Prefer a familiar verb."),
    (r"\bapproximately\b", ("about", "roughly"), "Offer a more conversational alternative."),
    (r"\bsubsequently\b", ("later", "afterward"), "Offer a simpler transition."),
    (r"\bfurthermore\b", ("also", "in addition"), "Vary a formal transition."),
    (r"\bmoreover\b", ("also", "besides"), "Vary a formal transition."),
    (r"\btherefore\b", ("so", "as a result"), "Offer a more natural transition."),
    (r"\bfacilitate\b", ("help", "make easier"), "Prefer a clearer verb."),
    (r"\bnecessitate\b", ("require", "call for"), "Prefer a familiar verb."),
    (r"\bendeavour\b", ("effort", "attempt"), "Offer a simpler alternative."),
    (r"\bendeavor\b", ("effort", "attempt"), "Offer a simpler alternative."),
)

PROTECTED_PATTERNS = (
    re.compile(r"\\b(?:https?://|www\\.)\\S+", re.I),
    re.compile(r"\\b[\\w.+-]+@[\\w.-]+\\.[A-Za-z]{2,}\\b"),
    re.compile(r"\\b(?:19|20)\\d{2}\\b"),
    re.compile(r"\\b\\d+(?:\\.\\d+)?%\\b"),
    re.compile(r"\\b(?:[A-Z]{2,}|[A-Z][a-z]+(?:[A-Z][a-z]+)+)\\b"),
)


def _match_case(source: str, replacement: str) -> str:
    if source.isupper():
        return replacement.upper()
    if source[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def _is_protected(span: tuple[int, int], text: str) -> bool:
    start, end = span
    for pattern in PROTECTED_PATTERNS:
        if any(start < match.end() and end > match.start() for match in pattern.finditer(text)):
            return True
    return False


def suggest_selected_text(
    selected_text: str,
    *,
    before: str = "",
    after: str = "",
    style: str = "natural",
) -> dict[str, Any]:
    """Return ranked deterministic suggestions for a user-selected passage."""
    selected = str(selected_text or "")
    if not selected.strip():
        raise ValueError("Select a word or phrase first.")
    if len(selected) > MAX_SELECTION_CHARS:
        raise ValueError(f"Selection exceeds {MAX_SELECTION_CHARS} characters.")
    if style not in {"natural", "clear", "concise", "formal"}:
        raise ValueError("Style must be natural, clear, concise, or formal.")

    context_before = str(before or "")[-MAX_CONTEXT_CHARS:]
    context_after = str(after or "")[:MAX_CONTEXT_CHARS]
    # Context is deliberately informational only; it is never sent to a model.
    suggestions: list[dict[str, str]] = []
    seen: set[tuple[int, int, str]] = set()

    for expression, alternatives, rationale in PHRASE_RULES:
        for match in re.finditer(expression, selected, flags=re.IGNORECASE):
            if _is_protected(match.span(), selected):
                continue
            original = match.group(0)
            for alternative in alternatives:
                candidate = _match_case(original, alternative)
                key = (match.start(), match.end(), candidate.casefold())
                if key in seen or candidate.casefold() == original.casefold():
                    continue
                seen.add(key)
                suggestions.append({
                    "original": original,
                    "replacement": candidate,
                    "start": str(match.start()),
                    "end": str(match.end()),
                    "reason": rationale,
                    "style": style,
                })

    # Do not invent alternatives when no safe local rule applies.
    return {
        "engine": "revelacode-local-humanizer",
        "version": "1.0.0",
        "model_used": False,
        "selection_characters": len(selected),
        "suggestion_count": len(suggestions),
        "suggestions": suggestions[:40],
        "context_used": bool(context_before or context_after),
        "notice": "Suggestions are optional. Review each change; the original text has not been modified.",
    }


def apply_accepted_replacements(text: str, replacements: list[dict[str, Any]]) -> str:
    """Apply explicit, non-overlapping exact-span replacements from right to left."""
    source = str(text or "")
    normalized: list[tuple[int, int, str]] = []
    for item in replacements:
        if not isinstance(item, dict):
            raise ValueError("Each accepted replacement must be an object.")
        try:
            start, end = int(item["start"]), int(item["end"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Each replacement needs valid start and end offsets.") from exc
        original = str(item.get("original") or "")
        replacement = str(item.get("replacement") or "")
        if start < 0 or end <= start or end > len(source) or source[start:end] != original:
            raise ValueError("A replacement no longer matches the source text. Refresh suggestions before applying.")
        if not replacement or len(replacement) > 500:
            raise ValueError("Replacement text is empty or too long.")
        normalized.append((start, end, replacement))

    normalized.sort(key=lambda item: item[0])
    for previous, current in zip(normalized, normalized[1:]):
        if previous[1] > current[0]:
            raise ValueError("Overlapping replacements are not allowed.")

    result = source
    for start, end, replacement in reversed(normalized):
        result = result[:start] + replacement + result[end:]
    return result


__all__ = ["suggest_selected_text", "apply_accepted_replacements", "MAX_SELECTION_CHARS"]
