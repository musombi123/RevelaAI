"""
RevelaAI Structured SVG Designer.

This module is the structured-design engine for:
- logos
- diagrams
- branded cards
- simple posters
- typography-led graphics

It uses RevelaAI text generation to create SVG source, then applies
strict sanitization and validation before returning it.

IMPORTANT:
- No scripts.
- No external resources.
- No event handlers.
- No remote images/fonts.
- User supplied text is never modified.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from html import unescape
from typing import Any

from ai.ai_client import ask_hf


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


def _text_content(
    element: ET.Element,
) -> str:
    """Collect text content from an element and descendants."""

    chunks: list[str] = []

    if element.text:
        chunks.append(
            element.text
        )

    for child in list(element):

        if child.tail:
            chunks.append(
                child.tail
            )

        chunks.append(
            _text_content(
                child
            )
        )

    return "".join(
        chunks
    )


def _normalize_rendered_text(
    value: str,
) -> str:
    """
    Normalize SVG text only for validation.

    The actual SVG output is not modified.
    """

    return re.sub(
        r"\s+",
        " ",
        unescape(
            value or ""
        ),
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

    if isinstance(
        request,
        dict,
    ):

        spec = request

        base = str(
            spec.get("request")
            or spec.get("prompt")
            or ""
        ).strip()

        inferred_text = spec.get(
            "text"
        )

        if text is not None:

            exact_text = str(
                text
            )

        elif inferred_text:

            exact_text = str(
                inferred_text
            )

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

            value = spec.get(
                key
            )

            if value:

                metadata.append(
                    f"{key}={value}"
                )

        palette = spec.get(
            "palette"
        )

        if (
            isinstance(
                palette,
                list,
            )
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
                + "; ".join(
                    metadata
                )
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

    if exact_text:

        base += (
            "\nEXACT TEXT TO RENDER: "
            f'"{exact_text}"'
            "\nDO NOT ADD ANY OTHER TEXT."
        )

    return (
        base,
        exact_text,
    )


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

        local_attribute = (
            _local_name(
                attribute
            )
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
    ] = "http://www.w3.org/2000/svg"

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
        _local_name(
            item
        )
        for item in allowed_root_attributes
    }

    for attribute in list(
        root.attrib
    ):

        local_attribute = (
            _local_name(
                attribute
            )
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

        for child in list(
            parent
        ):

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
            " ".join(
                rendered
            )
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
# AI SVG GENERATION
# =========================================================


def generate_svg(
    request: str | dict[str, Any],
    text: str | None = None,
) -> str:
    """
    Generate a structured SVG.

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

    result = ask_hf(
        text=brief,
        system_prompt=SVG_SYSTEM,
    )

    if not result.get(
        "success"
    ):

        raise RuntimeError(
            result.get(
                "error"
            )
            or "SVG generation failed."
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
        expected_text=exact_text,
    )


# =========================================================
# PUBLIC API
# =========================================================

__all__ = [
    "SVG_SYSTEM",
    "sanitize_svg",
    "generate_svg",
]
