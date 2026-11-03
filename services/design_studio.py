"""Canva-style design brief and deterministic typography-first renderer.

All user-visible copy is drawn with Pillow after the model plans the layout.
The image model is used only for optional backgrounds and illustration assets.
"""
from __future__ import annotations

import json
import re
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from ai.ai_client import ask_hf
from ai.image_prompt import extract_text

BRAND = ("#0A74DA", "#2E8B57", "#D4AF37")
COLORS = {
    "blue": "#0A74DA", "navy": "#10243A", "green": "#2E8B57",
    "gold": "#D4AF37", "purple": "#7656C9", "red": "#D94343",
    "orange": "#E87932", "yellow": "#E6B93F", "black": "#111827",
    "white": "#FFFFFF", "cream": "#F7F2E8", "pink": "#E879A8",
}
TEMPLATES = {
    "poster", "flyer", "instagram_post", "story", "whatsapp_status",
    "business_card", "certificate", "logo_sheet",
}
SIZES = {
    "1:1": (1080, 1080),
    "4:5": (1080, 1350),
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
    "a4": (1240, 1754),
}


def _hex_color(value: Any) -> str | None:
    text = str(value or "").strip()
    if re.fullmatch(r"#[0-9a-fA-F]{6}", text):
        return text.upper()
    return COLORS.get(text.lower())


def _template(request: str, kind: str, requested: Any = None) -> str:
    explicit = str(requested or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {"instagram": "instagram_post", "whatsapp": "whatsapp_status", "logo": "logo_sheet", "businesscard": "business_card"}
    explicit = aliases.get(explicit, explicit)
    if explicit in TEMPLATES:
        return explicit
    text = request.lower()
    if "business card" in text or "visiting card" in text:
        return "business_card"
    if "certificate" in text or "award" in text:
        return "certificate"
    if "whatsapp status" in text or "whatsapp story" in text:
        return "whatsapp_status"
    if "instagram story" in text or re.search(r"\bstory\b", text):
        return "story"
    if "instagram" in text or "social post" in text:
        return "instagram_post"
    if "flyer" in text or "leaflet" in text:
        return "flyer"
    if kind == "logo" or "logo" in text:
        return "logo_sheet"
    if kind == "banner":
        return "flyer"
    return "poster"


def _extract_copy(request: str, supplied: Any = None) -> list[str]:
    raw = str(supplied or "").strip()
    if not raw:
        quoted = re.findall(r'["“]([^"”]{1,180})["”]', request)
        if quoted:
            return [re.sub(r"\s+", " ", line).strip()[:180] for line in quoted[:6] if line.strip()]
        labelled = []
        for label in ("title", "headline", "heading", "subtitle", "body", "footer", "date", "venue"):
            match = re.search(rf"\b{label}\s*[:=]\s*([^,;\n]+)", request, re.I)
            if match:
                labelled.append(match.group(1).strip().strip('"\\''))
        if labelled:
            return [line[:180] for line in labelled[:6] if line]
        raw = str(extract_text(request) or "").strip()
    if not raw:
        match = re.search(r"\b(?:for|about|announcing)\s+(.+?)(?:\s+(?:using|with|in)\s+.+)?$", request, re.I)
        raw = match.group(1).strip(" .,:;") if match else ""
    if not raw:
        cleaned = re.sub(r"^(please\s+)?(create|make|design|generate)\s+(a|an|the)?\s*", "", request, flags=re.I)
        raw = " ".join(cleaned.split()[:9]).strip(" .,:;")
    lines = [re.sub(r"\s+", " ", line).strip() for line in raw.splitlines()]
    return [line[:180] for line in lines if line][:6]


def _parse_model_json(text: str) -> dict[str, Any]:
    value = str(text or "").strip()
    value = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", value, flags=re.I)
    start, end = value.find("{"), value.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        parsed = json.loads(value[start:end + 1])
        return parsed if isinstance(parsed, dict) else {}
    except (ValueError, TypeError):
        return {}


def build_design_brief(
    request: str,
    image_plan: dict[str, Any],
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Ask the configured language model for layout direction, then lock copy."""
    options = options if isinstance(options, dict) else {}
    revision = str(options.get("revision") or "").strip()
    previous = options.get("previous_brief") if isinstance(options.get("previous_brief"), dict) else {}
    template = str(previous.get("template") or _template(request, str(image_plan.get("kind") or ""), options.get("template")))
    ratio = str(options.get("aspect_ratio") or previous.get("aspect_ratio") or image_plan.get("aspect_ratio") or "4:5").lower()
    if ratio == "a4":
        ratio = "a4"
    width, height = SIZES.get(ratio, (1080, 1350))
    supplied_copy = options.get("text") or options.get("copy")
    revision_copy = str(extract_text(revision) or "").strip() if revision else ""
    if revision_copy:
        exact_lines = _extract_copy(revision, revision_copy)
    elif supplied_copy:
        exact_lines = _extract_copy(request, supplied_copy)
    elif previous.get("exact_copy"):
        exact_lines = [str(line) for line in previous.get("exact_copy", []) if str(line).strip()][:6]
    else:
        exact_lines = _extract_copy(request)
    translation_requested = bool(re.search(r"\b(swahili|kiswahili|translate|translation)\b", revision, re.I))
    prompt = (
        "Create a production-ready graphic design brief as strict JSON only. "
        "Keys: layout (one short sentence), palette (3 to 5 hex colours), "
        "hierarchy (title_scale number 0.9 to 1.8), font_style (sans|serif|display), "
        "motifs (up to 3 short visual motifs), background_prompt (one short image-only prompt), "
        "title, subtitle, body, footer. "
        "Do not add claims, dates, phone numbers or brand names. Preserve provided copy verbatim. "
        "Only translate the supplied copy if the revision explicitly asks for translation. "
        "Use balanced whitespace and safe margins of at least 8 percent.\n"
        f"Artifact: {template}. Aspect ratio: {ratio}. Request: {request[:1800]}. "
        f"Revision: {revision[:500]}. Supplied copy: {json.dumps(exact_lines, ensure_ascii=False)}."
    )
    model_brief: dict[str, Any] = {}
    try:
        response = ask_hf(
            prompt,
            system_prompt="You are a senior brand designer. Return valid JSON only. Never invent factual event details.",
        )
        if isinstance(response, dict) and response.get("success") is True:
            model_brief = _parse_model_json(response.get("response", ""))
    except Exception:
        model_brief = {}

    palette_values = model_brief.get("palette") if isinstance(model_brief.get("palette"), list) else []
    palette = [_hex_color(item) for item in palette_values]
    palette = [item for item in palette if item][:4]
    if not palette and previous.get("palette"):
        palette = [_hex_color(item) for item in previous.get("palette", []) if _hex_color(item)]
    if not palette:
        palette = [_hex_color(item) for item in image_plan.get("palette", []) if _hex_color(item)]
    if not palette:
        palette = list(BRAND)
    if revision:
        revision_colours = [name for name in COLORS if re.search(rf"\b{re.escape(name)}\b", revision, re.I)]
        if revision_colours:
            palette = [COLORS[name] for name in revision_colours[:3]]
        if re.search(r"\b(blue|navy|green|gold|purple|red|orange|yellow|black|white|cream|pink)\b", revision, re.I):
            palette = list(dict.fromkeys(palette))[:4]

    if translation_requested:
        title = str(model_brief.get("title") or (exact_lines[0] if exact_lines else ""))[:180]
        subtitle = str(model_brief.get("subtitle") or (exact_lines[1] if len(exact_lines) > 1 else ""))[:180]
        body = str(model_brief.get("body") or " ".join(exact_lines[2:]))[:420]
    else:
        title = exact_lines[0] if exact_lines else str(previous.get("title") or "")
        subtitle = exact_lines[1] if len(exact_lines) > 1 else str(previous.get("subtitle") or "")
        body = " ".join(exact_lines[2:])[:420] if len(exact_lines) > 2 else str(previous.get("body") or "")
    if revision and re.search(r"\b(title|headline).{0,18}\b(bigger|larger|prominent)\b", revision, re.I):
        title_scale = 1.55
    else:
        try:
            title_scale = max(0.9, min(1.8, float(previous.get("title_scale", model_brief.get("hierarchy", {}).get("title_scale", 1.25)))))
        except (TypeError, ValueError, AttributeError):
            title_scale = 1.25

    return {
        "template": template,
        "layout": str(previous.get("layout") or model_brief.get("layout") or "editorial grid with a strong headline and generous whitespace")[:240],
        "palette": palette,
        "font_style": str(model_brief.get("font_style") or "sans")[:20],
        "motifs": [str(x)[:60] for x in model_brief.get("motifs", [])[:3]] if isinstance(model_brief.get("motifs"), list) else [],
        "background_prompt": str(model_brief.get("background_prompt") or "")[:500],
        "title": title,
        "subtitle": subtitle,
        "body": body,
        "footer": str(model_brief.get("footer") or previous.get("footer") or "")[:180],
        "exact_copy": exact_lines,
        "aspect_ratio": ratio,
        "width": width,
        "height": height,
        "title_scale": title_scale,
        "safe_margin": 0.085,
        "editable_fields": ["title", "subtitle", "body", "footer", "palette", "font_style"],
        "brief_source": "configured_text_model" if model_brief else "deterministic_safe_fallback",
        "revision": revision or None,
    }


def _font(size: int, bold: bool = False, serif: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = []
    if serif:
        candidates += ["/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"]
    else:
        candidates += ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    candidates += ["C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    words = str(text or "").split()
    lines: list[str] = []
    current = ""
    for word in words:
        trial = (current + " " + word).strip()
        if current and draw.textbbox((0, 0), trial, font=font)[2] > max_width:
            lines.append(current)
            current = word
        else:
            current = trial
    if current:
        lines.append(current)
    return lines or [""]


def _draw_wrapped(draw: ImageDraw.ImageDraw, text: str, xy: tuple[int, int], font: ImageFont.ImageFont,
                  fill: str, max_width: int, line_gap: int = 12, align: str = "left", max_lines: int = 6) -> int:
    x, y = xy
    lines = _wrap(draw, text, font, max_width)[:max_lines]
    for line in lines:
        box = draw.textbbox((0, 0), line, font=font)
        line_width = box[2] - box[0]
        draw.text((x - line_width // 2 if align == "center" else x, y), line, font=font, fill=fill)
        y += max(1, box[3] - box[1]) + line_gap
    return y


def _gradient(size: tuple[int, int], first: str, second: str) -> Image.Image:
    image = Image.new("RGB", size, first)
    draw = ImageDraw.Draw(image)
    a = tuple(int(first[i:i + 2], 16) for i in (1, 3, 5))
    b = tuple(int(second[i:i + 2], 16) for i in (1, 3, 5))
    for y in range(size[1]):
        t = y / max(1, size[1] - 1)
        color = tuple(round(a[i] * (1 - t) + b[i] * t) for i in range(3))
        draw.line((0, y, size[0], y), fill=color)
    return image


def render_design(brief: dict[str, Any], background: Image.Image | None = None) -> Image.Image:
    """Render a crisp raster design with exact copy and reusable layout templates."""
    width, height = int(brief["width"]), int(brief["height"])
    palette = list(brief.get("palette") or BRAND)
    primary, secondary, accent = (palette + list(BRAND))[:3]
    template = str(brief.get("template") or "poster")
    dark = template in {"poster", "story", "whatsapp_status", "business_card", "logo_sheet"}
    image = background.convert("RGB").resize((width, height), Image.Resampling.LANCZOS) if background is not None else _gradient((width, height), "#0D1B2A" if dark else "#F8FAFC", "#172F4A" if dark else "#E8F1F8")
    draw = ImageDraw.Draw(image, "RGBA")
    margin = int(min(width, height) * float(brief.get("safe_margin", 0.085)))
    white = "#FFFFFF" if dark else "#10243A"
    muted = "#D8E4EF" if dark else "#536579"
    title = str(brief.get("title") or "")
    subtitle = str(brief.get("subtitle") or "")
    body = str(brief.get("body") or "")
    footer = str(brief.get("footer") or "")
    title_size = int(min(width, height) * (0.095 * float(brief.get("title_scale", 1.0))))
    title_font = _font(title_size, True, brief.get("font_style") == "serif")
    sub_font = _font(max(22, int(title_size * 0.38)), True)
    body_font = _font(max(19, int(title_size * 0.25)))
    tiny_font = _font(max(16, int(title_size * 0.18)), True)

    # Shared polished geometry: a high-contrast accent rail, soft cards and safe-area guides.
    draw.rounded_rectangle((margin, margin, width - margin, height - margin), radius=int(margin * 0.45),
                           outline=accent + "CC", width=max(2, int(width * 0.003)))
    draw.ellipse((width - margin * 2, -margin, width + margin, margin * 2), fill=primary + "35")
    draw.ellipse((-margin, height - margin * 2, margin * 2, height + margin), fill=accent + "28")

    if template == "business_card":
        draw.rounded_rectangle((margin, margin, width - margin, height - margin), radius=36, fill="#10243A")
        draw.rounded_rectangle((margin, margin, margin + int(width * .045), height - margin), radius=16, fill=accent)
        mark = (title[:1] or "R").upper()
        draw.ellipse((margin * 2, height // 2 - 100, margin * 2 + 200, height // 2 + 100), fill=primary)
        draw.text((margin * 2 + 70, height // 2 - 75), mark, font=_font(145, True), fill="#FFFFFF")
        x = margin * 2 + 260
        _draw_wrapped(draw, title or "Your name", (x, height // 2 - 125), title_font, "#FFFFFF", width - x - margin * 2, 10, "left", 2)
        _draw_wrapped(draw, subtitle, (x, height // 2 + 55), sub_font, accent, width - x - margin * 2, 8, "left", 2)
        _draw_wrapped(draw, body, (x, height // 2 + 145), body_font, "#D8E4EF", width - x - margin * 2, 8, "left", 3)
        return image

    if template == "certificate":
        draw.rectangle((margin, margin, width - margin, height - margin), outline=accent, width=max(6, width // 100))
        draw.rectangle((margin + 18, margin + 18, width - margin - 18, height - margin - 18), outline=primary, width=max(2, width // 350))
        y = margin + int(height * .13)
        _draw_wrapped(draw, title or "CERTIFICATE", (width // 2, y), _font(int(width * .055), True, True), accent, width - margin * 3, 16, "center", 2)
        y += int(height * .18)
        _draw_wrapped(draw, subtitle or "This certificate is presented to", (width // 2, y), sub_font, muted, width - margin * 3, 12, "center", 2)
        y += int(height * .13)
        _draw_wrapped(draw, body or "Recipient name", (width // 2, y), _font(int(width * .052), True, True), white, width - margin * 3, 18, "center", 3)
        y += int(height * .23)
        draw.line((margin * 2, y, width - margin * 2, y), fill=accent, width=3)
        if footer:
            _draw_wrapped(draw, footer, (width // 2, y + 40), tiny_font, muted, width - margin * 3, 8, "center", 2)
        return image

    if template == "logo_sheet":
        draw.text((width // 2, margin + 20), title or "BRAND IDENTITY", font=_font(int(width * .045), True), fill=white, anchor="ma")
        if subtitle:
            _draw_wrapped(draw, subtitle, (width // 2, int(height * .17)), _font(int(width * .025), True), accent, width - margin * 2, 8, "center", 2)
        cell = int(width * .22)
        gap = int(width * .055)
        start_x = (width - (cell * 3 + gap * 2)) // 2
        start_y = int(height * .25)
        labels = ["Wordmark", "Monogram", "Icon", "Outline", "Stacked", "Badge", "Symbol", "Reverse", "Compact"]
        for index, label in enumerate(labels):
            row, col = divmod(index, 3)
            x = start_x + col * (cell + gap)
            y = start_y + row * (cell + gap)
            draw.rounded_rectangle((x, y, x + cell, y + cell), radius=24, fill="#FFFFFF" if index % 2 else "#172F4A", outline=accent, width=3)
            mark = (title[:2] or "RC").upper()
            draw.ellipse((x + cell * .25, y + cell * .16, x + cell * .75, y + cell * .66), fill=primary if index % 2 else accent)
            draw.text((x + cell // 2, y + cell * .30), mark, font=_font(int(cell * .18), True), fill="#FFFFFF", anchor="mm")
            draw.text((x + cell // 2, y + cell * .80), label, font=tiny_font, fill="#10243A" if index % 2 else "#FFFFFF", anchor="mm")
        return image

    # Poster, flyer, social, story and WhatsApp templates.
    if template in {"story", "whatsapp_status"}:
        y = int(height * .23)
        draw.rounded_rectangle((margin, int(height * .10), width - margin, int(height * .17)), radius=30, fill=accent)
        if subtitle:
            _draw_wrapped(draw, subtitle.upper(), (width // 2, int(height * .20)), sub_font, accent, width - margin * 2, 10, "center", 2)
    elif template == "instagram_post":
        draw.polygon([(0, 0), (int(width * .44), 0), (0, int(height * .44))], fill=primary)
        draw.rounded_rectangle((margin, margin, width - margin, height - margin), radius=38, outline=accent, width=6)
        y = int(height * .24)
    elif template == "flyer":
        draw.rectangle((0, 0, int(width * .075), height), fill=primary)
        draw.rounded_rectangle((margin, margin, width - margin, height - margin), radius=24, fill="#FFFFFF" if not background else "#10243A88")
        y = int(height * .18)
    else:
        draw.rectangle((margin, margin, width - margin, int(height * .20)), fill=primary)
        y = int(height * .27)

    if template not in {"story", "whatsapp_status", "instagram_post", "flyer"}:
        y = int(height * .28)
    if title:
        y = _draw_wrapped(draw, title, (width // 2 if template in {"instagram_post", "story", "whatsapp_status"} else margin * 1.35, y),
                          title_font, white, width - margin * 2, int(title_size * .18),
                          "center" if template in {"instagram_post", "story", "whatsapp_status"} else "left", 4)
    if subtitle:
        y += int(height * .025)
        y = _draw_wrapped(draw, subtitle, (width // 2, y), sub_font, accent if dark else primary,
                          width - margin * 2, 12, "center", 3)
    if body:
        y += int(height * .045)
        y = _draw_wrapped(draw, body, (width // 2, y), body_font, muted if dark else "#334155",
                          width - margin * 2, 12, "center", 7)
    if footer:
        draw.rounded_rectangle((margin, height - margin * 2, width - margin, height - margin), radius=24, fill=primary)
        _draw_wrapped(draw, footer, (width // 2, height - margin * 1.65), tiny_font, "#FFFFFF", width - margin * 3, 8, "center", 2)
    elif template in {"poster", "flyer"}:
        draw.line((margin, height - margin * 1.6, width - margin, height - margin * 1.6), fill=accent, width=4)
    return image


def enhance_illustration_prompt(request: str, image_plan: dict[str, Any]) -> str:
    """Add useful composition and lighting guidance without switching providers."""
    style = str(image_plan.get("style") or "cinematic editorial")
    return (
        f"{request}. Visual direction: {style}; deliberate subject placement and clear focal point; "
        "professional composition, controlled depth of field, physically plausible lighting, "
        "rich but coherent colour grading, detailed materials, clean silhouette, balanced negative space. "
        "Create artwork only; do not render lettering, captions, watermarks, logos or UI text."
    )
