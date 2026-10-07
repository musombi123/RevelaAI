"""
RevelaAI Structured SVG Designer.

This module is the structured-design engine for:
- logos
- diagrams
- branded cards
- simple posters
- typography-led graphics

Architecture:

    generate_svg()
          |
          +--> RevelaAI AI provider
          |       |
          |       +--> successful SVG
          |
          +--> local deterministic SVG fallback
                  |
                  +--> safe SVG

The AI provider is optional.

IMPORTANT:
- No scripts.
- No external resources.
- No event handlers.
- No remote images/fonts.
- User supplied text is never modified.
- SVGs are sanitized and validated before returning.
- Provider credit/network failures must not crash image generation.
"""

from __future__ import annotations

import hashlib
import logging
import re
import xml.etree.ElementTree as ET
from html import unescape
from typing import Any

from ai.ai_client import ask_hf


# =========================================================
# LOGGING
# =========================================================

logger = logging.getLogger(__name__)


# =========================================================
# SVG AI CONTRACT
# =========================================================

SVG_SYSTEM = """
You are RevelaAI's senior vector and brand designer.

Return ONLY one complete, valid SVG document.
Do not return markdown.
Do not return code fences.
Do not add explanations before or after the SVG.

PRIMARY GOAL
Create a polished, professional, editable vector composition suitable
for a Canva-style design editor.

HARD SVG RULES

1. Root:
   - <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024">
   - The viewBox must be exactly 0 0 1024 1024.

2. Allowed visual primitives:
   - <g>
   - <path>
   - <rect>
   - <circle>
   - <ellipse>
   - <line>
   - <polyline>
   - <polygon>
   - <text>
   - <tspan>

3. Do NOT use:
   - <script>
   - <foreignObject>
   - <iframe>
   - <object>
   - <embed>
   - <image>
   - external links
   - external fonts
   - CSS imports
   - javascript:
   - event handlers such as onclick/onload
   - filters
   - embedded HTML
   - data URLs

4. Prefer attributes directly on SVG elements.
   Avoid complex CSS.

5. Typography:
   - font-family="Arial, Helvetica, sans-serif"
     or
     font-family="Georgia, serif"
   - Use text-anchor="middle" when centered.
   - Keep text clearly separated from symbols.
   - Never allow text to overlap the primary symbol.

6. Design:
   - Strong visual hierarchy.
   - Clean geometry.
   - Balanced whitespace.
   - 2-3 dominant colors unless the request explicitly requires more.
   - Crisp, scalable forms.
   - Avoid meaningless decorative clutter.

7. User text:
   - When exact text is supplied, reproduce it EXACTLY.
   - Preserve capitalization.
   - Preserve punctuation.
   - Preserve spacing where practical.
   - Never invent additional words.
   - Never add slogans, labels, brand names, dates or captions that were
     not supplied.

8. Background:
   - Transparent unless the request explicitly asks for a background.
   - If a background is requested, keep it simple and intentional.

9. Keep the SVG compact and editable.
"""


# =========================================================
# CONSTANTS
# =========================================================

ROOT_VIEWBOX = "0 0 1024 1024"

SVG_NAMESPACE = "http://www.w3.org/2000/svg"

ALLOWED_TAGS = {
    "svg",
    "g",
    "path",
    "rect",
    "circle",
    "ellipse",
    "line",
    "polyline",
    "polygon",
    "text",
    "tspan",
}

DANGEROUS_TAGS = {
    "script",
    "foreignobject",
    "iframe",
    "object",
    "embed",
    "image",
    "audio",
    "video",
    "style",
    "link",
    "animate",
    "animatemotion",
    "animatetransform",
    "set",
    "filter",
}

DANGEROUS_PROTOCOLS = (
    "javascript:",
    "data:",
    "vbscript:",
    "file:",
)

EVENT_ATTRIBUTE_RE = re.compile(
    r"^on[a-z0-9_-]+$",
    re.I,
)

SAFE_URL_ATTRIBUTE_RE = re.compile(
    r"^(href|xlink:href|src)$",
    re.I,
)

CODE_FENCE_RE = re.compile(
    r"```(?:svg|xml)?\s*(.*?)```",
    re.S | re.I,
)

SVG_EXTRACT_RE = re.compile(
    r"<svg\b.*?</svg>",
    re.S | re.I,
)

CSS_URL_RE = re.compile(
    r"url\s*\(\s*[^)]+\)",
    re.I,
)

EXTERNAL_REFERENCE_RE = re.compile(
    r"(?:https?://|//|javascript:|data:|file:)",
    re.I,
)


# =========================================================
# XML HELPERS
# =========================================================


def _local_name(tag: str) -> str:
    """Return an XML local tag name without a namespace."""

    if "}" in tag:
        return tag.rsplit("}", 1)[1]

    return tag


def _text_content(element: ET.Element) -> str:
    """Collect text content from an element and descendants."""

    chunks: list[str] = []

    if element.text:
        chunks.append(element.text)

    for child in list(element):

        if child.tail:
            chunks.append(child.tail)

        chunks.append(
            _text_content(child)
        )

    return "".join(chunks)


def _normalize_rendered_text(value: str) -> str:
    """
    Normalize SVG text only for validation.

    The actual SVG output is not modified.
    """

    return re.sub(
        r"\s+",
        " ",
        unescape(value or ""),
    ).strip()


# =========================================================
# REQUEST HELPERS
# =========================================================


def _build_design_brief(
    request: str | dict[str, Any],
    text: str | None = None,
) -> tuple[str, str | None]:
    """
    Build the AI brief from either:
    - a simple request string
    - the normalized image planner specification
    """

    if isinstance(request, dict):

        spec = request

        base = str(
            spec.get("request")
            or spec.get("prompt")
            or ""
        ).strip()

        inferred_text = spec.get("text")

        if text is not None:
            exact_text = str(text)

        elif inferred_text is not None:
            exact_text = str(inferred_text)

        else:
            exact_text = None

        metadata: list[str] = []

        for key in (
            "kind",
            "style",
            "layout",
            "aspect_ratio",
            "format",
        ):

            value = spec.get(key)

            if value:
                metadata.append(
                    f"{key}={value}"
                )

        palette = spec.get("palette")

        if (
            isinstance(palette, list)
            and palette
        ):

            metadata.append(
                "palette="
                + ", ".join(
                    map(
                        str,
                        palette[:3],
                    )
                )
            )

        if metadata:

            base += (
                "\nDesign specification: "
                + "; ".join(metadata)
            )

    else:

        base = str(
            request or ""
        ).strip()

        exact_text = (
            str(text)
            if text is not None
            else None
        )

    if not base:

        raise ValueError(
            "SVG design request cannot be empty."
        )

    if exact_text is not None:

        base += (
            "\nEXACT TEXT TO RENDER: "
            f'"{exact_text}"'
            "\nDO NOT ADD ANY OTHER TEXT."
        )

    return (
        base,
        exact_text,
    )


def _request_spec(
    request: str | dict[str, Any],
    text: str | None = None,
) -> dict[str, Any]:
    """
    Normalize a design request into a predictable dictionary.

    This is intentionally lightweight so it remains compatible with
    the existing image planner.
    """

    if isinstance(request, dict):

        spec = dict(request)

    else:

        spec = {
            "request": str(
                request or ""
            )
        }

    if text is not None:
        spec["text"] = text

    return spec


# =========================================================
# SVG SANITIZATION
# =========================================================


def _sanitize_attributes(
    element: ET.Element,
) -> None:
    """Remove unsafe or external attributes."""

    for attribute in list(
        element.attrib
    ):

        local_attribute = _local_name(
            attribute
        )

        value = str(
            element.attrib.get(
                attribute,
                "",
            )
        )

        # -------------------------------------------------
        # Event handlers
        # -------------------------------------------------

        if EVENT_ATTRIBUTE_RE.match(
            local_attribute
        ):

            del element.attrib[
                attribute
            ]

            continue

        # -------------------------------------------------
        # External URL references
        # -------------------------------------------------

        if SAFE_URL_ATTRIBUTE_RE.match(
            local_attribute
        ):

            lowered = (
                value.strip().lower()
            )

            if any(
                lowered.startswith(
                    protocol
                )
                for protocol in DANGEROUS_PROTOCOLS
            ):

                del element.attrib[
                    attribute
                ]

                continue

        # -------------------------------------------------
        # Any external reference
        # -------------------------------------------------

        if EXTERNAL_REFERENCE_RE.search(
            value
        ):

            del element.attrib[
                attribute
            ]

            continue

        # -------------------------------------------------
        # Unsafe CSS URL
        # -------------------------------------------------

        if (
            "url(" in value.lower()
            and CSS_URL_RE.search(
                value
            )
        ):

            del element.attrib[
                attribute
            ]


def _sanitize_tree(
    root: ET.Element,
) -> ET.Element:
    """
    Recursively retain only safe SVG elements.
    """

    root_name = _local_name(
        root.tag
    ).lower()

    if root_name != "svg":

        raise ValueError(
            "SVG root element is invalid."
        )

    # -----------------------------------------------------
    # Normalize root
    # -----------------------------------------------------

    root.tag = "svg"

    root.attrib[
        "xmlns"
    ] = SVG_NAMESPACE

    root.attrib[
        "viewBox"
    ] = ROOT_VIEWBOX

    _sanitize_attributes(
        root
    )

    # -----------------------------------------------------
    # Root attributes
    # -----------------------------------------------------

    allowed_root_attributes = {
        "xmlns",
        "viewBox",
        "width",
        "height",
        "preserveAspectRatio",
        "fill",
        "stroke",
        "stroke-width",
        "stroke-linecap",
        "stroke-linejoin",
        "text-anchor",
        "font-family",
        "font-size",
        "font-weight",
    }

    normalized_allowed = {
        _local_name(item)
        for item in allowed_root_attributes
    }

    for attribute in list(
        root.attrib
    ):

        local_attribute = _local_name(
            attribute
        )

        if local_attribute not in (
            normalized_allowed
        ):

            if local_attribute == "xmlns":
                continue

            del root.attrib[
                attribute
            ]

    # -----------------------------------------------------
    # Recursive filtering
    # -----------------------------------------------------

    def clean_children(
        parent: ET.Element,
    ) -> None:

        for child in list(parent):

            child_name = (
                _local_name(
                    child.tag
                ).lower()
            )

            if (
                child_name
                in DANGEROUS_TAGS
                or child_name
                not in ALLOWED_TAGS
            ):

                parent.remove(
                    child
                )

                continue

            child.tag = child_name

            _sanitize_attributes(
                child
            )

            clean_children(
                child
            )

    clean_children(
        root
    )

    return root


# =========================================================
# SVG VALIDATION
# =========================================================


def _validate_svg_root(
    root: ET.Element,
) -> None:

    if root.tag != "svg":

        raise ValueError(
            "SVG root element is invalid."
        )

    if root.attrib.get(
        "viewBox"
    ) != ROOT_VIEWBOX:

        raise ValueError(
            (
                "SVG viewBox must be "
                f'"{ROOT_VIEWBOX}".'
            )
        )


def _validate_requested_text(
    root: ET.Element,
    expected_text: str | None,
) -> None:
    """
    Ensure the model did not silently change
    or invent text.

    When expected text is supplied:
        all rendered text must equal that text.
    """

    if expected_text is None:
        return

    rendered: list[str] = []

    for element in root.iter():

        if (
            _local_name(
                element.tag
            ).lower()
            == "text"
        ):

            rendered.append(
                _text_content(
                    element
                )
            )

    actual = (
        _normalize_rendered_text(
            " ".join(rendered)
        )
    )

    expected = (
        _normalize_rendered_text(
            expected_text
        )
    )

    if actual != expected:

        raise ValueError(
            (
                "Generated SVG text does not "
                "exactly match the requested text. "
                f'Expected="{expected}" '
                f'Actual="{actual}"'
            )
        )


def _validate_svg(
    root: ET.Element,
    expected_text: str | None = None,
) -> None:

    _validate_svg_root(
        root
    )

    for element in root.iter():

        name = _local_name(
            element.tag
        ).lower()

        if name not in ALLOWED_TAGS:

            raise ValueError(
                f"Unsupported SVG element: {name}"
            )

        for attribute, value in (
            element.attrib.items()
        ):

            local_attribute = (
                _local_name(
                    attribute
                )
            )

            if EVENT_ATTRIBUTE_RE.match(
                local_attribute
            ):

                raise ValueError(
                    (
                        "Unsafe SVG event "
                        f"attribute: {attribute}"
                    )
                )

            if EXTERNAL_REFERENCE_RE.search(
                str(value)
            ):

                raise ValueError(
                    "SVG contains an external reference."
                )

    _validate_requested_text(
        root,
        expected_text,
    )


# =========================================================
# SERIALIZATION
# =========================================================


def _serialize_svg(
    root: ET.Element,
) -> str:

    raw = ET.tostring(
        root,
        encoding="unicode",
        short_empty_elements=True,
    )

    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        + raw
    )


# =========================================================
# PUBLIC SANITIZER
# =========================================================


def sanitize_svg(
    raw: str,
    *,
    expected_text: str | None = None,
) -> str:
    """
    Extract, sanitize and validate an SVG document.

    Raises:
        ValueError for malformed or unsafe SVG.
    """

    raw = str(
        raw or ""
    ).strip()

    if not raw:

        raise ValueError(
            "The model returned an empty SVG."
        )

    # -----------------------------------------------------
    # Remove markdown fences
    # -----------------------------------------------------

    fenced = CODE_FENCE_RE.search(
        raw
    )

    if fenced:

        raw = fenced.group(
            1
        ).strip()

    # -----------------------------------------------------
    # Extract SVG
    # -----------------------------------------------------

    match = SVG_EXTRACT_RE.search(
        raw
    )

    if not match:

        raise ValueError(
            "The model did not return an SVG."
        )

    svg_text = match.group(
        0
    ).strip()

    # -----------------------------------------------------
    # Reject obvious external resources
    # -----------------------------------------------------

    if EXTERNAL_REFERENCE_RE.search(
        svg_text
    ):

        raise ValueError(
            "SVG contains an external reference."
        )

    # -----------------------------------------------------
    # XML parsing
    # -----------------------------------------------------

    try:

        root = ET.fromstring(
            svg_text
        )

    except ET.ParseError as exc:

        raise ValueError(
            "The generated SVG is not valid XML."
        ) from exc

    # -----------------------------------------------------
    # Sanitization
    # -----------------------------------------------------

    root = _sanitize_tree(
        root
    )

    # -----------------------------------------------------
    # Validation
    # -----------------------------------------------------

    _validate_svg(
        root,
        expected_text=expected_text,
    )

    # -----------------------------------------------------
    # Final serialization
    # -----------------------------------------------------

    return _serialize_svg(
        root
    )


# =========================================================
# LOCAL DESIGN HELPERS
# =========================================================


def _stable_palette(
    spec: dict[str, Any],
) -> tuple[str, str, str]:
    """
    Resolve a deterministic 3-color palette.

    Explicit planner palettes win.

    Otherwise the request gets a stable palette derived from
    its content so the same request produces the same fallback.
    """

    palette = spec.get(
        "palette"
    )

    if isinstance(
        palette,
        list,
    ):

        cleaned = [
            str(item).strip()
            for item in palette
            if str(item).strip()
        ]

        if len(cleaned) >= 3:

            return (
                cleaned[0],
                cleaned[1],
                cleaned[2],
            )

        if len(cleaned) == 2:

            return (
                cleaned[0],
                cleaned[1],
                "#111827",
            )

        if len(cleaned) == 1:

            return (
                cleaned[0],
                "#111827",
                "#FFFFFF",
            )

    request_text = (
        str(
            spec.get("request")
            or spec.get("prompt")
            or ""
        )
        .lower()
    )

    # -----------------------------------------------------
    # Domain-specific fallback palettes
    # -----------------------------------------------------

    if any(
        word in request_text
        for word in (
            "shamba",
            "farm",
            "agriculture",
            "crop",
            "agro",
            "leaf",
        )
    ):

        return (
            "#15803D",
            "#84CC16",
            "#0F172A",
        )

    if any(
        word in request_text
        for word in (
            "biashara",
            "business",
            "market",
            "commerce",
            "shop",
        )
    ):

        return (
            "#2563EB",
            "#0F172A",
            "#38BDF8",
        )

    if any(
        word in request_text
        for word in (
            "elimu",
            "education",
            "school",
            "learning",
            "teacher",
        )
    ):

        return (
            "#7C3AED",
            "#2563EB",
            "#111827",
        )

    if any(
        word in request_text
        for word in (
            "community",
            "jumuiya",
            "social",
            "people",
        )
    ):

        return (
            "#0F766E",
            "#14B8A6",
            "#0F172A",
        )

    if any(
        word in request_text
        for word in (
            "scripture",
            "bible",
            "theology",
            "faith",
            "church",
        )
    ):

        return (
            "#92400E",
            "#D97706",
            "#1F2937",
        )

    if any(
        word in request_text
        for word in (
            "programming",
            "developer",
            "software",
            "code",
            "technology",
            "tech",
        )
    ):

        return (
            "#06B6D4",
            "#2563EB",
            "#0F172A",
        )

    # -----------------------------------------------------
    # Stable generic palette
    # -----------------------------------------------------

    digest = hashlib.sha256(
        request_text.encode(
            "utf-8"
        )
    ).hexdigest()

    palettes = (
        (
            "#2563EB",
            "#7C3AED",
            "#111827",
        ),
        (
            "#0F766E",
            "#0891B2",
            "#111827",
        ),
        (
            "#DB2777",
            "#7C3AED",
            "#111827",
        ),
        (
            "#EA580C",
            "#F59E0B",
            "#111827",
        ),
    )

    index = int(
        digest[:8],
        16,
    ) % len(palettes)

    return palettes[index]


def _svg_root() -> ET.Element:
    """Create the canonical RevelaAI SVG root."""

    return ET.Element(
        "svg",
        {
            "xmlns": SVG_NAMESPACE,
            "viewBox": ROOT_VIEWBOX,
        },
    )


def _add(
    parent: ET.Element,
    tag: str,
    **attributes: Any,
) -> ET.Element:
    """Small safe SVG element factory."""

    cleaned = {
        key: str(value)
        for key, value in attributes.items()
        if value is not None
    }

    return ET.SubElement(
        parent,
        tag,
        cleaned,
    )


def _add_text(
    root: ET.Element,
    value: str,
    *,
    x: int = 512,
    y: int = 780,
    font_size: int = 82,
    fill: str = "#111827",
    font_weight: str = "700",
) -> None:
    """
    Add only explicitly requested user text.

    This function must never invent words.
    """

    _add(
        root,
        "text",
        x=x,
        y=y,
        fill=fill,
        **{
            "font-family": "Arial, Helvetica, sans-serif",
            "font-size": font_size,
            "font-weight": font_weight,
            "text-anchor": "middle",
        },
    ).text = value


# =========================================================
# LOCAL SYMBOLS
# =========================================================


def _draw_leaf(
    root: ET.Element,
    primary: str,
    secondary: str,
) -> None:
    """Clean agricultural leaf mark."""

    group = _add(
        root,
        "g",
    )

    _add(
        group,
        "path",
        d=(
            "M512 150 "
            "C390 190 315 285 330 400 "
            "C345 515 435 565 512 585 "
            "C589 565 679 515 694 400 "
            "C709 285 634 190 512 150 Z"
        ),
        fill=primary,
    )

    _add(
        group,
        "path",
        d=(
            "M512 205 "
            "C500 300 500 400 512 540"
        ),
        fill="none",
        stroke="#FFFFFF",
        **{
            "stroke-width": "18",
            "stroke-linecap": "round",
        },
    )

    _add(
        group,
        "path",
        d=(
            "M505 320 "
            "C455 300 410 275 370 235"
        ),
        fill="none",
        stroke="#FFFFFF",
        **{
            "stroke-width": "14",
            "stroke-linecap": "round",
        },
    )

    _add(
        group,
        "path",
        d=(
            "M519 390 "
            "C570 365 620 330 655 285"
        ),
        fill="none",
        stroke="#FFFFFF",
        **{
            "stroke-width": "14",
            "stroke-linecap": "round",
        },
    )

    _add(
        group,
        "circle",
        cx=512,
        cy=570,
        r=28,
        fill=secondary,
    )


def _draw_business(
    root: ET.Element,
    primary: str,
    secondary: str,
) -> None:
    """Modern commerce / business symbol."""

    group = _add(
        root,
        "g",
    )

    _add(
        group,
        "rect",
        x=270,
        y=330,
        width=484,
        height=310,
        rx=48,
        fill=primary,
    )

    _add(
        group,
        "rect",
        x=350,
        y=250,
        width=324,
        height=110,
        rx=28,
        fill=secondary,
    )

    _add(
        group,
        "rect",
        x=330,
        y=430,
        width=82,
        height=135,
        rx=18,
        fill="#FFFFFF",
    )

    _add(
        group,
        "rect",
        x=471,
        y=390,
        width=82,
        height=175,
        rx=18,
        fill="#FFFFFF",
    )

    _add(
        group,
        "rect",
        x=612,
        y=345,
        width=82,
        height=220,
        rx=18,
        fill="#FFFFFF",
    )


def _draw_education(
    root: ET.Element,
    primary: str,
    secondary: str,
) -> None:
    """Simple open-book education mark."""

    group = _add(
        root,
        "g",
    )

    _add(
        group,
        "path",
        d=(
            "M512 315 "
            "C430 270 350 270 275 315 "
            "L275 650 "
            "C355 605 430 605 512 650 Z"
        ),
        fill=primary,
    )

    _add(
        group,
        "path",
        d=(
            "M512 315 "
            "C594 270 674 270 749 315 "
            "L749 650 "
            "C669 605 594 605 512 650 Z"
        ),
        fill=secondary,
    )

    _add(
        group,
        "line",
        x1=512,
        y1=315,
        x2=512,
        y2=650,
        stroke="#FFFFFF",
        **{
            "stroke-width": "18",
        },
    )


def _draw_community(
    root: ET.Element,
    primary: str,
    secondary: str,
) -> None:
    """Three-person community symbol."""

    group = _add(
        root,
        "g",
    )

    _add(
        group,
        "circle",
        cx=512,
        cy=300,
        r=88,
        fill=primary,
    )

    _add(
        group,
        "circle",
        cx=320,
        cy=390,
        r=68,
        fill=secondary,
    )

    _add(
        group,
        "circle",
        cx=704,
        cy=390,
        r=68,
        fill=secondary,
    )

    _add(
        group,
        "path",
        d=(
            "M380 680 "
            "C385 520 420 445 512 445 "
            "C604 445 639 520 644 680 Z"
        ),
        fill=primary,
    )

    _add(
        group,
        "path",
        d=(
            "M210 680 "
            "C215 555 245 500 320 500 "
            "C365 500 397 525 420 575 "
            "L420 680 Z"
        ),
        fill=secondary,
    )

    _add(
        group,
        "path",
        d=(
            "M604 575 "
            "C627 525 659 500 704 500 "
            "C779 500 809 555 814 680 "
            "L604 680 Z"
        ),
        fill=secondary,
    )


def _draw_scripture(
    root: ET.Element,
    primary: str,
    secondary: str,
) -> None:
    """Simple scripture / faith mark."""

    group = _add(
        root,
        "g",
    )

    _add(
        group,
        "rect",
        x=330,
        y=300,
        width=364,
        height=370,
        rx=32,
        fill="#FFFFFF",
        stroke=primary,
        **{
            "stroke-width": "22",
        },
    )

    _add(
        group,
        "line",
        x1=512,
        y1=320,
        x2=512,
        y2=650,
        stroke=primary,
        **{
            "stroke-width": "14",
        },
    )

    _add(
        group,
        "line",
        x1=425,
        y1=410,
        x2=425,
        y2=520,
        stroke=secondary,
        **{
            "stroke-width": "20",
            "stroke-linecap": "round",
        },
    )

    _add(
        group,
        "line",
        x1=370,
        y1=465,
        x2=480,
        y2=465,
        stroke=secondary,
        **{
            "stroke-width": "20",
            "stroke-linecap": "round",
        },
    )


def _draw_programming(
    root: ET.Element,
    primary: str,
    secondary: str,
) -> None:
    """Developer / programming symbol."""

    group = _add(
        root,
        "g",
    )

    _add(
        group,
        "polyline",
        points="455,310 315,500 455,690",
        fill="none",
        stroke=primary,
        **{
            "stroke-width": "48",
            "stroke-linecap": "round",
            "stroke-linejoin": "round",
        },
    )

    _add(
        group,
        "polyline",
        points="569,310 709,500 569,690",
        fill="none",
        stroke=secondary,
        **{
            "stroke-width": "48",
            "stroke-linecap": "round",
            "stroke-linejoin": "round",
        },
    )

    _add(
        group,
        "line",
        x1=545,
        y1=275,
        x2=479,
        y2=725,
        stroke="#111827",
        **{
            "stroke-width": "38",
            "stroke-linecap": "round",
        },
    )


def _draw_generic(
    root: ET.Element,
    primary: str,
    secondary: str,
) -> None:
    """Professional abstract fallback symbol."""

    group = _add(
        root,
        "g",
    )

    _add(
        group,
        "circle",
        cx=512,
        cy=480,
        r=220,
        fill="none",
        stroke=primary,
        **{
            "stroke-width": "52",
        },
    )

    _add(
        group,
        "polygon",
        points="512,245 680,555 344,555",
        fill=secondary,
    )

    _add(
        group,
        "circle",
        cx=512,
        cy=480,
        r=72,
        fill="#FFFFFF",
    )


# =========================================================
# LOCAL SVG FALLBACK
# =========================================================


def _local_svg_fallback(
    request: str | dict[str, Any],
    *,
    text: str | None = None,
) -> str:
    """
    Deterministic local SVG designer.

    This is intentionally independent of:
    - Hugging Face
    - external APIs
    - model downloads
    - network access
    - image generation providers

    It guarantees that simple vector requests can still produce
    a valid asset when the remote AI provider is unavailable.
    """

    spec = _request_spec(
        request,
        text,
    )

    request_text = str(
        spec.get("request")
        or spec.get("prompt")
        or ""
    ).strip()

    exact_text = (
        str(spec["text"])
        if spec.get("text") is not None
        else None
    )

    kind = str(
        spec.get("kind")
        or ""
    ).lower()

    style = str(
        spec.get("style")
        or ""
    ).lower()

    layout = str(
        spec.get("layout")
        or ""
    ).lower()

    primary, secondary, dark = (
        _stable_palette(
            spec
        )
    )

    root = _svg_root()

    # -----------------------------------------------------
    # Optional explicit background
    # -----------------------------------------------------

    background_requested = any(
        word in (
            request_text
            + " "
            + style
        ).lower()
        for word in (
            "background",
            "solid background",
            "colored background",
        )
    )

    if background_requested:

        _add(
            root,
            "rect",
            x=0,
            y=0,
            width=1024,
            height=1024,
            fill="#FFFFFF",
        )

    # -----------------------------------------------------
    # Determine visual family
    # -----------------------------------------------------

    normalized = (
        request_text
        + " "
        + kind
        + " "
        + style
        + " "
        + layout
    ).lower()

    if any(
        word in normalized
        for word in (
            "shamba",
            "farm",
            "agriculture",
            "crop",
            "agro",
            "leaf",
        )
    ):

        _draw_leaf(
            root,
            primary,
            secondary,
        )

    elif any(
        word in normalized
        for word in (
            "biashara",
            "business",
            "market",
            "commerce",
            "shop",
        )
    ):

        _draw_business(
            root,
            primary,
            secondary,
        )

    elif any(
        word in normalized
        for word in (
            "elimu",
            "education",
            "school",
            "learning",
            "teacher",
        )
    ):

        _draw_education(
            root,
            primary,
            secondary,
        )

    elif any(
        word in normalized
        for word in (
            "community",
            "jumuiya",
            "social",
            "people",
        )
    ):

        _draw_community(
            root,
            primary,
            secondary,
        )

    elif any(
        word in normalized
        for word in (
            "scripture",
            "bible",
            "theology",
            "faith",
            "church",
        )
    ):

        _draw_scripture(
            root,
            primary,
            secondary,
        )

    elif any(
        word in normalized
        for word in (
            "programming",
            "developer",
            "software",
            "code",
            "technology",
            "tech",
        )
    ):

        _draw_programming(
            root,
            primary,
            secondary,
        )

    else:

        _draw_generic(
            root,
            primary,
            secondary,
        )

    # -----------------------------------------------------
    # User text
    #
    # IMPORTANT:
    # Never invent fallback text.
    # -----------------------------------------------------

    if exact_text is not None:

        text_size = 82

        # Long text gets progressively smaller so the
        # deterministic fallback remains usable.
        text_length = len(
            exact_text
        )

        if text_length > 24:
            text_size = 62

        if text_length > 36:
            text_size = 48

        if text_length > 52:
            text_size = 38

        # Default logo composition:
        # symbol above, exact user text below.
        _add_text(
            root,
            exact_text,
            y=800,
            font_size=text_size,
            fill=dark,
        )

    # -----------------------------------------------------
    # Final sanitize + validate
    # -----------------------------------------------------

    return sanitize_svg(
        _serialize_svg(root),
        expected_text=exact_text,
    )


# =========================================================
# PROVIDER ERROR CLASSIFICATION
# =========================================================


def _provider_error_is_fallbackable(
    result: dict[str, Any],
) -> bool:
    """
    Determine whether the remote provider failure should trigger
    local SVG generation.

    Expected cases include:
    - no HF credits
    - HTTP 402
    - authentication failure
    - rate limits
    - provider unavailable
    - provider timeout
    - upstream 5xx
    """

    if not isinstance(
        result,
        dict,
    ):
        return True

    status = result.get(
        "status"
    )

    error = str(
        result.get(
            "error"
        )
        or ""
    ).lower()

    status_text = str(
        status
        or ""
    ).lower()

    combined = (
        f"{status_text} {error}"
    )

    fallback_markers = (
        "402",
        "401",
        "403",
        "408",
        "409",
        "429",
        "500",
        "502",
        "503",
        "504",
        "credit",
        "credits",
        "pre-paid",
        "prepaid",
        "remaining credits",
        "inference provider",
        "rate limit",
        "rate-limit",
        "timeout",
        "timed out",
        "temporarily unavailable",
        "service unavailable",
        "upstream",
        "connection",
        "network",
    )

    return any(
        marker in combined
        for marker in fallback_markers
    )


# =========================================================
# AI SVG GENERATION
# =========================================================


def _generate_ai_svg(
    brief: str,
    *,
    expected_text: str | None,
) -> str:
    """
    Ask the configured AI provider for SVG and sanitize it.

    Provider failures are converted to RuntimeError so the public
    generate_svg() function can decide whether to use local fallback.
    """

    result = ask_hf(
        text=brief,
        system_prompt=SVG_SYSTEM,
    )

    if not isinstance(
        result,
        dict,
    ):

        raise RuntimeError(
            "SVG AI provider returned an invalid response."
        )

    if not result.get(
        "success"
    ):

        error = (
            result.get(
                "error"
            )
            or "SVG generation failed."
        )

        status = result.get(
            "status"
        )

        if status:

            raise RuntimeError(
                f"SVG provider error "
                f"(status={status}): {error}"
            )

        raise RuntimeError(
            f"SVG provider error: {error}"
        )

    raw_svg = result.get(
        "response"
    )

    if not raw_svg:

        raise RuntimeError(
            "SVG generation returned no content."
        )

    return sanitize_svg(
        raw_svg,
        expected_text=expected_text,
    )


def generate_svg(
    request: str | dict[str, Any],
    text: str | None = None,
) -> str:
    """
    Generate a structured SVG.

    Provider strategy:

        1. Try RevelaAI AI provider.
        2. Sanitize and validate AI SVG.
        3. If provider credits/network/rate-limit/etc. fail,
           use deterministic local SVG generation.
        4. Return a valid sanitized SVG.

    Backward compatible:

        generate_svg(
            "Create a modern logo",
            text="RevelaAI",
        )

    Planner compatible:

        generate_svg(
            build_image_prompt(request)
        )
    """

    brief, exact_text = (
        _build_design_brief(
            request,
            text,
        )
    )

    # -----------------------------------------------------
    # AI-FIRST
    # -----------------------------------------------------

    try:

        svg = _generate_ai_svg(
            brief,
            expected_text=exact_text,
        )

        logger.info(
            "SVG generation succeeded using AI provider."
        )

        return svg

    except Exception as exc:

        error_message = str(
            exc
        )

        # -------------------------------------------------
        # Expected provider failure:
        # use local deterministic SVG.
        # -------------------------------------------------

        provider_result = {
            "error": error_message,
        }

        if _provider_error_is_fallbackable(
            provider_result
        ):

            logger.warning(
                "SVG AI provider unavailable; "
                "using deterministic local fallback. "
                "error=%s",
                error_message,
            )

            try:

                return _local_svg_fallback(
                    request,
                    text=exact_text,
                )

            except Exception as fallback_exc:

                logger.exception(
                    "Local SVG fallback failed. "
                    "error=%s",
                    fallback_exc,
                )

                raise RuntimeError(
                    (
                        "Both AI SVG generation and "
                        "local SVG fallback failed."
                    )
                ) from fallback_exc

        # -------------------------------------------------
        # Non-provider SVG failure.
        #
        # Still attempt local fallback because malformed
        # model output should not take down image generation.
        # -------------------------------------------------

        logger.warning(
            "SVG AI generation failed; "
            "attempting local deterministic fallback. "
            "error=%s",
            error_message,
        )

        try:

            return _local_svg_fallback(
                request,
                text=exact_text,
            )

        except Exception as fallback_exc:

            logger.exception(
                "Local SVG fallback failed. "
                "error=%s",
                fallback_exc,
            )

            raise RuntimeError(
                (
                    "SVG generation failed and "
                    "local fallback was unable to "
                    "produce a valid SVG."
                )
            ) from fallback_exc


# =========================================================
# PUBLIC API
# =========================================================

__all__ = [
    "SVG_SYSTEM",
    "sanitize_svg",
    "generate_svg",
]
