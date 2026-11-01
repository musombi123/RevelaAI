"""Framework-neutral image planning and asset-generation service."""
from __future__ import annotations

import logging
import os
import uuid
from typing import Any

from ai.ai_client import generate_hf_image
from ai.image_prompt import build_image_prompt
from ai.svg_designer import generate_svg
from services.runtime_config import IMAGE_DIR, REVELAAI_IMAGE_ENGINE_VERSION
from services.ai_service import detect_capability

logger = logging.getLogger("revelaai.image_service")


def is_image_generation_request(message: str) -> bool:
    return (
        detect_capability(str(message or ""), intent="general")
        == "image_generation"
    )


def _optional_int(
    value: Any,
    label: str,
) -> int | None:

    if value is None:

        return None

    if isinstance(
        value,
        str,
    ):

        value = value.strip()

        if not value:

            return None

    try:

        return int(
            value
        )

    except (
        TypeError,
        ValueError,
    ) as exc:

        raise ValueError(
            f"Image {label} must be an integer."
        ) from exc


def parse_image_options(
    source: Any,
) -> dict[str, Any]:

    if not isinstance(
        source,
        dict,
    ):

        return {}

    options: dict[str, Any] = {}

    aspect_ratio = (
        source.get(
            "aspect_ratio"
        )
        or source.get(
            "image_aspect_ratio"
        )
        or ""
    )

    aspect_ratio = str(
        aspect_ratio
    ).strip().lower()

    if aspect_ratio:

        options[
            "aspect_ratio"
        ] = aspect_ratio

    width = _optional_int(
        source.get(
            "width"
        ),
        "width",
    )

    height = _optional_int(
        source.get(
            "height"
        ),
        "height",
    )

    seed = _optional_int(
        source.get(
            "seed"
        ),
        "seed",
    )

    if width is not None:

        options[
            "width"
        ] = width

    if height is not None:

        options[
            "height"
        ] = height

    if seed is not None:

        options[
            "seed"
        ] = seed

    return options


def _save_svg_asset(
    svg: str,
) -> tuple[str, str]:

    filename = (
        "revelaai_"
        f"{uuid.uuid4().hex}.svg"
    )

    filepath = os.path.join(
        IMAGE_DIR,
        filename,
    )

    with open(
        filepath,
        "w",
        encoding="utf-8",
    ) as handle:

        handle.write(
            svg
        )

    return (
        filename,
        filepath,
    )


def _save_raster_asset(
    image: Any,
) -> tuple[str, str]:

    filename = (
        "revelaai_"
        f"{uuid.uuid4().hex}.png"
    )

    filepath = os.path.join(
        IMAGE_DIR,
        filename,
    )

    image.save(
        filepath,
        format="PNG",
    )

    return (
        filename,
        filepath,
    )


def generate_image_asset(
    message: str,
    *,
    image_options: dict[str, Any] | None = None,
    request_base_url: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """
    Generate one image/design asset.

    Planner determines:
        - prompt
        - kind
        - engine
        - layout
        - style
        - dimensions
        - text awareness

    ai.ai_client.py owns provider/model routing.
    """

    options = (
        image_options
        if isinstance(
            image_options,
            dict,
        )
        else {}
    )

    image_plan = build_image_prompt(
        message
    )

    if not isinstance(
        image_plan,
        dict,
    ):

        raise RuntimeError(
            "Image planner returned an invalid plan."
        )

    requested_aspect_ratio = (
        options.get(
            "aspect_ratio"
        )
    )

    requested_width = (
        options.get(
            "width"
        )
    )

    requested_height = (
        options.get(
            "height"
        )
    )

    requested_seed = (
        options.get(
            "seed"
        )
    )

    aspect_ratio = (
        requested_aspect_ratio
        or image_plan.get(
            "aspect_ratio"
        )
    )

    width = (
        requested_width
        if requested_width is not None
        else image_plan.get(
            "width"
        )
    )

    height = (
        requested_height
        if requested_height is not None
        else image_plan.get(
            "height"
        )
    )

    logger.info(
        "IMAGE PROMPT PLANNED | "
        "request_id=%s | kind=%s | engine=%s | "
        "style=%s | layout=%s | text=%s | "
        "aspect=%s | size=%sx%s",
        request_id,
        image_plan.get(
            "kind"
        ),
        image_plan.get(
            "engine"
        ),
        image_plan.get(
            "style"
        ),
        image_plan.get(
            "layout"
        ),
        image_plan.get(
            "has_text"
        ),
        aspect_ratio,
        width,
        height,
    )

    # =====================================================
    # STRUCTURED SVG
    # =====================================================

    if image_plan.get(
        "engine"
    ) == "svg":

        svg = generate_svg(
            image_plan,
            text=image_plan.get(
                "text"
            ),
        )

        if not svg:

            raise RuntimeError(
                "SVG designer returned empty output."
            )

        filename, filepath = (
            _save_svg_asset(
                svg
            )
        )

        asset_type = "svg"

    # =====================================================
    # RASTER IMAGE
    # =====================================================

    else:

        image = generate_hf_image(
            prompt=image_plan[
                "prompt"
            ],
            negative_prompt=image_plan.get(
                "negative_prompt"
            ),
            has_text=bool(
                image_plan.get(
                    "has_text"
                )
            ),
            aspect_ratio=aspect_ratio,
            width=width,
            height=height,
            seed=requested_seed,
        )

        if image is None:

            raise RuntimeError(
                "The configured raster image provider returned no image."
            )

        filename, filepath = (
            _save_raster_asset(
                image
            )
        )

        asset_type = "png"

    base_url = (
        str(request_base_url or os.getenv("REVELAAI_PUBLIC_BASE_URL", "http://localhost")).rstrip("/")
    )
    image_url = (
        base_url
        + "/ai/images/"
        + filename
    )

    logger.info(
        "IMAGE GENERATED SUCCESSFULLY | "
        "request_id=%s | file=%s | "
        "asset_type=%s | kind=%s | aspect=%s",
        request_id,
        filename,
        asset_type,
        image_plan.get(
            "kind"
        ),
        aspect_ratio,
    )

    return {
        "filename": filename,
        "filepath": filepath,
        "image_url": image_url,
        "asset_type": asset_type,
        "image_plan": image_plan,
        "aspect_ratio": aspect_ratio,
        "width": width,
        "height": height,
        "seed": requested_seed,
    }

