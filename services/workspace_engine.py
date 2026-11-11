"""Bounded deterministic processors used by the authenticated workspace API."""
from __future__ import annotations
import ast, base64, binascii, csv, io, json, math, re, statistics
from collections import Counter
from typing import Any
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

MAX_ROWS = 10_000
MAX_COLUMNS = 100
MAX_IMAGE_BYTES = 4 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000
_CODE_LANGUAGES = {
    "python": (".py", "text/x-python"), "py": (".py", "text/x-python"),
    "javascript": (".js", "text/javascript"), "js": (".js", "text/javascript"),
    "typescript": (".ts", "text/typescript"), "ts": (".ts", "text/typescript"),
    "tsx": (".tsx", "text/typescript"), "jsx": (".jsx", "text/javascript"),
    "html": (".html", "text/html"), "css": (".css", "text/css"),
    "json": (".json", "application/json"), "sql": (".sql", "application/sql"),
    "bash": (".sh", "text/x-shellscript"), "sh": (".sh", "text/x-shellscript"),
    "go": (".go", "text/x-go"), "golang": (".go", "text/x-go"),
    "rust": (".rs", "text/x-rust"), "rs": (".rs", "text/x-rust"),
    "java": (".java", "text/x-java"), "c": (".c", "text/x-c"),
    "cpp": (".cpp", "text/x-c++src"), "c++": (".cpp", "text/x-c++src"),
    "csharp": (".cs", "text/x-csharp"), "c#": (".cs", "text/x-csharp"),
    "php": (".php", "application/x-httpd-php"), "ruby": (".rb", "text/x-ruby"),
    "swift": (".swift", "text/x-swift"), "kotlin": (".kt", "text/x-kotlin"),
}

def _cell_text(value: Any) -> str:
    if value is None: return ""
    if isinstance(value, (dict, list, tuple)): return json.dumps(value, ensure_ascii=False, default=str)[:1000]
    return str(value).strip()[:1000]

def parse_dataset(source: Any) -> tuple[list[str], list[list[Any]]]:
    """Normalize CSV text, row arrays, or row objects into a bounded table."""
    if isinstance(source, str):
        if len(source.encode("utf-8")) > 8 * 1024 * 1024: raise ValueError("CSV input exceeds the 8 MB limit.")
        parsed = list(csv.reader(io.StringIO(source)))
        if not parsed: raise ValueError("The supplied dataset is empty.")
        headers = [str(v).strip()[:200] or f"Column {i + 1}" for i, v in enumerate(parsed[0])]
        rows = parsed[1:]
    elif isinstance(source, dict):
        headers, rows = source.get("headers"), source.get("rows")
        if not isinstance(headers, list) or not isinstance(rows, list):
            raise ValueError("Dataset objects must contain headers and rows arrays.")
        headers = [str(v).strip()[:200] or f"Column {i + 1}" for i, v in enumerate(headers)]
    elif isinstance(source, list) and source and all(isinstance(v, dict) for v in source):
        headers = list(dict.fromkeys(str(k)[:200] for row in source for k in row))
        rows = [[row.get(header) for header in headers] for row in source]
    elif isinstance(source, list) and source and all(isinstance(v, (list, tuple)) for v in source):
        headers = [f"Column {i + 1}" for i in range(max(len(row) for row in source))]
        rows = source
    else:
        raise ValueError("Provide CSV text, a headers/rows table, or an array of row objects.")
    if not headers or len(headers) > MAX_COLUMNS: raise ValueError(f"Datasets must contain between 1 and {MAX_COLUMNS} columns.")
    if len(rows) > MAX_ROWS: raise ValueError(f"Datasets may contain at most {MAX_ROWS:,} rows.")
    if len({name.casefold() for name in headers}) != len(headers): raise ValueError("Column names must be unique.")
    normalized = []
    for row_index, row in enumerate(rows):
        values = [row.get(header) for header in headers] if isinstance(row, dict) else list(row) if isinstance(row, (list, tuple)) else None
        if values is None: raise ValueError(f"Dataset row {row_index + 1} is not an array or object.")
        if len(values) > MAX_COLUMNS: raise ValueError(f"Dataset row {row_index + 1} exceeds {MAX_COLUMNS} columns.")
        values = (values + [None] * len(headers))[:len(headers)]
        normalized.append([_cell_text(value) for value in values])
    if not normalized: raise ValueError("The supplied dataset has headers but no data rows.")
    return headers, normalized

def _numeric(value: Any) -> float | None:
    if value is None or isinstance(value, bool): return None
    try: number = float(str(value).strip().replace(",", ""))
    except (TypeError, ValueError, OverflowError): return None
    return number if math.isfinite(number) else None

def analyze_dataset(source: Any) -> dict[str, Any]:
    """Produce reproducible descriptive statistics and workbook-ready tables."""
    headers, rows = parse_dataset(source)
    duplicate_count = len(rows) - len({json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows})
    profiles, numeric_stats, category_rows = [], [["Column", "Count", "Mean", "Median", "Minimum", "Maximum", "Std. deviation"]], [["Column", "Value", "Frequency"]]
    missing_total = 0
    for column_index, name in enumerate(headers):
        values = [row[column_index] for row in rows]
        present = [value for value in values if str(value).strip()]
        missing = len(values) - len(present); missing_total += missing
        numeric = [_numeric(value) for value in present]
        numbers = [value for value in numeric if value is not None]
        is_numeric = bool(numbers) and len(numbers) == len(present)
        profile = {"column": name, "type": "numeric" if is_numeric else "categorical",
                   "non_empty": len(present), "missing": missing,
                   "missing_pct": round(missing / len(rows) * 100, 2),
                   "unique": len({str(value) for value in present})}
        if is_numeric:
            mean, median = statistics.fmean(numbers), statistics.median(numbers)
            deviation = statistics.stdev(numbers) if len(numbers) > 1 else 0.0
            stats = {"mean": round(mean, 6), "median": round(median, 6), "minimum": min(numbers),
                     "maximum": max(numbers), "standard_deviation": round(deviation, 6)}
            profile["statistics"] = stats
            numeric_stats.append([name, len(numbers), stats["mean"], stats["median"], stats["minimum"], stats["maximum"], stats["standard_deviation"]])
        else:
            top = Counter(str(value) for value in present).most_common(10)
            profile["top_values"] = [{"value": value, "count": count} for value, count in top]
            category_rows.extend([[name, value, count] for value, count in top])
        profiles.append(profile)
    completeness = round(100 * (1 - missing_total / max(1, len(rows) * len(headers))), 2)
    workbook_payload = {"title": "RevelaAI Dataset Analysis", "sheets": [
        {"name": "Data Quality", "headers": ["Metric", "Value"], "rows": [
            ["Rows", len(rows)], ["Columns", len(headers)], ["Missing cells", missing_total],
            ["Duplicate rows", duplicate_count], ["Completeness (%)", completeness]]},
        {"name": "Column Profiles", "headers": ["Column", "Type", "Non-empty", "Missing", "Missing %", "Unique"],
         "rows": [[p["column"], p["type"], p["non_empty"], p["missing"], p["missing_pct"], p["unique"]] for p in profiles]},
        {"name": "Numeric Statistics", "headers": numeric_stats[0], "rows": numeric_stats[1:]},
        {"name": "Top Categories", "headers": category_rows[0], "rows": category_rows[1:5001]},
        {"name": "Dataset Preview", "headers": headers, "rows": rows[:4999]},
    ]}
    return {"row_count": len(rows), "column_count": len(headers), "duplicate_rows": duplicate_count,
            "missing_cells": missing_total, "completeness_pct": completeness, "columns": profiles,
            "workbook_payload": workbook_payload, "dataset_truncated_in_workbook": len(rows) > 4999}

def render_analysis_chart(analysis: dict[str, Any]) -> bytes | None:
    """Render a compact deterministic chart for the first numeric column."""
    profiles = analysis.get("columns") if isinstance(analysis, dict) else None
    selected = next((p for p in profiles or [] if p.get("type") == "numeric" and p.get("statistics")), None)
    if not selected: return None
    stats = selected["statistics"]; labels = ["Min", "Median", "Mean", "Max"]
    values = [float(stats["minimum"]), float(stats["median"]), float(stats["mean"]), float(stats["maximum"])]
    image = Image.new("RGB", (1000, 560), "#FFFFFF"); draw = ImageDraw.Draw(image)
    draw.text((48, 28), f"{selected['column'][:80]} — numeric distribution", fill="#132238", font=ImageFont.load_default(size=23))
    left, top, right, bottom = 90, 110, 940, 455
    draw.line((left, bottom, right, bottom), fill="#667085", width=2); draw.line((left, top, left, bottom), fill="#667085", width=2)
    low, high = min(values), max(values); span = high - low or 1.0
    palette = ["#0A74DA", "#2E8B57", "#D4AF37", "#0A74DA"]
    for index, (label, value) in enumerate(zip(labels, values)):
        x = left + 65 + index * 205; bar_height = int(55 + ((value - low) / span) * 225); y = bottom - bar_height
        draw.rounded_rectangle((x, y, x + 110, bottom), radius=10, fill=palette[index])
        draw.text((x + 20, bottom + 16), label, fill="#344054", font=ImageFont.load_default(size=18))
        draw.text((x, max(top, y - 24)), f"{value:.4g}"[:20], fill="#132238", font=ImageFont.load_default(size=16))
    output = io.BytesIO(); image.save(output, format="PNG", optimize=True)
    return output.getvalue()

def edit_image(image_value: str, mime_type: str, operations: list[dict[str, Any]]) -> tuple[bytes, int, int]:
    """Apply a whitelist of bounded Pillow edits; source image bytes remain ephemeral."""
    encoded = str(image_value or "").strip()
    if encoded.startswith("data:"):
        header, separator, encoded = encoded.partition(",")
        if not separator or ";base64" not in header.lower(): raise ValueError("Image data must be a base64 data URL.")
        declared = header[5:].split(";", 1)[0].lower()
        if mime_type and declared != mime_type.lower(): raise ValueError("Image data URL and MIME type do not match.")
        mime_type = declared
    allowed = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}
    if mime_type not in allowed: raise ValueError("Image MIME type must be JPEG, PNG, or WEBP.")
    if len(encoded) > ((MAX_IMAGE_BYTES + 2) // 3) * 4 + 8: raise ValueError("Image exceeds the 4 MB limit.")
    try: raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc: raise ValueError("Image data is not valid base64.") from exc
    if not raw or len(raw) > MAX_IMAGE_BYTES: raise ValueError("Image must be non-empty and no larger than 4 MB.")
    try:
        with Image.open(io.BytesIO(raw)) as source:
            if source.format != allowed[mime_type]: raise ValueError("Image MIME type does not match its actual format.")
            if source.width < 1 or source.height < 1 or source.width * source.height > MAX_IMAGE_PIXELS:
                raise ValueError("Image dimensions are invalid or exceed 20 megapixels.")
            source.verify()
        with Image.open(io.BytesIO(raw)) as source: image = ImageOps.exif_transpose(source).convert("RGBA")
    except (OSError, Image.DecompressionBombError) as exc: raise ValueError("Image content is invalid or unsupported.") from exc
    if not isinstance(operations, list) or len(operations) > 12: raise ValueError("Provide up to 12 supported image-edit operations.")
    for operation in operations:
        if not isinstance(operation, dict): raise ValueError("Each image-edit operation must be an object.")
        name = str(operation.get("type") or "").strip().lower()
        if name in {"brightness", "contrast", "saturation", "sharpness"}:
            factor = float(operation.get("factor", 1.0))
            if not 0.2 <= factor <= 3.0: raise ValueError(f"{name} factor must be between 0.2 and 3.")
            image = getattr(ImageEnhance, name.title())(image).enhance(factor)
        elif name == "grayscale": image = ImageOps.grayscale(image).convert("RGBA")
        elif name == "invert":
            alpha = image.getchannel("A"); image = ImageOps.invert(image.convert("RGB")).convert("RGBA"); image.putalpha(alpha)
        elif name == "blur":
            radius = float(operation.get("radius", 1.5))
            if not 0.1 <= radius <= 8: raise ValueError("Blur radius must be between 0.1 and 8.")
            image = image.filter(ImageFilter.GaussianBlur(radius=radius))
        elif name == "rotate":
            degrees = float(operation.get("degrees", 0))
            if not -360 <= degrees <= 360: raise ValueError("Rotation must be between -360 and 360 degrees.")
            image = image.rotate(-degrees, expand=True, resample=Image.Resampling.BICUBIC)
        elif name == "flip":
            direction = str(operation.get("direction") or "horizontal").lower()
            if direction == "horizontal": image = ImageOps.mirror(image)
            elif direction == "vertical": image = ImageOps.flip(image)
            else: raise ValueError("Flip direction must be horizontal or vertical.")
        elif name == "crop":
            left, top, right, bottom = [float(operation.get(k, d)) for k, d in (("left", 0), ("top", 0), ("right", 1), ("bottom", 1))]
            if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1): raise ValueError("Crop coordinates must be normalized fractions between 0 and 1.")
            image = image.crop((int(left * image.width), int(top * image.height), int(right * image.width), int(bottom * image.height)))
        elif name == "resize":
            width, height = int(operation.get("width", image.width)), int(operation.get("height", image.height))
            if not (1 <= width <= 2600 and 1 <= height <= 2600 and width * height <= MAX_IMAGE_PIXELS):
                raise ValueError("Resize dimensions must be 1–2,600 pixels per side.")
            image.thumbnail((width, height), Image.Resampling.LANCZOS)
        elif name == "text":
            text_value, color = str(operation.get("text") or ""), str(operation.get("color") or "#FFFFFF")
            x, y, size = float(operation.get("x", 0.08)), float(operation.get("y", 0.82)), int(operation.get("font_size", 36))
            if not text_value or len(text_value) > 300 or not re.fullmatch(r"#[0-9A-Fa-f]{6}", color):
                raise ValueError("Text overlays need 1–300 characters and a #RRGGBB color.")
            if not (0 <= x <= 1 and 0 <= y <= 1 and 8 <= size <= 160): raise ValueError("Text position must be 0–1 and font size 8–160.")
            ImageDraw.Draw(image).text((int(x * image.width), int(y * image.height)), text_value,
                font=ImageFont.load_default(size=size), fill=color, stroke_width=1, stroke_fill="#101828")
        else: raise ValueError(f"Unsupported image-edit operation: {name or 'missing type'}.")
    output = io.BytesIO(); image.save(output, format="PNG", optimize=True)
    return output.getvalue(), image.width, image.height

def markdown_to_sections(markdown: str) -> list[dict[str, Any]]:
    """Convert generated Markdown to bounded editable DOCX sections."""
    sections: list[dict[str, Any]] = []; current: dict[str, Any] = {"heading": "", "paragraphs": []}
    for raw_line in str(markdown or "").splitlines():
        line = raw_line.strip()
        if not line: continue
        heading = re.match(r"^(#{1,3})\s+(.+)$", line)
        if heading:
            if current["heading"] or current["paragraphs"]: sections.append(current)
            current = {"heading": heading.group(2)[:180], "paragraphs": []}
        elif line.startswith(("- ", "* ", "• ")): current["paragraphs"].append("• " + line[2:][:12000])
        elif re.match(r"^\d+[.)]\s+", line): current["paragraphs"].append(line[:12000])
        else: current["paragraphs"].append(line[:12000])
    if current["heading"] or current["paragraphs"]: sections.append(current)
    return sections[:80] or [{"heading": "Content", "paragraphs": [str(markdown or "")[:12000]]}]

def markdown_to_slides(markdown: str, title: str) -> list[dict[str, Any]]:
    """Convert Markdown headings and bullets into editable PowerPoint slides."""
    slides: list[dict[str, Any]] = []; current = {"title": title[:180], "bullets": []}
    for raw_line in str(markdown or "").splitlines():
        line = raw_line.strip()
        if not line: continue
        heading = re.match(r"^#{1,2}\s+(.+)$", line)
        if heading:
            if current["bullets"] or slides: slides.append(current)
            current = {"title": heading.group(1)[:180], "bullets": []}
        elif line.startswith(("- ", "* ", "• ")): current["bullets"].append(line[2:][:500])
        else: current["bullets"].append(line[:500])
        if len(current["bullets"]) >= 12:
            slides.append(current); current = {"title": f"{title[:150]} — continued", "bullets": []}
    if current["bullets"] or not slides: slides.append(current)
    return slides[:80]

def extract_code_block(response: str, language_hint: str = "") -> tuple[str, str, str, str]:
    """Extract one code artifact and validate syntax where a parser is available."""
    match = re.search(r"\x60{3}([A-Za-z0-9_+-]*)\s*\n(.*?)\x60{3}", str(response or ""), re.DOTALL)
    if not match: raise ValueError("The model did not return a fenced code block; no source file was created.")
    language = (match.group(1) or language_hint or "").strip().lower()
    extension, mime = _CODE_LANGUAGES.get(language, (".txt", "text/plain"))
    code = match.group(2).strip() + "\n"
    if not code.strip() or len(code.encode("utf-8")) > 30_000: raise ValueError("Generated source must be non-empty and no larger than 30 KB.")
    validation = "not_available"
    if extension == ".py":
        try: ast.parse(code)
        except SyntaxError as exc: raise ValueError(f"Generated Python failed syntax validation at line {exc.lineno}: {exc.msg}") from exc
        validation = "python_ast"
    elif extension == ".json":
        try: json.loads(code)
        except json.JSONDecodeError as exc: raise ValueError(f"Generated JSON is invalid at line {exc.lineno}: {exc.msg}") from exc
        validation = "json_parse"
    return code, extension, mime, validation
