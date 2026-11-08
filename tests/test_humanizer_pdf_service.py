"""Regression tests for conservative page-aware Humanizer PDF reconstruction."""
import base64

import pytest
import pymupdf

from ai.pdf_processor import normalize_text
from services.humanizer_pdf_service import HumanizerPDFError, inspect_pdf_layout, reconstruct_pdf


def make_pdf(*page_texts: str, with_image: bool = False) -> bytes:
    document = pymupdf.open()
    for text in page_texts:
        page = document.new_page(width=612, height=792)
        if text:
            page.insert_text((72, 90), text, fontsize=12, fontname="helv")
        if with_image:
            # A tiny embedded image proves redaction does not rasterize/remove
            # page artwork outside the selected text.
            png = base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jvS8AAAAASUVORK5CYII="
            )
            page.insert_image(pymupdf.Rect(72, 120, 92, 140), stream=png)
        page.draw_rect(pymupdf.Rect(70, 70, 500, 110), color=(0, 0, 0), width=0.4)
    output = document.tobytes()
    document.close()
    return output


def read_pages(data: bytes) -> list[str]:
    document = pymupdf.open(stream=data, filetype="pdf")
    try:
        return [normalize_text(page.get_text("text", sort=True)) for page in document]
    finally:
        document.close()


def replacement(page: int, source: str, phrase: str, new_text: str, *, occurrence: int = 0):
    start = -1
    for _ in range(occurrence + 1):
        start = source.find(phrase, start + 1)
        assert start >= 0
    return {
        "page": page,
        "start": start,
        "end": start + len(phrase),
        "original": phrase,
        "replacement": new_text,
    }


def test_layout_inspection_marks_native_text_as_editable_and_scans_as_unsupported():
    native = make_pdf("This page contains readable native PDF text.")
    layout = inspect_pdf_layout(native)
    assert layout[0]["layout_supported"] is True
    assert layout[0]["native_characters"] > 0

    scanned = make_pdf("")
    scanned_layout = inspect_pdf_layout(scanned)
    assert scanned_layout[0]["layout_supported"] is False


def test_reconstructs_only_the_selected_repeated_phrase_occurrence():
    source = "We make use of tools. Later, make use of tools."
    original_pdf = make_pdf(source)
    selected = replacement(1, source, "make use of", "use", occurrence=1)

    revised_pdf, metadata = reconstruct_pdf(original_pdf, [selected])

    assert read_pages(revised_pdf) == ["We make use of tools. Later, use tools."]
    assert read_pages(original_pdf) == [source]
    assert metadata["accepted_replacements"] == 1
    assert metadata["changed_pages"] == 1
    assert metadata["original_modified"] is False
    assert metadata["model_used"] is False


def test_reconstructs_multiple_pages_and_preserves_unedited_page_text():
    first = "We make use of a careful method."
    second = "The report is approximately complete."
    original_pdf = make_pdf(first, second)
    edits = [
        replacement(1, first, "make use of", "use"),
        replacement(2, second, "approximately", "about"),
    ]

    revised_pdf, metadata = reconstruct_pdf(original_pdf, edits)

    assert read_pages(revised_pdf) == [
        "We use a careful method.",
        "The report is about complete.",
    ]
    assert metadata["page_count"] == 2
    assert metadata["changed_pages"] == 2
    assert len(read_pages(original_pdf)) == 2


def test_preserves_embedded_images_and_vector_graphics():
    source = "We make use of this image."
    original_pdf = make_pdf(source, with_image=True)
    before = pymupdf.open(stream=original_pdf, filetype="pdf")
    before_images = len(before[0].get_images(full=True))
    before.close()

    revised_pdf, _metadata = reconstruct_pdf(
        original_pdf,
        [replacement(1, source, "make use of", "use")],
    )

    after = pymupdf.open(stream=revised_pdf, filetype="pdf")
    try:
        assert len(after[0].get_images(full=True)) == before_images
        assert len(after[0].get_drawings()) >= 1
    finally:
        after.close()


def test_rejects_partial_word_selection_without_returning_a_pdf():
    source = "We utilize a careful method."
    original_pdf = make_pdf(source)
    start = source.index("til")
    with pytest.raises(HumanizerPDFError, match="complete words"):
        reconstruct_pdf(original_pdf, [{
            "page": 1,
            "start": start,
            "end": start + 3,
            "original": "til",
            "replacement": "use",
        }])


def test_rejects_replacement_that_would_overflow_original_text_width():
    source = "We use this method."
    original_pdf = make_pdf(source)
    with pytest.raises(HumanizerPDFError, match="wider than the selected text"):
        reconstruct_pdf(original_pdf, [replacement(1, source, "use", "a substantially longer replacement")])


def test_rejects_cross_line_selection():
    document = pymupdf.open()
    page = document.new_page(width=612, height=792)
    page.insert_text((72, 90), "We make use", fontsize=12, fontname="helv")
    page.insert_text((72, 120), "of this method.", fontsize=12, fontname="helv")
    source_pdf = document.tobytes()
    document.close()
    source = "We make use\nof this method."
    with pytest.raises(HumanizerPDFError, match="one visual line"):
        reconstruct_pdf(source_pdf, [{
            "page": 1,
            "start": source.index("make"),
            "end": source.index("of") + len("of"),
            "original": "make use\nof",
            "replacement": "use",
        }])


def test_rejects_stale_offsets_and_repeated_source_mismatch():
    source = "We make use of tools."
    original_pdf = make_pdf(source)
    with pytest.raises(HumanizerPDFError, match="no longer matches"):
        reconstruct_pdf(original_pdf, [{
            "page": 1,
            "start": 3,
            "end": 14,
            "original": "different",
            "replacement": "use",
        }])


def test_rejects_overlapping_approved_edits():
    source = "We make use of this method."
    original_pdf = make_pdf(source)
    first = replacement(1, source, "make use of", "use")
    second = replacement(1, source, "use of", "use")
    with pytest.raises(HumanizerPDFError, match="Overlapping"):
        reconstruct_pdf(original_pdf, [first, second])


def test_rejects_ocr_only_page_for_pdf_reconstruction_but_keeps_original_intact():
    original_pdf = make_pdf("")
    with pytest.raises(HumanizerPDFError, match="does not expose reliable native text geometry"):
        reconstruct_pdf(original_pdf, [{
            "page": 1,
            "start": 0,
            "end": 4,
            "original": "scan",
            "replacement": "text",
        }])
    assert read_pages(original_pdf) == [""]
