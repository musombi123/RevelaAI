"""Framework-neutral image and design studio service."""
from __future__ import annotations

import logging
import os
import re
import uuid
from typing import Any

from PIL import Image

from ai.ai_client import generate_hf_image
from ai.image_prompt import build_image_prompt
from ai.svg_designer import generate_svg
from services.design_studio import build_design_brief, enhance_illustration_prompt, render_design
from services.runtime_config import IMAGE_DIR
from services.ai_service import detect_capability

logger = logging.getLogger("revelaai.image_service")
DESIGN_REQUEST_RE = re.compile(
    r"\b(poster|flyer|leaflet|invitation|logo|brand mark|banner|instagram|social post|"
    r"whatsapp status|business card|visiting card|certificate|award graphic)\b",
    re.I,
)


def is_image_generation_request(message: str) -> bool:
    return detect_capability(str(message or ""), intent="general") == "image_generation"


def is_design_revision(message: str) -> bool:
    return bool(re.search(
        r"\b(change|switch|replace|make|increase|decrease|bigger|smaller|use|translate|"
        r"recolour|recolor|move|remove|add|edit|revise)\b",
        str(message or ""), re.I,
    ))


def _optional_int(value: Any, label: str) -> int | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Image {label} must be an integer.") from exc
    if parsed < 1 or parsed > 2600:
        raise ValueError(f"Image {label} must be between 1 and 2600 pixels.")
    return parsed


def parse_image_options(source: Any) -> dict[str, Any]:
    if not isinstance(source, dict):
        return {}
    options: dict[str, Any] = {}
    ratio = str(source.get("aspect_ratio") or source.get("image_aspect_ratio") or "").strip().lower()
    if ratio:
        if ratio not in {"1:1", "4:5", "9:16", "16:9", "a4"}:
            raise ValueError("Choose a supported canvas: 1:1, 4:5, 9:16, 16:9 or A4.")
        options["aspect_ratio"] = ratio
    for field in ("width", "height", "seed"):
        value = _optional_int(source.get(field), field)
        if value is not None:
            options[field] = value
    output_format = str(source.get("output_format") or "png").strip().lower()
    if output_format not in {"png", "jpg", "jpeg", "pdf"}:
        raise ValueError("Image output format must be PNG, JPG or PDF.")
    options["output_format"] = "jpg" if output_format == "jpeg" else output_format
    template = str(source.get("template") or "").strip().lower().replace("-", "_").replace(" ", "_")
    if template:
        allowed = {"poster", "flyer", "instagram_post", "story", "whatsapp_status", "business_card", "certificate", "logo_sheet"}
        if template not in allowed:
            raise ValueError("Unsupported design template.")
        options["template"] = template
    copy = source.get("text") if source.get("text") is not None else source.get("copy")
    if copy is not None:
        if not isinstance(copy, str) or len(copy) > 1200:
            raise ValueError("Design text must be a string of 1,200 characters or fewer.")
        options["text"] = copy
    options["use_ai_background"] = source.get("use_ai_background") is True
    return options


def _save_svg(svg: str) -> tuple[str, str]:
    filename = f"revelaai_{uuid.uuid4().hex}.svg"
    path = os.path.join(IMAGE_DIR, filename)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(svg)
    return filename, path


def _save_image(image: Image.Image, extension: str) -> tuple[str, str]:
    filename = f"revelaai_{uuid.uuid4().hex}.{extension}"
    path = os.path.join(IMAGE_DIR, filename)
    if extension == "jpg":
        image.convert("RGB").save(path, format="JPEG", quality=94, optimize=True, progressive=True)
    else:
        image.save(path, format="PNG", optimize=True)
    return filename, path


def _save_pdf(image: Image.Image) -> tuple[str, str]:
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    filename = f"revelaai_{uuid.uuid4().hex}.pdf"
    path = os.path.join(IMAGE_DIR, filename)
    page_width = 595.28
    page_height = page_width * image.height / max(1, image.width)
    pdf = canvas.Canvas(path, pagesize=(page_width, page_height), pageCompression=1)
    pdf.drawImage(ImageReader(image.convert("RGB")), 0, 0, width=page_width, height=page_height, preserveAspectRatio=True, mask="auto")
    pdf.showPage()
    pdf.save()
    return filename, path


def _asset_urls(base_url: str, filenames: dict[str, str]) -> dict[str, str]:
    root = base_url.rstrip("/")
    return {kind: f"{root}/ai/images/{filename}" for kind, filename in filenames.items()}


def generate_image_asset(
    message: str,
    *,
    image_options: dict[str, Any] | None = None,
    request_base_url: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Route designed artefacts through exact-text layout; route artwork to Pollinations."""
    options = image_options if isinstance(image_options, dict) else {}
    base_request = str(options.get("base_request") or message or "").strip()
    revision = str(options.get("revision") or "").strip()
    planning_request = base_request + (f"\nRevision request: {revision}" if revision else "")
    plan = build_image_prompt(planning_request)
    ratio = str(options.get("aspect_ratio") or plan.get("aspect_ratio") or "1:1").lower()
    if ratio not in {"1:1", "4:5", "9:16", "16:9", "a4"}:
        ratio = "1:1"
    ratio_sizes = {"1:1": (1080, 1080), "4:5": (1080, 1350), "9:16": (1080, 1920), "16:9": (1920, 1080), "a4": (1240, 1754)}
    width = options.get("width") or ratio_sizes[ratio][0]
    height = options.get("height") or ratio_sizes[ratio][1]
    seed = options.get("seed")
    is_design = bool(DESIGN_REQUEST_RE.search(planning_request))
    is_diagram = plan.get("kind") == "diagram" and not is_design
    downloads: dict[str, str] = {}
    brief = None
    image: Image.Image | None = None
    svg_name = None

    logger.info("IMAGE ROUTED | request_id=%s | path=%s | kind=%s | ratio=%s", request_id,
                "design" if is_design else "illustration", plan.get("kind"), ratio)

    if is_diagram:
        svg = generate_svg(plan, text=plan.get("text"))
        if not svg:
            raise RuntimeError("The vector designer returned an empty diagram.")
        svg_name, _ = _save_svg(svg)
        filenames = {"svg": svg_name}
        asset_type = "svg"
        width, height = int(plan.get("width") or width), int(plan.get("height") or height)
        brief = {"template": "diagram", "brief_source": "existing_safe_svg_designer", "exact_copy": [plan.get("text")] if plan.get("text") else []}
    elif is_design:
        brief = build_design_brief(planning_request, plan, {**options, "revision": revision})
        brief["width"], brief["height"] = width, height
        background = None
        if options.get("use_ai_background") or re.search(r"\b(photo background|photographic background|realistic background|image background)\b", planning_request, re.I):
            background_prompt = brief.get("background_prompt") or enhance_illustration_prompt(planning_request, plan)
            try:
                background = generate_hf_image(prompt=background_prompt, aspect_ratio=ratio, width=width, height=height, seed=seed, has_text=False)
            except Exception as exc:
                logger.warning("Design background unavailable; using local template background | error=%s", type(exc).__name__)
        image = render_design(brief, background=background)
        filenames = {}
        for extension in ("png", "jpg"):
            filename, _ = _save_image(image, extension)
            filenames[extension] = filename
        pdf_name, _ = _save_pdf(image)
        filenames["pdf"] = pdf_name
        asset_type = "png"
        width, height = image.size
        downloads = _asset_urls(str(request_base_url or os.getenv("REVELAAI_PUBLIC_BASE_URL", "http://localhost")), filenames)
    else:
        illustration_prompt = enhance_illustration_prompt(planning_request, plan)
        image = generate_hf_image(
            prompt=illustration_prompt,
            negative_prompt=plan.get("negative_prompt"),
            has_text=False,
            aspect_ratio=ratio,
            width=width,
            height=height,
            seed=seed,
        )
        if image is None:
            raise RuntimeError("The configured illustration provider returned no image.")
        filenames = {}
        for extension in ("png", "jpg"):
            filename, _ = _save_image(image, extension)
            filenames[extension] = filename
        pdf_name, _ = _save_pdf(image)
        filenames["pdf"] = pdf_name
        asset_type = "png"
        width, height = image.size
        downloads = _asset_urls(str(request_base_url or os.getenv("REVELAAI_PUBLIC_BASE_URL", "http://localhost")), filenames)

    base_url = str(request_base_url or os.getenv("REVELAAI_PUBLIC_BASE_URL", "http://localhost")).rstrip("/")
    image_url = f"{base_url}/ai/images/{svg_name or filenames.get('png') or filenames.get('svg')}"
    if not downloads and filenames:
        downloads = _asset_urls(base_url, filenames)
    return {
        "filename": svg_name or filenames.get("png") or filenames.get("svg"),
        "image_url": image_url,
        "downloads": downloads,
        "asset_type": asset_type,
        "image_plan": {**plan, "engine": "design_renderer" if is_design else ("svg" if is_diagram else "pollinations")},
        "design_brief": brief,
        "aspect_ratio": ratio,
        "width": width,
        "height": height,
        "seed": seed,
    }
