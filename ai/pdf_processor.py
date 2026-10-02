# ai/pdf_processor.py

"""
RevelaAI PDF Processor

Responsibilities:

    - Validate PDF input
    - Inspect document metadata
    - Extract text page-by-page
    - Preserve page numbers
    - Detect pages with little/no text
    - Optionally run OCR
    - Produce bounded text chunks for RevelaAI
    - Never call the language model directly

Architecture:

    PDF
      |
      v
    PDFProcessor
      |
      +--> native PDF text extraction
      |
      +--> OCR fallback for scanned pages
      |
      v
    normalized pages
      |
      v
    bounded chunks
      |
      v
    RevelaAI orchestrator
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


# =========================================================
# CONFIGURATION
# =========================================================

PDF_MAX_BYTES = int(
    os.getenv(
        "PDF_MAX_BYTES",
        str(20 * 1024 * 1024),
    )
)

PDF_MAX_PAGES = int(
    os.getenv(
        "PDF_MAX_PAGES",
        "100",
    )
)

PDF_MAX_TEXT_CHARS = int(
    os.getenv(
        "PDF_MAX_TEXT_CHARS",
        "500000",
    )
)

PDF_CHUNK_CHARS = int(
    os.getenv(
        "PDF_CHUNK_CHARS",
        "8000",
    )
)

PDF_CHUNK_OVERLAP = int(
    os.getenv(
        "PDF_CHUNK_OVERLAP",
        "400",
    )
)

PDF_OCR_ENABLED = (
    os.getenv(
        "PDF_OCR_ENABLED",
        "true",
    )
    .strip()
    .lower()
    in {
        "1",
        "true",
        "yes",
        "on",
    }
)

PDF_OCR_LANGUAGE = (
    os.getenv(
        "PDF_OCR_LANGUAGE",
        "eng",
    )
    .strip()
    or "eng"
)

PDF_MIN_NATIVE_TEXT_CHARS = int(
    os.getenv(
        "PDF_MIN_NATIVE_TEXT_CHARS",
        "40",
    )
)


# =========================================================
# ERRORS
# =========================================================

class PDFProcessingError(Exception):
    """
    Raised when PDF processing fails.
    """

    def __init__(
        self,
        message: str,
        *,
        code: str = "pdf_processing_error",
    ):
        super().__init__(message)
        self.code = code


# =========================================================
# IMPORT
# =========================================================

def _load_pymupdf():
    try:
        import pymupdf

        return pymupdf

    except ImportError as exc:

        raise PDFProcessingError(
            "PyMuPDF is not installed.",
            code="pymupdf_missing",
        ) from exc


# =========================================================
# INPUT VALIDATION
# =========================================================

def validate_pdf_bytes(
    data: bytes,
) -> None:

    if not isinstance(
        data,
        bytes,
    ):

        raise PDFProcessingError(
            "PDF input must be bytes.",
            code="invalid_pdf_input",
        )

    if not data:

        raise PDFProcessingError(
            "PDF is empty.",
            code="empty_pdf",
        )

    if len(data) > PDF_MAX_BYTES:

        raise PDFProcessingError(
            "PDF exceeds the maximum allowed size.",
            code="pdf_too_large",
        )

    if not data.startswith(
        b"%PDF-"
    ):

        raise PDFProcessingError(
            "Uploaded file is not a valid PDF.",
            code="invalid_pdf_signature",
        )


# =========================================================
# TEXT NORMALIZATION
# =========================================================

def normalize_text(
    text: str,
) -> str:

    if not text:
        return ""

    lines = []

    for line in str(text).splitlines():

        cleaned = " ".join(
            line.strip().split()
        )

        if cleaned:
            lines.append(
                cleaned
            )

    return "\n".join(
        lines
    ).strip()


# =========================================================
# OCR
# =========================================================

def _ocr_page(
    page,
) -> str:

    try:

        text_page = page.get_textpage_ocr(
            language=PDF_OCR_LANGUAGE,
            dpi=150,
            full=True,
        )

        text = page.get_text(
            textpage=text_page,
            sort=True,
        )

        return normalize_text(
            text
        )

    except Exception as exc:

        raise PDFProcessingError(
            "OCR processing failed. "
            "Make sure Tesseract OCR is installed "
            "and configured correctly.",
            code="pdf_ocr_failed",
        ) from exc


# =========================================================
# PAGE EXTRACTION
# =========================================================

def extract_pdf_pages(
    data: bytes,
    *,
    enable_ocr: bool | None = None,
) -> list[dict[str, Any]]:

    validate_pdf_bytes(
        data
    )

    pymupdf = _load_pymupdf()

    use_ocr = (
        PDF_OCR_ENABLED
        if enable_ocr is None
        else bool(enable_ocr)
    )

    try:

        document = pymupdf.open(
            stream=data,
            filetype="pdf",
        )

    except Exception as exc:

        raise PDFProcessingError(
            "Could not open the PDF.",
            code="pdf_open_failed",
        ) from exc

    try:

        page_count = document.page_count

        if page_count > PDF_MAX_PAGES:

            raise PDFProcessingError(
                (
                    "PDF contains too many pages. "
                    f"Maximum allowed is {PDF_MAX_PAGES}."
                ),
                code="pdf_too_many_pages",
            )

        pages: list[dict[str, Any]] = []

        total_chars = 0

        for page_index in range(
            page_count
        ):

            page = document[
                page_index
            ]

            native_text = normalize_text(
                page.get_text(
                    "text",
                    sort=True,
                )
            )

            extraction_method = "native"

            text = native_text

            if (
                use_ocr
                and len(native_text)
                < PDF_MIN_NATIVE_TEXT_CHARS
            ):

                try:

                    ocr_text = _ocr_page(
                        page
                    )

                    if len(ocr_text) > len(
                        native_text
                    ):

                        text = ocr_text
                        extraction_method = "ocr"

                except PDFProcessingError:

                    # Preserve native text and continue.
                    # OCR failure on one page should not
                    # destroy the complete document.
                    pass

            total_chars += len(
                text
            )

            if total_chars > PDF_MAX_TEXT_CHARS:

                remaining = max(
                    0,
                    PDF_MAX_TEXT_CHARS
                    - (
                        total_chars
                        - len(text)
                    ),
                )

                text = text[
                    :remaining
                ]

                total_chars = PDF_MAX_TEXT_CHARS

            pages.append({
                "page": page_index + 1,
                "text": text,
                "characters": len(text),
                "method": extraction_method,
            })

            if total_chars >= PDF_MAX_TEXT_CHARS:
                break

        return pages

    finally:

        document.close()


# =========================================================
# FULL TEXT
# =========================================================

def join_pdf_text(
    pages: list[dict[str, Any]],
) -> str:

    sections = []

    for page in pages:

        page_number = page.get(
            "page"
        )

        text = str(
            page.get(
                "text",
                "",
            )
        ).strip()

        if not text:
            continue

        sections.append(
            (
                f"[Page {page_number}]\n"
                f"{text}"
            )
        )

    return "\n\n".join(
        sections
    ).strip()


# =========================================================
# CHUNKING
# =========================================================

def chunk_pdf_pages(
    pages: list[dict[str, Any]],
    *,
    chunk_chars: int | None = None,
    overlap: int | None = None,
) -> list[dict[str, Any]]:

    size = int(
        chunk_chars
        or PDF_CHUNK_CHARS
    )

    overlap_size = int(
        overlap
        if overlap is not None
        else PDF_CHUNK_OVERLAP
    )

    if size <= 0:
        raise PDFProcessingError(
            "PDF chunk size must be positive.",
            code="invalid_chunk_size",
        )

    if overlap_size < 0:
        overlap_size = 0

    if overlap_size >= size:
        overlap_size = max(
            0,
            size // 10,
        )

    chunks: list[
        dict[str, Any]
    ] = []

    current_text = ""
    current_start_page = None
    current_end_page = None
    chunk_index = 0

    for page in pages:

        page_number = int(
            page.get(
                "page",
                0,
            )
        )

        page_text = str(
            page.get(
                "text",
                "",
            )
        ).strip()

        if not page_text:
            continue

        page_section = (
            f"[Page {page_number}]\n"
            f"{page_text}"
        )

        if not current_text:

            current_text = page_section
            current_start_page = page_number
            current_end_page = page_number

            continue

        candidate = (
            current_text
            + "\n\n"
            + page_section
        )

        if len(candidate) <= size:

            current_text = candidate
            current_end_page = page_number

            continue

        chunk_index += 1

        chunks.append({
            "index": chunk_index,
            "text": current_text,
            "start_page": current_start_page,
            "end_page": current_end_page,
            "characters": len(
                current_text
            ),
        })

        overlap_text = (
            current_text[
                -overlap_size:
            ]
            if overlap_size
            else ""
        )

        current_text = (
            overlap_text
            + "\n\n"
            + page_section
        )

        current_start_page = page_number
        current_end_page = page_number

        if len(current_text) > size:

            current_text = current_text[
                -size:
            ]

    if current_text:

        chunk_index += 1

        chunks.append({
            "index": chunk_index,
            "text": current_text,
            "start_page": current_start_page,
            "end_page": current_end_page,
            "characters": len(
                current_text
            ),
        })

    return chunks


# =========================================================
# MAIN PROCESSOR
# =========================================================

def process_pdf(
    data: bytes,
    *,
    enable_ocr: bool | None = None,
    chunk_chars: int | None = None,
    overlap: int | None = None,
) -> dict[str, Any]:

    pages = extract_pdf_pages(
        data,
        enable_ocr=enable_ocr,
    )

    text = join_pdf_text(
        pages
    )

    chunks = chunk_pdf_pages(
        pages,
        chunk_chars=chunk_chars,
        overlap=overlap,
    )

    extracted_chars = sum(
        int(
            page.get(
                "characters",
                0,
            )
        )
        for page in pages
    )

    ocr_pages = sum(
        1
        for page in pages
        if page.get("method") == "ocr"
    )

    return {
        "success": True,

        "metadata": {
            "pages": len(pages),
            "characters": extracted_chars,
            "ocr_pages": ocr_pages,
            "has_text": bool(
                text.strip()
            ),
        },

        "pages": pages,

        "text": text,

        "chunks": chunks,
    }


__all__ = [
    "PDFProcessingError",
    "validate_pdf_bytes",
    "extract_pdf_pages",
    "join_pdf_text",
    "chunk_pdf_pages",
    "process_pdf",
]