"""Conservative, page-aware PDF reconstruction for the selective Humanizer.

Only exact whole-word selections that can be mapped to one horizontal text run
are editable. Unsupported layouts are rejected instead of being guessed.
The source PDF is processed in memory and is never overwritten or persisted.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from ai.pdf_processor import normalize_text, validate_pdf_bytes

MAX_PDF_REPLACEMENTS = 40


class HumanizerPDFError(ValueError):
    """A requested PDF edit cannot be applied without risking document damage."""


def _load_pymupdf():
    try:
        import pymupdf
    except ImportError as exc:  # pragma: no cover - deployment dependency guard
        raise HumanizerPDFError("PDF reconstruction is unavailable because PyMuPDF is not installed.") from exc
    return pymupdf


def _open_pdf(data: bytes):
    validate_pdf_bytes(data)
    pymupdf = _load_pymupdf()
    try:
        document = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise HumanizerPDFError("The uploaded PDF could not be opened. It may be encrypted or damaged.") from exc
    if document.is_encrypted:
        document.close()
        raise HumanizerPDFError("Encrypted PDFs are not supported. Remove the password and upload the PDF again.")
    return pymupdf, document


def _word_map(page) -> tuple[str, list[dict[str, Any]]]:
    """Build normalized page text and a word-to-coordinate map from native text."""
    rows = page.get_text("words", sort=True)
    parts: list[str] = []
    words: list[dict[str, Any]] = []
    cursor = 0
    previous_line: tuple[int, int] | None = None

    for row in rows:
        if len(row) < 8:
            continue
        x0, y0, x1, y1, raw_word, block_no, line_no, word_no = row[:8]
        token = " ".join(str(raw_word or "").split())
        if not token:
            continue
        line_key = (int(block_no), int(line_no))
        separator = "\n" if previous_line is not None and line_key != previous_line else (" " if previous_line is not None else "")
        if separator:
            parts.append(separator)
            cursor += len(separator)
        start = cursor
        parts.append(token)
        cursor += len(token)
        words.append({
            "text": token,
            "start": start,
            "end": cursor,
            "line": line_key,
            "word_no": int(word_no),
            "bbox": (float(x0), float(y0), float(x1), float(y1)),
        })
        previous_line = line_key

    mapped_text = "".join(parts).strip()
    return mapped_text, words


def _layout_for_page(page) -> tuple[str, list[dict[str, Any]], bool]:
    native_text = normalize_text(page.get_text("text", sort=True))
    mapped_text, words = _word_map(page)
    supported = bool(words) and mapped_text == native_text
    return native_text, words, supported


def inspect_pdf_layout(data: bytes) -> list[dict[str, Any]]:
    """Report whether pages have reliable native word geometry for PDF editing."""
    _pymupdf, document = _open_pdf(data)
    try:
        results = []
        for index, page in enumerate(document):
            native_text, _words, supported = _layout_for_page(page)
            reason = "" if supported else (
                "This page has no reliable native text geometry. It may be scanned, OCR-only, "
                "or use a text layout that cannot be mapped safely."
            )
            results.append({
                "page": index + 1,
                "layout_supported": supported,
                "native_characters": len(native_text),
                "reason": reason,
            })
        return results
    finally:
        document.close()


def _normalize_font_name(value: str) -> str:
    name = str(value or "").split("+")[-1].lower()
    return re.sub(r"[^a-z0-9]", "", name)


def _font_for_span(document, page, span: dict[str, Any], pymupdf):
    """Reuse an embedded source font; allow only regular Base-14 fallbacks."""
    span_name = str(span.get("font") or "")
    normalized = _normalize_font_name(span_name)

    for entry in page.get_fonts(full=True):
        if len(entry) < 5:
            continue
        xref, _ext, _kind, basefont, resource_name = entry[:5]
        if normalized not in {
            _normalize_font_name(str(basefont)),
            _normalize_font_name(str(resource_name)),
        }:
            continue
        try:
            extracted = document.extract_font(int(xref))
            font_bytes = extracted[3] if len(extracted) > 3 else b""
            if not font_bytes:
                continue
            alias = f"RH{int(xref):x}"
            page.insert_font(fontname=alias, fontbuffer=font_bytes)
            font_object = pymupdf.Font(fontbuffer=font_bytes)
            return alias, font_object
        except Exception:
            continue

    flags = int(span.get("flags") or 0)
    # Do not silently turn a bold / italic / unknown font into a different face.
    if flags & (2 | 16):
        raise HumanizerPDFError("This text uses a non-regular font that cannot be reused safely.")
    if normalized == "helvetica":
        font_name = "helv"
    elif normalized == "timesroman":
        font_name = "tiro"
    elif normalized == "courier":
        font_name = "cour"
    else:
        raise HumanizerPDFError(
            f"The source font '{span_name or 'unknown'}' cannot be embedded for a safe replacement."
        )
    return font_name, pymupdf.Font(fontname=font_name)


def _find_span(page, target_rect, pymupdf):
    data = page.get_text("dict", sort=True)
    for block in data.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            direction = line.get("dir") or (1.0, 0.0)
            if abs(float(direction[0]) - 1.0) > 0.002 or abs(float(direction[1])) > 0.002:
                continue
            for span in line.get("spans", []):
                raw_bbox = span.get("bbox")
                if not raw_bbox or not span.get("text"):
                    continue
                bbox = pymupdf.Rect(raw_bbox)
                if (
                    bbox.x0 <= target_rect.x0 + 0.6
                    and bbox.y0 <= target_rect.y0 + 1.0
                    and bbox.x1 >= target_rect.x1 - 0.6
                    and bbox.y1 >= target_rect.y1 - 1.0
                ):
                    return span, line
    raise HumanizerPDFError(
        "The selected words cross font/style runs or do not share one horizontal text run. "
        "Select a shorter phrase within one consistently formatted line."
    )


def _overlap_area(left, right) -> float:
    width = max(0.0, min(left[2], right[2]) - max(left[0], right[0]))
    height = max(0.0, min(left[3], right[3]) - max(left[1], right[1]))
    return width * height


def _locate_edit(page, page_text: str, words: list[dict[str, Any]], item: dict[str, Any], pymupdf):
    try:
        start = int(item["start"])
        end = int(item["end"])
        page_number = int(item["page"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HumanizerPDFError("Each replacement needs a valid page number and start/end offsets.") from exc

    original = str(item.get("original") or "")
    replacement = str(item.get("replacement") or "")
    if start < 0 or end <= start or end > len(page_text) or page_text[start:end] != original:
        raise HumanizerPDFError(
            "A selected passage no longer matches the uploaded PDF. Re-extract the PDF and review the changes again."
        )
    if not replacement or len(replacement) > 500 or any(ch in replacement for ch in "\r\n\t"):
        raise HumanizerPDFError("Replacement text must be one non-empty line of at most 500 characters.")

    first_index = next((i for i, word in enumerate(words) if word["start"] == start), None)
    last_index = next((i for i, word in enumerate(words) if word["end"] == end), None)
    if first_index is None or last_index is None or last_index < first_index:
        raise HumanizerPDFError(
            "PDF export supports complete words only. Select from the start of the first word "
            "through the end of the last word; partial-word selections remain available as text edits."
        )

    selected_words = words[first_index:last_index + 1]
    if not selected_words or any(word["line"] != selected_words[0]["line"] for word in selected_words):
        raise HumanizerPDFError("PDF export currently supports selections on one visual line only.")

    x0 = min(word["bbox"][0] for word in selected_words)
    y0 = min(word["bbox"][1] for word in selected_words)
    x1 = max(word["bbox"][2] for word in selected_words)
    y1 = max(word["bbox"][3] for word in selected_words)
    target_rect = pymupdf.Rect(x0, y0, x1, y1)
    if target_rect.is_empty or target_rect.is_infinite:
        raise HumanizerPDFError("The selected passage has no usable PDF coordinates.")

    # Redaction must not touch any unselected word. This catches unusual
    # overlapping text layers, side notes, and tightly packed multi-column text.
    for index, word in enumerate(words):
        if first_index <= index <= last_index:
            continue
        if _overlap_area(word["bbox"], tuple(target_rect)) > 0.25:
            raise HumanizerPDFError(
                "The selected area overlaps nearby unselected text. No PDF was generated."
            )

    span, line = _find_span(page, target_rect, pymupdf)
    size = float(span.get("size") or 0)
    if size <= 0:
        raise HumanizerPDFError("The source font size could not be read.")
    font_name, font_object = _font_for_span(page.parent, page, span, pymupdf)
    if any(not font_object.has_glyph(ord(character)) for character in replacement):
        raise HumanizerPDFError("The source font does not contain every character in the replacement.")

    replacement_width = float(font_object.text_length(replacement, fontsize=size))
    # A little safety margin accounts for PDF text-metric rounding.
    if replacement_width > target_rect.width - 0.6:
        raise HumanizerPDFError(
            "The replacement is wider than the selected text. Choose a shorter alternative "
            "so nearby content and the original layout are not disturbed."
        )

    origin = span.get("origin") or (target_rect.x0, target_rect.y1)
    baseline_y = float(origin[1])
    color_value = int(span.get("color") or 0)
    color = (
        ((color_value >> 16) & 255) / 255.0,
        ((color_value >> 8) & 255) / 255.0,
        (color_value & 255) / 255.0,
    )

    return {
        "page": page_number,
        "start": start,
        "end": end,
        "original": original,
        "replacement": replacement,
        "rect": target_rect,
        "point": (target_rect.x0, baseline_y),
        "font_name": font_name,
        "font_size": size,
        "color": color,
    }


def reconstruct_pdf(data: bytes, replacements: list[dict[str, Any]]) -> tuple[bytes, dict[str, Any]]:
    """Apply individually approved page-offset edits and return a new PDF in memory."""
    if not isinstance(replacements, list) or not replacements:
        raise HumanizerPDFError("Approve at least one replacement before creating a revised PDF.")
    if len(replacements) > MAX_PDF_REPLACEMENTS:
        raise HumanizerPDFError(f"Apply no more than {MAX_PDF_REPLACEMENTS} replacements in one PDF export.")

    pymupdf, document = _open_pdf(data)
    try:
        if document.page_count > 100:
            raise HumanizerPDFError("PDF reconstruction is limited to 100 pages per export.")

        page_texts: dict[int, str] = {}
        page_words: dict[int, list[dict[str, Any]]] = {}
        page_edits: dict[int, list[dict[str, Any]]] = defaultdict(list)

        for item in replacements:
            if not isinstance(item, dict):
                raise HumanizerPDFError("Each accepted replacement must be an object.")
            try:
                page_number = int(item["page"])
            except (KeyError, TypeError, ValueError) as exc:
                raise HumanizerPDFError("Each replacement needs a valid 1-based page number.") from exc
            if page_number < 1 or page_number > document.page_count:
                raise HumanizerPDFError("A replacement refers to a page outside this PDF.")
            page_index = page_number - 1
            if page_index not in page_texts:
                source_text, words, supported = _layout_for_page(document[page_index])
                if not supported:
                    raise HumanizerPDFError(
                        f"Page {page_number} does not expose reliable native text geometry. "
                        "Scanned/OCR pages and unsupported layouts are preserved unchanged."
                    )
                page_texts[page_index] = source_text
                page_words[page_index] = words
            page_edits[page_index].append(
                _locate_edit(document[page_index], page_texts[page_index], page_words[page_index], item, pymupdf)
            )

        expected_texts = dict(page_texts)
        for page_index, edits in page_edits.items():
            edits.sort(key=lambda edit: edit["start"])
            for previous, current in zip(edits, edits[1:]):
                if previous["end"] > current["start"]:
                    raise HumanizerPDFError("Overlapping accepted replacements are not allowed.")
                if previous["rect"].intersects(current["rect"]):
                    raise HumanizerPDFError("Selected PDF areas overlap. Apply one non-overlapping replacement at a time.")
            expected = expected_texts[page_index]
            for edit in reversed(edits):
                expected = expected[:edit["start"]] + edit["replacement"] + expected[edit["end"]:]
            expected_texts[page_index] = expected

        # Mark only selected glyph areas for text redaction. Images and vector
        # graphics are explicitly retained; fill=None avoids painting a white
        # rectangle over a colored cell or page background.
        for page_index, edits in page_edits.items():
            page = document[page_index]
            for edit in edits:
                page.add_redact_annot(edit["rect"], fill=None, cross_out=False)
            page.apply_redactions(images=0, graphics=0)

        for page_index, edits in page_edits.items():
            page = document[page_index]
            for edit in edits:
                page.insert_text(
                    edit["point"],
                    edit["replacement"],
                    fontsize=edit["font_size"],
                    fontname=edit["font_name"],
                    color=edit["color"],
                    overlay=True,
                )

        # Fail closed: re-extract each edited page and require an exact textual
        # match with the expected offset-based result before returning bytes.
        for page_index, expected in expected_texts.items():
            actual = normalize_text(document[page_index].get_text("text", sort=True))
            if actual != expected:
                raise HumanizerPDFError(
                    "The edited page did not pass text-integrity validation. No revised PDF was returned."
                )

        output = document.tobytes(garbage=4, deflate=True)
        # Verify the generated file can be reopened and retains the page count.
        verification = pymupdf.open(stream=output, filetype="pdf")
        try:
            if verification.page_count != document.page_count:
                raise HumanizerPDFError("The generated PDF did not retain the original page count.")
        finally:
            verification.close()

        change_count = sum(len(edits) for edits in page_edits.values())
        return output, {
            "accepted_replacements": change_count,
            "changed_pages": len(page_edits),
            "page_count": document.page_count,
            "model_used": False,
            "original_modified": False,
            "layout_policy": "conservative-single-line-native-text",
        }
    except HumanizerPDFError:
        raise
    except Exception as exc:
        raise HumanizerPDFError(
            "PDF reconstruction failed safely. The source PDF was not changed and no output was produced."
        ) from exc
    finally:
        document.close()


__all__ = [
    "HumanizerPDFError",
    "inspect_pdf_layout",
    "reconstruct_pdf",
    "MAX_PDF_REPLACEMENTS",
]
