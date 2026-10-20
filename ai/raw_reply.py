"""Framework-neutral downloadable document responses for FastAPI handlers.

Call build_document_export from a native route and return the resulting
Starlette response. This module does not read request globals or depend on Flask.
"""
from __future__ import annotations

from typing import Literal

from fastapi.responses import Response

from utils.document_export import create_docx, create_pdf

ExportKind = Literal["docx", "pdf"]


def build_document_export(raw_reply: str, export_type: str) -> Response | None:
    """Build an attachment response for a supported document format.

    Return None when the requested format is unsupported so the endpoint can
    continue with its normal non-download response.
    """
    kind = str(export_type or "").strip().lower()
    if kind == "docx":
        file_bytes = create_docx(str(raw_reply or ""))
        return Response(
            content=file_bytes,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": 'attachment; filename="revelaai_document.docx"'},
        )
    if kind == "pdf":
        file_bytes = create_pdf(str(raw_reply or ""))
        return Response(
            content=file_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": 'attachment; filename="revelaai_document.pdf"'},
        )
    return None
