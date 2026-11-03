"""Canva-style design brief and deterministic typography-first renderer.

All user-visible copy is drawn with Pillow after the model plans the layout.
The image model is used only for optional backgrounds and illustration assets.
"""
from __future__ import annotations

import json
import math
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
                labelled.append(match.group(1).strip().strip(" \"'"))
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
    explicit_fields = [
        str(options.get(field) or "").strip()
        for field in ("title", "subtitle", "body", "footer")
        if str(options.get(field) or "").strip()
    ]
    revision_copy = str(extract_text(revision) or "").strip() if revision else ""
    if revision_copy:
        exact_lines = _extract_copy(revision, revision_copy)
    elif explicit_fields:
        exact_lines = explicit_fields[:6]
    elif supplied_copy:
        exact_lines = _extract_copy(request, supplied_copy)
    elif previous.get("exact_copy"):
        exact_lines = [str(line) for line in previous.get("exact_copy", []) if str(line).strip()][:6]
    else:
        exact_lines = _extract_copy(request)
    translation_requested = bool(re.search(r"\b(swahili|kiswahili|translate|translation)\b", revision, re.I))
    prompt = (
        "Create a production-ready graphic design brief as strict JSON only. "
        "Keys: layout (specific alignment and composition), palette (3 to 5 hex colours), "
        "hierarchy (title_scale number 0.9 to 1.8 plus a short hierarchy description), "
        "font_style (sans|serif|display), icons (up to 3 simple icon names such as star, leaf, bolt, book, globe), "
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
        "font_style": str(model_brief.get("font_style") or previous.get("font_style") or "sans").lower()[:20],
        "icons": [str(x)[:40] for x in model_brief.get("icons", [])[:3]] if isinstance(model_brief.get("icons"), list) else [],
        "motifs": [str(x)[:60] for x in model_brief.get("motifs", [])[:3]] if isinstance(model_brief.get("motifs"), list) else [],
        "background_prompt": str(model_brief.get("background_prompt") or "")[:500],
        "title": str(options.get("title") or title)[:180],
        "subtitle": str(options.get("subtitle") or subtitle)[:180],
        "body": str(options.get("body") or body)[:420],
        "footer": str(options.get("footer") or model_brief.get("footer") or previous.get("footer") or "")[:180],
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


def _font(size: int, bold: bool = False, serif: bool = False, display: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    size = max(12, int(size))
    candidates = []
    if serif:
        candidates += [
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
        ]
    elif display:
        candidates += [
            "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ]
    else:
        candidates += [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
    candidates += [
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _fit_font(draw: ImageDraw.ImageDraw, text: str, start_size: int, max_width: int,
              max_lines: int, *, bold: bool = True, serif: bool = False, display: bool = False) -> ImageFont.ImageFont:
    """Shrink only as much as needed to keep exact copy inside the safe area."""
    for size in range(max(14, int(start_size)), 13, -2):
        font = _font(size, bold=bold, serif=serif, display=display)
        lines = _wrap(draw, text, font, max_width)
        if len(lines) <= max_lines and all(draw.textbbox((0, 0), line, font=font)[2] <= max_width for line in lines):
            return font
    return _font(14, bold=bold, serif=serif, display=display)


def _draw_motif(draw: ImageDraw.ImageDraw, name: str, center: tuple[int, int], size: int, color: str) -> None:
    """Draw a small, deterministic decorative icon without external assets."""
    x, y = center
    key = str(name or "").lower()
    width = max(3, size // 10)
    if any(word in key for word in ("star", "spark", "shine")):
        points = []
        for i in range(10):
            angle = -math.pi / 2 + i * math.pi / 5
            radius = size // 2 if i % 2 == 0 else size // 5
            points.append((x + int(math.cos(angle) * radius), y + int(math.sin(angle) * radius)))
        draw.polygon(points, fill=color)
    elif "leaf" in key:
        draw.ellipse((x-size//2, y-size//3, x+size//2, y+size//3), fill=color)
        draw.line((x-size//3, y+size//4, x+size//3, y-size//4), fill="#FFFFFF", width=width)
    elif any(word in key for word in ("bolt", "flash", "energy")):
        draw.polygon([(x, y-size//2), (x-size//4, y), (x, y), (x-size//8, y+size//2), (x+size//3, y-size//8), (x+size//8, y-size//8)], fill=color)
    elif "book" in key:
        draw.rounded_rectangle((x-size//2, y-size//2, x, y+size//2), radius=width, outline=color, width=width)
        draw.rounded_rectangle((x, y-size//2, x+size//2, y+size//2), radius=width, outline=color, width=width)
        draw.line((x, y-size//2, x, y+size//2), fill=color, width=width)
    elif "globe" in key:
        draw.ellipse((x-size//2, y-size//2, x+size//2, y+size//2), outline=color, width=width)
        draw.arc((x-size//4, y-size//2, x+size//4, y+size//2), 0, 360, fill=color, width=width)
        draw.line((x-size//2, y, x+size//2, y), fill=color, width=width)
    else:
        draw.ellipse((x-size//2, y-size//2, x+size//2, y+size//2), fill=color)


def _draw_pill(draw: ImageDraw.ImageDraw, text: str, xy: tuple[int, int], font: ImageFont.ImageFont,
               fill: str, text_fill: str, pad_x: int = 24, pad_y: int = 12) -> None:
    x, y = xy
    box = draw.textbbox((0, 0), text, font=font)
    width, height = box[2] - box[0], box[3] - box[1]
    draw.rounded_rectangle((x, y, x + width + pad_x * 2, y + height + pad_y * 2), radius=(height + pad_y * 2) // 2, fill=fill)
    draw.text((x + pad_x, y + pad_y - box[1]), text, font=font, fill=text_fill)


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
    """Render one of eight typography-first, high-resolution templates with exact copy."""
    width, height = int(brief["width"]), int(brief["height"])
    palette = [_hex_color(value) for value in (brief.get("palette") or BRAND)]
    palette = [value for value in palette if value]
    primary, secondary, accent = (palette + list(BRAND))[:3]
    template = str(brief.get("template") or "poster")
    dark = template in {"poster", "story", "whatsapp_status", "business_card", "logo_sheet"}
    if background is not None:
        image = background.convert("RGB").resize((width, height), Image.Resampling.LANCZOS)
        overlay = Image.new("RGBA", (width, height), (7, 19, 34, 142) if dark else (248, 250, 252, 176))
        image = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")
    else:
        image = _gradient((width, height), "#0B1727" if dark else "#F7F5EF", "#173A55" if dark else "#E5EEF5")
    draw = ImageDraw.Draw(image, "RGBA")
    margin = max(32, int(min(width, height) * float(brief.get("safe_margin", 0.085))))
    right = width - margin
    bottom = height - margin
    title = str(brief.get("title") or "")
    subtitle = str(brief.get("subtitle") or "")
    body = str(brief.get("body") or "")
    footer = str(brief.get("footer") or "")
    serif = str(brief.get("font_style") or "").lower() == "serif"
    display = str(brief.get("font_style") or "").lower() == "display"
    white = "#FFFFFF" if dark else "#10243A"
    muted = "#DCE7F0" if dark else "#536579"
    title_size = int(min(width, height) * (0.105 * float(brief.get("title_scale", 1.0))))
    title_font = _fit_font(draw, title, title_size, width - margin * 2, 4, serif=serif, display=display)
    sub_font = _font(max(22, int(title_size * 0.34)), True, serif=serif)
    body_font = _font(max(19, int(title_size * 0.22)))
    tiny_font = _font(max(16, int(title_size * 0.16)), True)
    icons = brief.get("icons") if isinstance(brief.get("icons"), list) else []
    motifs = brief.get("motifs") if isinstance(brief.get("motifs"), list) else []
    decorations = [str(x) for x in (icons + motifs)[:3]]

    # Reusable high-quality visual language: precise safe area, contrast, accents and detail.
    draw.rounded_rectangle((margin, margin, right, bottom), radius=max(22, margin // 3),
                           outline=accent + "CC", width=max(2, width // 360))
    draw.ellipse((int(width * .76), -int(height * .12), int(width * 1.08), int(height * .20)), fill=primary + "42")
    draw.ellipse((-int(width * .12), int(height * .80), int(width * .20), int(height * 1.12)), fill=accent + "35")
    for index, motif in enumerate(decorations):
        _draw_motif(draw, motif, (right - (index * max(70, margin // 2)), margin + max(30, margin // 2)), max(28, margin // 2), accent if index % 2 == 0 else primary)

    if template == "business_card":
        draw.rounded_rectangle((margin, margin, right, bottom), radius=38, fill="#10243A")
        draw.rounded_rectangle((margin, margin, margin + max(14, width // 48), bottom), radius=14, fill=accent)
        mark_size = int(min(width, height) * .25)
        cx, cy = margin * 2 + mark_size // 2, height // 2
        draw.ellipse((cx-mark_size//2, cy-mark_size//2, cx+mark_size//2, cy+mark_size//2), fill=primary)
        _draw_motif(draw, decorations[0] if decorations else "star", (cx, cy), mark_size // 2, "#FFFFFF")
        x = margin * 2 + mark_size + 34
        available = right - x - margin
        name_font = _fit_font(draw, title or "Your name", int(height * .12), available, 2, display=display, serif=serif)
        _draw_wrapped(draw, title or "Your name", (x, height // 2 - int(height * .22)), name_font, "#FFFFFF", available, 8, "left", 2)
        _draw_wrapped(draw, subtitle, (x, height // 2 + int(height * .02)), sub_font, accent, available, 8, "left", 2)
        _draw_wrapped(draw, body, (x, height // 2 + int(height * .16)), body_font, "#D8E4EF", available, 8, "left", 3)
        if footer:
            _draw_wrapped(draw, footer, (x, bottom - margin // 2), tiny_font, "#FFFFFF", available, 6, "left", 2)
        return image

    if template == "certificate":
        draw.rectangle((margin, margin, right, bottom), outline=accent, width=max(5, width // 150))
        inner = margin + max(18, margin // 5)
        draw.rectangle((inner, inner, width-inner, height-inner), outline=primary, width=max(2, width // 420))
        _draw_motif(draw, "star", (width // 2, margin * 2), max(40, margin // 2), accent)
        y = margin + int(height * .13)
        _draw_wrapped(draw, title or "CERTIFICATE", (width // 2, y), _fit_font(draw, title or "CERTIFICATE", int(width*.06), width-margin*3, 2, serif=True), accent, width-margin*3, 16, "center", 2)
        y += int(height * .16)
        _draw_wrapped(draw, subtitle or "This certificate is presented to", (width // 2, y), sub_font, muted, width-margin*3, 12, "center", 2)
        y += int(height * .13)
        recipient_font = _fit_font(draw, body or "Recipient name", int(width*.055), width-margin*3, 3, serif=True)
        y = _draw_wrapped(draw, body or "Recipient name", (width // 2, y), recipient_font, white, width-margin*3, 18, "center", 3)
        y += int(height * .12)
        draw.line((margin*2, y, right-margin*2, y), fill=accent, width=3)
        if footer:
            _draw_wrapped(draw, footer, (width // 2, y+35), tiny_font, muted, width-margin*3, 8, "center", 2)
        return image

    if template == "logo_sheet":
        _draw_wrapped(draw, title or "BRAND IDENTITY", (width//2, margin+22), _fit_font(draw, title or "BRAND IDENTITY", int(width*.05), width-margin*2, 2, display=True), white, width-margin*2, 8, "center", 2)
        if subtitle:
            _draw_wrapped(draw, subtitle, (width//2, int(height*.14)), sub_font, accent, width-margin*2, 8, "center", 2)
        cell = int(min(width, height) * .205)
        gap = int(cell * .13)
        grid_width = cell * 3 + gap * 2
        start_x = (width - grid_width) // 2
        start_y = int(height * .23)
        labels = ["Wordmark", "Monogram", "Icon", "Outline", "Stacked", "Badge", "Symbol", "Reverse", "Compact"]
        mark = (title[:2] or "RC").upper()
        for index, label in enumerate(labels):
            row, col = divmod(index, 3)
            x, y = start_x + col*(cell+gap), start_y + row*(cell+gap)
            dark_cell = index % 2 == 0
            fill = "#10243A" if dark_cell else "#FFFFFF"
            text_color = "#FFFFFF" if dark_cell else "#10243A"
            draw.rounded_rectangle((x,y,x+cell,y+cell), radius=max(14,cell//10), fill=fill, outline=accent, width=max(2,cell//90))
            draw.ellipse((x+cell*.27,y+cell*.10,x+cell*.73,y+cell*.56), fill=primary if dark_cell else accent)
            draw.text((x+cell//2,y+cell*.33), mark, font=_font(int(cell*.17),True,display=True), fill="#FFFFFF", anchor="mm")
            draw.text((x+cell//2,y+cell*.79), label, font=_font(max(14,int(cell*.075)),True), fill=text_color, anchor="mm")
        if footer:
            _draw_wrapped(draw, footer, (width//2, bottom-margin//2), tiny_font, muted, width-margin*2, 8, "center", 2)
        return image

    # Poster: editorial hero composition with strong left alignment and a bold accent rail.
    if template == "poster":
        draw.rectangle((margin, margin, right, margin + int(height*.12)), fill=primary)
        _draw_pill(draw, str(brief.get("layout") or "FEATURED EVENT")[:34].upper(), (margin*1.35, margin+int(height*.035)), tiny_font, accent, "#10243A")
        y = int(height*.29)
        title_font = _fit_font(draw, title, int(min(width,height)*.13*float(brief.get("title_scale",1.0))), width-margin*3, 4, serif=serif, display=display)
        y = _draw_wrapped(draw, title, (margin*1.35,y), title_font, white, width-margin*3, 8, "left", 4)
        if subtitle:
            y += int(height*.035)
            y = _draw_wrapped(draw, subtitle, (margin*1.35,y), sub_font, accent, width-margin*3, 10, "left", 3)
        if body:
            y += int(height*.045)
            _draw_wrapped(draw, body, (margin*1.35,y), body_font, muted, width-margin*3, 12, "left", 6)
        if footer:
            draw.rounded_rectangle((margin, bottom-int(height*.12), right, bottom), radius=24, fill=primary)
            _draw_wrapped(draw, footer, (width//2, bottom-int(height*.085)), tiny_font, "#FFFFFF", width-margin*3, 8, "center", 2)
        return image

    # Flyer: bright information-first layout with an event title block and detail panel.
    if template == "flyer":
        draw.rounded_rectangle((margin, margin, right, int(height*.36)), radius=30, fill=primary)
        _draw_pill(draw, "YOU'RE INVITED", (margin*1.35, margin*1.35), tiny_font, accent, "#10243A")
        y = int(height*.19)
        title_font = _fit_font(draw, title, int(min(width,height)*.105*float(brief.get("title_scale",1.0))), width-margin*3, 4, serif=serif, display=display)
        y = _draw_wrapped(draw, title, (margin*1.35,y), title_font, "#FFFFFF", width-margin*3, 8, "left", 4)
        if subtitle:
            _draw_wrapped(draw, subtitle, (margin*1.35,y+18), sub_font, "#F8FAFC", width-margin*3, 8, "left", 2)
        panel_top = int(height*.43)
        draw.rounded_rectangle((margin, panel_top, right, bottom), radius=28, fill="#FFFFFF", outline=accent, width=3)
        if body:
            _draw_wrapped(draw, body, (margin*1.4,panel_top+int(height*.08)), body_font, "#10243A", width-margin*2.8, 12, "left", 7)
        if footer:
            draw.rounded_rectangle((margin*1.35,bottom-int(height*.13),right-margin*1.35,bottom-int(height*.035)), radius=18, fill=secondary)
            _draw_wrapped(draw, footer, (width//2,bottom-int(height*.105)), tiny_font, "#FFFFFF", width-margin*3, 8, "center", 2)
        return image

    # Square social post: a clean centered composition with graphic corner geometry.
    if template == "instagram_post":
        draw.polygon([(0,0),(int(width*.42),0),(0,int(height*.42))], fill=primary)
        draw.polygon([(width, height),(int(width*.70),height),(width,int(height*.70))], fill=accent)
        draw.rounded_rectangle((margin*1.25,margin*1.25,right-margin*1.25,bottom-margin*1.25), radius=36, fill="#10243A" if dark else "#FFFFFF", outline=accent, width=5)
        y = int(height*.27)
        if subtitle:
            _draw_wrapped(draw, subtitle.upper(), (width//2,y), tiny_font, accent, width-margin*4, 8, "center", 2)
            y += int(height*.07)
        title_font = _fit_font(draw,title,int(min(width,height)*.105*float(brief.get("title_scale",1.0))),width-margin*4,4,serif=serif,display=display)
        y = _draw_wrapped(draw,title,(width//2,y),title_font,white,width-margin*4,10,"center",4)
        if body:
            y += int(height*.045)
            _draw_wrapped(draw,body,(width//2,y),body_font,muted,width-margin*4,10,"center",6)
        if footer:
            _draw_pill(draw,footer,(margin*1.8,bottom-int(height*.13)),tiny_font,primary,"#FFFFFF")
        return image

    # Vertical story/status canvas: large readable title, high contrast and a clear CTA.
    if template in {"story", "whatsapp_status"}:
        draw.rounded_rectangle((margin,int(height*.10),right,int(height*.17)),radius=24,fill=primary)
        _draw_pill(draw,"UPDATE",(margin*1.35,int(height*.115)),tiny_font,accent,"#10243A")
        y = int(height*.27)
        if subtitle:
            _draw_wrapped(draw,subtitle.upper(),(width//2,y),tiny_font,accent,width-margin*2,10,"center",2)
            y += int(height*.08)
        title_font = _fit_font(draw,title,int(min(width,height)*.13*float(brief.get("title_scale",1.0))),width-margin*2,5,serif=serif,display=display)
        y = _draw_wrapped(draw,title,(width//2,y),title_font,white,width-margin*2,12,"center",5)
        if body:
            y += int(height*.06)
            _draw_wrapped(draw,body,(width//2,y),body_font,muted,width-margin*2,12,"center",6)
        if footer:
            draw.rounded_rectangle((margin,bottom-int(height*.13),right,bottom),radius=28,fill=primary)
            _draw_wrapped(draw,footer,(width//2,bottom-int(height*.095)),tiny_font,"#FFFFFF",width-margin*2,8,"center",2)
        return image

    # Safe fallback retains poster hierarchy for future registered template aliases.
    y = int(height*.25)
    y = _draw_wrapped(draw,title,(margin*1.3,y),title_font,white,width-margin*2.6,10,"left",4)
    if subtitle:
        y += 22
        y = _draw_wrapped(draw,subtitle,(margin*1.3,y),sub_font,accent,width-margin*2.6,8,"left",3)
    if body:
        y += 28
        y = _draw_wrapped(draw,body,(margin*1.3,y),body_font,muted,width-margin*2.6,10,"left",6)
    if footer:
        _draw_wrapped(draw,footer,(width//2,bottom-margin),(width-margin*2),tiny_font,muted,width-margin*2,8,"center",2)
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
