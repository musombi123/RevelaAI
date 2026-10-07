"""RevelaAI image prompt planner."""

from __future__ import annotations

import os
import re
from typing import Any

QUOTED = re.compile(r'["“]([^"”]{1,60})["”]')

KEYWORD = re.compile(
    r"\b(?:writing|written|saying|says|reads|wording|caption|title|text)\b"
    r"\s*(?:of|is|as|:)?\s*"
    r"([A-Za-z0-9][A-Za-z0-9 '&-]{0,40}?)"
    r"(?=\s+(?:on|in|with|and|for|using|style|logo|poster|banner)\b|[.,;!?\n]|$)",
    re.I,
)

TEXT_FORMATS = (
    "logo", "poster", "banner", "flyer", "sign", "card", "t-shirt",
    "tshirt", "badge", "sticker", "label", "cover", "emblem",
)

ECOSYSTEM_TERMS = ("revelacode", "revelaai", "jumuiya", "biashara", "shamba", "elimu")

ECOSYSTEM_HUBS = (
    "RevelaAI at the center, connected to Theology Hub, Biashara, "
    "Shamba, Elimu and Community"
)

LOGO_ENGINE = os.getenv("RA_LOGO_ENGINE", "svg").strip().lower()  # "svg" | "image"


def _has(text: str, words: tuple[str, ...]) -> bool:
    return any(re.search(rf"\b{re.escape(word)}", text) for word in words)


def _detect_kind(request: str) -> str:
    t = request.lower()

    if _has(t, ("logo", "emblem", "monogram", "wordmark", "brand mark")):
        return "logo"
    if _has(t, ("poster", "flyer", "banner", "billboard", "invitation", "certificate")):
        return "poster"
    if _has(t, ("diagram", "architecture", "flowchart", "infographic", "ecosystem map")):
        return "diagram"
    if _has(t, ("cartoon", "illustration", "drawing", "anime", "comic",
                "watercolor", "painting", "sketch", "3d render", "pixel art")):
        return "illustration"
    return "photo"


def extract_text(request: str) -> str | None:
    """Find the exact words the user wants written in the image."""
    quoted = QUOTED.search(request)
    if quoted:
        found = quoted.group(1).strip()
    else:
        lowered = request.lower()
        if not any(fmt in lowered for fmt in TEXT_FORMATS):
            return None
        match = KEYWORD.search(request)
        if not match:
            return None
        found = match.group(1).strip()

    if not found:
        return None

    return found.title() if found.islower() else found


def _text_clause(text: str | None) -> str:
    if not text:
        return ""
    return (
        f' The design contains exactly this text, spelled correctly, in a bold '
        f'clean sans-serif typeface: "{text}". No other words or letters.'
    )


def build_image_prompt(user_request: str) -> dict[str, Any]:
    request = " ".join(str(user_request or "").split())

    if not request:
        raise ValueError("Image request cannot be empty.")

    kind = _detect_kind(request)
    text = extract_text(request)
    ecosystem = any(term in request.lower() for term in ECOSYSTEM_TERMS)

    width, height, engine = 1216, 832, "image"

    if kind == "photo":
        prompt = (
            f"{request}. Candid documentary photograph, shot on a 35mm lens in "
            "natural daylight, realistic skin texture and fabric detail, "
            "true-to-life colors, shallow depth of field, subtle film grain, "
            "unretouched."
        )

    elif kind == "illustration":
        prompt = f"{request}. Detailed, coherent composition with a clear subject."

    elif kind == "poster":
        width, height = 832, 1216
        prompt = (
            f"{request}. Professionally designed poster with one clear focal "
            "subject and generous empty space." + _text_clause(text)
        )

    elif kind == "logo":
        width, height = 1024, 1024
        engine = "svg" if LOGO_ENGINE == "svg" else "image"
        prompt = (
            f"{request}. Professional flat vector logo, clean geometric shapes, "
            "two or three solid colors, centered on a plain white background, "
            "crisp edges, no gradients, no shadows."
            + _text_clause(text)
        )

    else:  # diagram: diffusion models can't label boxes correctly
        engine = "svg"
        prompt = request
        if ecosystem:
            prompt = f"{request}. Hubs to show: {ECOSYSTEM_HUBS}."

    return {
        "prompt": prompt,
        "negative_prompt": "",  # FLUX ignores it; kept so old callers don't break
        "kind": kind,
        "engine": engine,
        "text": text,
        "has_text": bool(text),
        "width": width,
        "height": height,
        "domain": "revelacode_ecosystem" if ecosystem else "general",
        "style": kind,
        "format": f"{width}x{height}",
    }
