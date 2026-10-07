"""
RevelaAI Canva-style Image Prompt Planner.

Responsibilities:
- Understand a natural-language image request.
- Detect the requested design artifact.
- Detect explicit text.
- Preserve requested text exactly.
- Detect aspect-ratio / canvas format.
- Detect visual style.
- Detect color preferences.
- Determine image vs structured/SVG generation.
- Produce a normalized design specification for the
  image-generation and future Canva-style editing layers.

This module DOES NOT call the image model.
"""

from __future__ import annotations

import os
import re
from typing import Any


# =========================================================
# TEXT EXTRACTION
# =========================================================

# Explicit quoted text.
#
# Examples:
#   "RevelaAI"
#   “Code. Innovate. Transform.”
#
QUOTED = re.compile(
    r'[\"“](.{1,120}?)[\"”]'
)


# Natural-language text instructions.
#
# Examples:
#   poster saying Welcome to RevelaAI
#   logo with text RevelaCode
#   banner reading Code. Innovate. Transform.
#
KEYWORD = re.compile(
    r"\b(?:writing|written|saying|says|reads|wording|caption|headline|title|text)\b"
    r"\s*(?:of|is|as|:)?\s*"
    r"[\"“']?"
    r"([^\"”'\n]{1,120}?)"
    r"[\"”']?"
    r"(?=\s+(?:on|in|with|and|for|using|style|logo|poster|banner|"
    r"background|above|below)\b|[.,;!?\n]|$)",
    re.I,
)


# Formats where text is likely intentional.
TEXT_FORMATS = (
    "logo",
    "poster",
    "banner",
    "flyer",
    "sign",
    "card",
    "t-shirt",
    "tshirt",
    "badge",
    "sticker",
    "label",
    "cover",
    "emblem",
    "social media",
    "social post",
    "thumbnail",
    "presentation",
    "slide",
)


# =========================================================
# ARTIFACT CLASSIFICATION
# =========================================================

KIND_TERMS: dict[str, tuple[str, ...]] = {

    "logo": (
        "logo",
        "emblem",
        "monogram",
        "wordmark",
        "brand mark",
        "app icon",
        "favicon",
    ),

    "poster": (
        "poster",
        "flyer",
        "billboard",
        "invitation",
        "certificate",
        "event graphic",
        "campaign poster",
    ),

    "banner": (
        "banner",
        "web banner",
        "hero banner",
        "cover banner",
        "header graphic",
    ),

    "social": (
        "social media",
        "instagram post",
        "instagram",
        "facebook post",
        "facebook",
        "linkedin post",
        "linkedin",
        "twitter post",
        "twitter",
        "x post",
        "social post",
        "thumbnail",
    ),

    "presentation": (
        "presentation",
        "slide",
        "pitch deck",
        "powerpoint",
        "presentation slide",
    ),

    "diagram": (
        "diagram",
        "architecture",
        "flowchart",
        "infographic",
        "ecosystem map",
        "mind map",
        "process map",
        "system map",
    ),

    "illustration": (
        "cartoon",
        "illustration",
        "drawing",
        "anime",
        "comic",
        "watercolor",
        "painting",
        "sketch",
        "3d render",
        "pixel art",
        "vector art",
    ),
}


# =========================================================
# REVELACODE ECOSYSTEM
# =========================================================

ECOSYSTEM_TERMS = (
    "revelacode",
    "revelaai",
    "jumuiya",
    "biashara",
    "shamba",
    "elimu",
    "theology hub",
    "community",
)


ECOSYSTEM_HUBS = (
    "RevelaAI at the center, connected to Theology Hub, "
    "Biashara, Shamba, Elimu and Community"
)


# =========================================================
# FORMAT PRESETS
# =========================================================

FORMAT_PRESETS: dict[str, dict[str, Any]] = {

    "square": {
        "aspect_ratio": "1:1",
        "width": 1024,
        "height": 1024,
        "label": "Square",
    },

    "portrait": {
        "aspect_ratio": "2:3",
        "width": 832,
        "height": 1216,
        "label": "Portrait",
    },

    "landscape": {
        "aspect_ratio": "3:2",
        "width": 1216,
        "height": 832,
        "label": "Landscape",
    },

    "wide": {
        "aspect_ratio": "16:9",
        "width": 1536,
        "height": 864,
        "label": "Wide",
    },

    "story": {
        "aspect_ratio": "9:16",
        "width": 864,
        "height": 1536,
        "label": "Story",
    },

    "banner": {
        "aspect_ratio": "3:1",
        "width": 1536,
        "height": 512,
        "label": "Banner",
    },

    "social_portrait": {
        "aspect_ratio": "4:5",
        "width": 1088,
        "height": 1360,
        "label": "Social Portrait",
    },

    "presentation": {
        "aspect_ratio": "16:9",
        "width": 1280,
        "height": 720,
        "label": "Presentation",
    },

    "phone": {
        "aspect_ratio": "9:16",
        "width": 768,
        "height": 1365,
        "label": "Phone",
    },
}


# =========================================================
# STYLE DETECTION
# =========================================================

STYLE_TERMS: dict[str, tuple[str, ...]] = {

    "minimal": (
        "minimal",
        "minimalist",
        "clean",
        "simple",
        "modern minimal",
    ),

    "corporate": (
        "corporate",
        "professional",
        "business",
        "enterprise",
        "executive",
    ),

    "luxury": (
        "luxury",
        "premium",
        "elegant",
        "high-end",
        "exclusive",
    ),

    "playful": (
        "playful",
        "fun",
        "friendly",
        "youthful",
        "vibrant",
    ),

    "editorial": (
        "editorial",
        "magazine",
        "fashion editorial",
        "publication",
    ),

    "tech": (
        "technology",
        "tech",
        "digital",
        "futuristic",
        "ai",
        "cyber",
    ),

    "african_modern": (
        "african",
        "kenyan",
        "east african",
        "africa",
    ),
}


# =========================================================
# COLOR DETECTION
# =========================================================

COLOR_TERMS: dict[str, tuple[str, ...]] = {

    "blue": (
        "blue",
        "navy",
        "cobalt",
        "azure",
    ),

    "green": (
        "green",
        "emerald",
        "forest green",
        "olive",
    ),

    "purple": (
        "purple",
        "violet",
        "lavender",
    ),

    "red": (
        "red",
        "crimson",
        "scarlet",
    ),

    "orange": (
        "orange",
        "amber",
        "tangerine",
    ),

    "yellow": (
        "yellow",
        "gold",
        "mustard",
    ),

    "black": (
        "black",
        "charcoal",
    ),

    "white": (
        "white",
        "ivory",
        "cream",
    ),
}


# =========================================================
# ENGINE CONFIGURATION
# =========================================================

LOGO_ENGINE = (
    os.getenv(
        "RA_LOGO_ENGINE",
        "svg",
    )
    .strip()
    .lower()
)


# =========================================================
# HELPERS
# =========================================================


def _has(
    text: str,
    words: tuple[str, ...],
) -> bool:

    return any(
        re.search(
            rf"\b{re.escape(word)}\b",
            text,
            re.I,
        )
        for word in words
    )


def _first_match(
    text: str,
    mapping: dict[str, tuple[str, ...]],
    default: str,
) -> str:

    for value, words in mapping.items():

        if _has(
            text,
            words,
        ):

            return value

    return default


# =========================================================
# ARTIFACT DETECTION
# =========================================================


def _detect_kind(
    request: str,
) -> str:
    """
    Infer the primary visual artifact.
    """

    t = request.lower()

    # More specific classes first.
    priority = (
        "logo",
        "diagram",
        "presentation",
        "social",
        "banner",
        "poster",
        "illustration",
    )

    for kind in priority:

        if _has(
            t,
            KIND_TERMS[kind],
        ):

            return kind

    return "photo"


# =========================================================
# CANVAS FORMAT DETECTION
# =========================================================


def _detect_format(
    request: str,
    kind: str,
) -> tuple[str, dict[str, Any]]:

    t = request.lower()

    # -----------------------------------------------------
    # Explicit aspect ratios
    # -----------------------------------------------------

    if _has(
        t,
        (
            "story",
            "reel",
            "9:16",
            "vertical video",
        ),
    ):

        key = "story"

    elif _has(
        t,
        (
            "16:9",
            "wide screen",
            "widescreen",
        ),
    ):

        key = "wide"

    elif _has(
        t,
        (
            "4:5",
            "instagram portrait",
        ),
    ):

        key = "social_portrait"

    # -----------------------------------------------------
    # Artifact defaults
    # -----------------------------------------------------

    elif kind == "logo":

        key = "square"

    elif kind == "poster":

        key = "portrait"

    elif kind == "banner":

        key = "banner"

    elif kind == "presentation":

        key = "presentation"

    elif kind == "social":

        key = "social_portrait"

    elif kind == "diagram":

        key = "landscape"

    else:

        key = "landscape"

    return key, FORMAT_PRESETS[key]


# =========================================================
# STYLE DETECTION
# =========================================================


def _detect_style(
    request: str,
    kind: str,
) -> str:

    detected = _first_match(
        request.lower(),
        STYLE_TERMS,
        default="modern",
    )

    if detected == "modern":

        if kind == "logo":
            return "minimal"

        if kind in {
            "poster",
            "banner",
            "social",
            "presentation",
        }:
            return "professional"

        if kind == "diagram":
            return "clean"

    return detected


# =========================================================
# COLOR DETECTION
# =========================================================


def _detect_palette(
    request: str,
) -> list[str]:

    t = request.lower()

    palette: list[str] = []

    for name, words in COLOR_TERMS.items():

        if _has(
            t,
            words,
        ):

            palette.append(
                name
            )

    if palette:

        return palette[:3]

    return []


# =========================================================
# LAYOUT DETECTION
# =========================================================


def _detect_layout(
    request: str,
    kind: str,
    has_text: bool,
) -> str:

    t = request.lower()

    if _has(
        t,
        (
            "centered",
            "centre",
            "center",
        ),
    ):

        return "centered"

    if _has(
        t,
        (
            "split layout",
            "split screen",
            "split design",
        ),
    ):

        return "split"

    if _has(
        t,
        (
            "text left",
            "left aligned",
            "copy on left",
        ),
    ):

        return "text_left"

    if _has(
        t,
        (
            "text right",
            "right aligned",
            "copy on right",
        ),
    ):

        return "text_right"

    if kind == "logo":

        return "symbol_above_wordmark"

    if kind in {
        "poster",
        "banner",
        "social",
        "presentation",
    } and has_text:

        return "focal_subject_with_text_zone"

    if kind == "diagram":

        return "structured_nodes"

    return "subject_focused"


# =========================================================
# TEXT EXTRACTION
# =========================================================


def extract_text(
    request: str,
) -> str | None:
    """
    Extract text that the user explicitly wants rendered.

    IMPORTANT:
    Never modify the user's supplied text.
    """

    # -----------------------------------------------------
    # Best case: quoted text
    # -----------------------------------------------------

    quoted = QUOTED.search(
        request
    )

    if quoted:

        found = (
            quoted.group(1)
            .strip()
        )

        return (
            found
            if found
            else None
        )

    # -----------------------------------------------------
    # Natural-language text request
    # -----------------------------------------------------

    if not any(
        _has(
            request,
            (fmt,),
        )
        for fmt in TEXT_FORMATS
    ):

        return None

    match = KEYWORD.search(
        request
    )

    if not match:

        return None

    found = (
        match.group(1)
        .strip()
    )

    return (
        found
        if found
        else None
    )


# =========================================================
# TEXT PROMPT CLAUSE
# =========================================================


def _text_clause(
    text: str | None,
) -> str:

    if not text:

        return ""

    return (
        " Render only the exact supplied text. "
        f'The exact text is: "{text}". '
        "Preserve spelling, capitalization, punctuation "
        "and spacing. Do not invent, duplicate, paraphrase "
        "or add any other words."
    )


# =========================================================
# NEGATIVE PROMPTS
# =========================================================


def _negative_prompt(
    kind: str,
) -> str:

    common = (
        "blurry, low resolution, distorted anatomy, "
        "duplicated objects, bad composition, cropped subject, "
        "watermark, signature, random typography, gibberish text, "
        "misspelled words"
    )

    if kind == "photo":

        return (
            f"{common}, plastic skin, oversharpening, "
            "artificial HDR"
        )

    if kind == "logo":

        return (
            f"{common}, gradients, photorealism, mockup, "
            "shadow, clutter"
        )

    if kind == "diagram":

        return (
            f"{common}, tangled connectors, "
            "unreadable labels, cluttered nodes"
        )

    return common


# =========================================================
# VISUAL PROMPT BUILDER
# =========================================================


def _build_visual_direction(
    *,
    request: str,
    kind: str,
    style: str,
    layout: str,
    palette: list[str],
    text: str | None,
) -> str:
    """
    Convert structured design intent into a strong
    generation prompt.
    """

    parts: list[str] = []

    parts.append(
        request
    )

    parts.append(
        f"Create a polished {kind} "
        f"in a {style} visual direction."
    )

    parts.append(
        f"Use a {layout} composition with "
        "strong visual hierarchy, balanced spacing, "
        "intentional alignment and a clear focal point."
    )

    # -----------------------------------------------------
    # Palette
    # -----------------------------------------------------

    if palette:

        parts.append(
            "Use a controlled color palette centered on "
            + ", ".join(palette)
            + "."
        )

    else:

        parts.append(
            "Use a restrained professional color palette "
            "with strong contrast and accessible visual hierarchy."
        )

    # -----------------------------------------------------
    # Typography
    # -----------------------------------------------------

    if text:

        parts.append(
            _text_clause(
                text
            )
        )

    # -----------------------------------------------------
    # Photo
    # -----------------------------------------------------

    if kind == "photo":

        parts.append(
            "Candid documentary photography, realistic "
            "natural lighting, authentic skin and material "
            "texture, physically plausible detail, 35mm lens "
            "character and subtle depth of field."
        )

    # -----------------------------------------------------
    # Illustration
    # -----------------------------------------------------

    elif kind == "illustration":

        parts.append(
            "Cohesive illustration, clear silhouette, "
            "deliberate shapes, layered depth and visually "
            "readable subject separation."
        )

    # -----------------------------------------------------
    # Marketing / graphic design
    # -----------------------------------------------------

    elif kind in {
        "poster",
        "banner",
        "social",
        "presentation",
    }:

        parts.append(
            "Premium graphic-design composition, generous "
            "whitespace, clear headline area, supporting "
            "visual hierarchy and professional marketing-art direction."
        )

    # -----------------------------------------------------
    # Logo
    # -----------------------------------------------------

    elif kind == "logo":

        parts.append(
            "Flat vector brand mark, simple geometric "
            "construction, strong silhouette, scalable "
            "iconography, crisp edges and memorable symbolism. "
            "Avoid unnecessary detail."
        )

    # -----------------------------------------------------
    # Diagram
    # -----------------------------------------------------

    elif kind == "diagram":

        parts.append(
            "Structured infographic aesthetic, clean node "
            "hierarchy, consistent spacing, clear grouping "
            "and simple geometric connectors."
        )

    return " ".join(
        parts
    )


# =========================================================
# PUBLIC PLANNER
# =========================================================


def build_image_prompt(
    user_request: str,
) -> dict[str, Any]:
    """
    Convert a raw user request into a normalized
    Canva-style image specification.

    This function does NOT call the image model.
    """

    request = " ".join(
        str(
            user_request or ""
        ).split()
    )

    if not request:

        raise ValueError(
            "Image request cannot be empty."
        )

    # -----------------------------------------------------
    # Core interpretation
    # -----------------------------------------------------

    kind = _detect_kind(
        request
    )

    text = extract_text(
        request
    )

    has_text = bool(
        text
    )

    ecosystem = any(
        term in request.lower()
        for term in ECOSYSTEM_TERMS
    )

    # -----------------------------------------------------
    # Canvas
    # -----------------------------------------------------

    format_key, format_spec = (
        _detect_format(
            request,
            kind,
        )
    )

    width = int(
        format_spec["width"]
    )

    height = int(
        format_spec["height"]
    )

    # -----------------------------------------------------
    # Visual properties
    # -----------------------------------------------------

    style = _detect_style(
        request,
        kind,
    )

    palette = _detect_palette(
        request
    )

    layout = _detect_layout(
        request,
        kind,
        has_text,
    )

    # -----------------------------------------------------
    # Generation engine
    # -----------------------------------------------------

    if kind == "diagram":

        engine = "svg"

    elif kind == "logo":

        engine = (
            "svg"
            if LOGO_ENGINE == "svg"
            else "image"
        )

    else:

        engine = "image"

    # -----------------------------------------------------
    # Text strategy
    # -----------------------------------------------------

    if kind in {
        "logo",
        "diagram",
    }:

        text_strategy = "structured"

    elif has_text:

        text_strategy = "text_aware_image"

    else:

        text_strategy = "image_only"

    # -----------------------------------------------------
    # Ecosystem context
    # -----------------------------------------------------

    ecosystem_context = (
        ECOSYSTEM_HUBS
        if ecosystem
        else ""
    )

    # -----------------------------------------------------
    # Main generation prompt
    # -----------------------------------------------------

    prompt = _build_visual_direction(
        request=request,
        kind=kind,
        style=style,
        layout=layout,
        palette=palette,
        text=text,
    )

    if ecosystem:

        prompt += (
            f" Brand ecosystem context: "
            f"{ecosystem_context}."
        )

    # -----------------------------------------------------
    # Final design specification
    # -----------------------------------------------------

    return {

        # =================================================
        # Original request
        # =================================================

        "request": request,

        # =================================================
        # Generation
        # =================================================

        "prompt": prompt,

        "negative_prompt": (
            _negative_prompt(
                kind
            )
        ),

        # =================================================
        # Artifact classification
        # =================================================

        "kind": kind,

        "engine": engine,

        "style": style,

        "layout": layout,

        "text_strategy": text_strategy,

        # =================================================
        # Typography
        # =================================================

        "text": text,

        "has_text": has_text,

        # =================================================
        # Brand / ecosystem
        # =================================================

        "domain": (
            "revelacode_ecosystem"
            if ecosystem
            else "general"
        ),

        "ecosystem": ecosystem,

        "ecosystem_context": ecosystem_context,

        # =================================================
        # Color
        # =================================================

        "palette": palette,

        # =================================================
        # Canvas
        # =================================================

        "format_key": format_key,

        "format_label": (
            format_spec["label"]
        ),

        "aspect_ratio": (
            format_spec["aspect_ratio"]
        ),

        "width": width,

        "height": height,

        "format": (
            f"{width}x{height}"
        ),

        # =================================================
        # Canva-style editing metadata
        # =================================================

        "safe_area": {
            "top": 0.08,
            "right": 0.08,
            "bottom": 0.08,
            "left": 0.08,
        },

        "editable": (
            kind != "photo"
        ),

        "requires_post_layout": (
            kind
            in {
                "logo",
                "diagram",
                "poster",
                "banner",
                "social",
                "presentation",
            }
        ),
    }


# =========================================================
# PUBLIC API
# =========================================================

__all__ = [
    "FORMAT_PRESETS",
    "ECOSYSTEM_TERMS",
    "ECOSYSTEM_HUBS",
    "extract_text",
    "build_image_prompt",
]
