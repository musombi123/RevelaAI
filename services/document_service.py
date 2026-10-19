"""Framework-neutral document ingestion and text extraction."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from services.runtime_config import DOCUMENT_MAX_MODEL_CHARS
from utils.docx_utils import extract_text_from_docx

logger = logging.getLogger("revelaai.document_service")


def process_uploaded_document(
    file_storage,
    *,
    prompt: str | None = None,
) -> tuple[str, dict[str, Any]]:

    if file_storage is None:

        raise ValueError(
            "No file was supplied."
        )

    filename = (
        file_storage.filename
        or ""
    ).strip()

    if not filename:

        raise ValueError(
            "Uploaded file has no filename."
        )

    safe_name = os.path.basename(
        filename
    )

    extension = (
        Path(
            safe_name
        ).suffix.lower()
    )

    data = file_storage.read()

    if not data:

        raise ValueError(
            "Uploaded file is empty."
        )

    # -----------------------------------------------------
    # PDF
    # -----------------------------------------------------

    if extension == ".pdf":

        try:

            from ai.pdf_processor import (
                process_pdf,
            )

        except ImportError as exc:

            raise RuntimeError(
                "PDF processor is not installed."
            ) from exc

        result = process_pdf(
            data
        )

        extracted_text = str(
            result.get(
                "text",
                "",
            )
            or ""
        ).strip()

        if not extracted_text:

            raise ValueError(
                "The PDF contains no readable text."
            )

        document_text = (
            extracted_text[
                :DOCUMENT_MAX_MODEL_CHARS
            ]
        )

        prompt = (
            (request.form.get("message", "") if prompt is None else prompt)
            or ""
        ).strip()

        if prompt:

            message = (
                f"{prompt}\n\n"
                f"Document: {safe_name}\n"
                f"Document content:\n"
                f"{document_text}"
            )

        else:

            message = (
                f"Analyze the following PDF "
                f"document: {safe_name}\n\n"
                f"{document_text}"
            )

        metadata = {
            "type": "pdf",
            "filename": safe_name,
            "mime_type": (
                file_storage.mimetype
                or "application/pdf"
            ),
            "pages": (
                result.get(
                    "metadata",
                    {},
                ).get(
                    "pages"
                )
            ),
            "chunks": len(
                result.get(
                    "chunks",
                    [],
                )
                if isinstance(
                    result.get(
                        "chunks",
                        [],
                    ),
                    list,
                )
                else []
            ),
            "ocr_pages": (
                result.get(
                    "metadata",
                    {},
                ).get(
                    "ocr_pages",
                    0,
                )
            ),
            "truncated_for_model": (
                len(extracted_text)
                > DOCUMENT_MAX_MODEL_CHARS
            ),
        }

        return (
            message,
            metadata,
        )

    # -----------------------------------------------------
    # DOCX
    # -----------------------------------------------------

    if extension == ".docx":

        content = str(
            extract_text_from_docx(
                data
            )
            or ""
        ).strip()

        if not content:

            raise ValueError(
                "The DOCX document contains no readable text."
            )

        content = content[
            :DOCUMENT_MAX_MODEL_CHARS
        ]

        prompt = (
            (request.form.get("message", "") if prompt is None else prompt)
            or ""
        ).strip()

        if prompt:

            message = (
                f"{prompt}\n\n"
                f"Document: {safe_name}\n"
                f"Document content:\n"
                f"{content}"
            )

        else:

            message = (
                f"Analyze the following document: "
                f"{safe_name}\n\n"
                f"{content}"
            )

        return (
            message,
            {
                "type": "docx",
                "filename": safe_name,
                "mime_type": (
                    file_storage.mimetype
                    or (
                        "application/vnd.openxmlformats-officedocument."
                        "wordprocessingml.document"
                    )
                ),
                "truncated_for_model": (
                    len(content)
                    >= DOCUMENT_MAX_MODEL_CHARS
                ),
            },
        )

    # -----------------------------------------------------
    # TEXT / SOURCE FILES
    # -----------------------------------------------------

    if extension in {
        ".txt",
        ".md",
        ".csv",
        ".json",
        ".py",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".html",
        ".css",
    }:

        content = data.decode(
            "utf-8",
            errors="replace",
        ).strip()

        if not content:

            raise ValueError(
                "The uploaded text file is empty."
            )

        content = content[
            :DOCUMENT_MAX_MODEL_CHARS
        ]

        prompt = (
            (request.form.get("message", "") if prompt is None else prompt)
            or ""
        ).strip()

        if prompt:

            message = (
                f"{prompt}\n\n"
                f"File: {safe_name}\n"
                f"File content:\n"
                f"{content}"
            )

        else:

            message = (
                f"Analyze the following file: "
                f"{safe_name}\n\n"
                f"{content}"
            )

        return (
            message,
            {
                "type": "text_document",
                "filename": safe_name,
                "mime_type": (
                    file_storage.mimetype
                    or "text/plain"
                ),
                "truncated_for_model": (
                    len(content)
                    >= DOCUMENT_MAX_MODEL_CHARS
                ),
            },
        )

    raise ValueError(
        (
            "Unsupported file type. "
            "Supported documents are PDF, DOCX, TXT, MD, "
            "CSV, JSON and common source-code text files."
        )
    )

