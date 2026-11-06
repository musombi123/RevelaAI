"""Authenticated API for the local selective Humanizer."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from fastapi_routes.auth import resolve_revelacode_user
from services.humanizer_service import (
    MAX_SELECTION_CHARS,
    apply_accepted_replacements,
    suggest_selected_text,
)

router = APIRouter(prefix="/api/humanizer", tags=["Humanizer"])
LOG = logging.getLogger("revelaai.humanizer")
MAX_PDF_BYTES = 20 * 1024 * 1024


def _authenticated_user(request: Request) -> tuple[str | None, JSONResponse | None]:
    return resolve_revelacode_user(request.headers.get("Authorization", ""))


@router.post("/suggest")
async def humanizer_suggest(request: Request):
    user_id, error = _authenticated_user(request)
    if error:
        return error
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"error": {"code": "INVALID_JSON", "message": "A JSON request body is required."}}, status_code=400)
    if not isinstance(payload, dict):
        return JSONResponse({"error": {"code": "INVALID_BODY", "message": "A JSON object is required."}}, status_code=400)

    selected = str(payload.get("selected_text") or "")
    if len(selected) > MAX_SELECTION_CHARS:
        return JSONResponse({"error": {"code": "SELECTION_TOO_LARGE", "message": f"Select no more than {MAX_SELECTION_CHARS} characters at a time."}}, status_code=413)
    try:
        result = suggest_selected_text(
            selected,
            before=str(payload.get("context_before") or ""),
            after=str(payload.get("context_after") or ""),
            style=str(payload.get("style") or "natural"),
        )
    except ValueError as exc:
        return JSONResponse({"error": {"code": "INVALID_SELECTION", "message": str(exc)}}, status_code=400)
    result["user_id"] = user_id
    return {"success": True, "data": result}


@router.post("/pdf/extract")
async def humanizer_extract_pdf(request: Request, file: UploadFile = File(...)):
    user_id, error = _authenticated_user(request)
    if error:
        return error
    filename = (file.filename or "").replace("\\", "/").split("/")[-1]
    if not filename.lower().endswith(".pdf"):
        return JSONResponse({"error": {"code": "PDF_REQUIRED", "message": "Upload a PDF file."}}, status_code=415)
    data = await file.read(MAX_PDF_BYTES + 1)
    if not data:
        return JSONResponse({"error": {"code": "EMPTY_PDF", "message": "The PDF is empty."}}, status_code=400)
    if len(data) > MAX_PDF_BYTES:
        return JSONResponse({"error": {"code": "PDF_TOO_LARGE", "message": "PDF must be 20 MB or smaller."}}, status_code=413)
    try:
        from ai.pdf_processor import process_pdf
        result = await run_in_threadpool(process_pdf, data, enable_ocr=True)
    except Exception as exc:
        LOG.warning("Humanizer PDF extraction failed | error_type=%s", type(exc).__name__)
        return JSONResponse({"error": {"code": "PDF_EXTRACTION_FAILED", "message": "The PDF could not be read. It may be encrypted, damaged, or image-only."}}, status_code=422)
    pages = [
        {"page": int(page.get("page") or index + 1), "text": str(page.get("text") or ""), "characters": int(page.get("characters") or 0), "extraction_method": str(page.get("method") or "native")}
        for index, page in enumerate(result.get("pages", []))
    ]
    return {
        "success": True,
        "data": {
            "filename": filename[:255],
            "pages": pages,
            "page_count": len(pages),
            "characters": int(result.get("metadata", {}).get("characters") or 0),
            "ocr_enabled": True,\n            "ocr_pages": int(result.get("metadata", {}).get("ocr_pages") or 0),
            "user_id": user_id,
            "notice": "PDF text was extracted locally. OCR is attempted when configured. The original file was not modified or stored. Select a passage to receive local suggestions.",
        },
    }


@router.post("/apply")
async def humanizer_apply(request: Request):
    _user_id, error = _authenticated_user(request)
    if error:
        return error
    try:
        payload: Any = await request.json()
    except Exception:
        return JSONResponse({"error": {"code": "INVALID_JSON", "message": "A JSON request body is required."}}, status_code=400)
    if not isinstance(payload, dict):
        return JSONResponse({"error": {"code": "INVALID_BODY", "message": "A JSON object is required."}}, status_code=400)
    source = str(payload.get("source_text") or "")
    replacements = payload.get("accepted_replacements")
    if not isinstance(replacements, list) or len(replacements) > 40:
        return JSONResponse({"error": {"code": "INVALID_REPLACEMENTS", "message": "Provide up to 40 individually accepted replacements."}}, status_code=400)
    try:
        revised = apply_accepted_replacements(source, replacements)
    except ValueError as exc:
        return JSONResponse({"error": {"code": "REPLACEMENT_REJECTED", "message": str(exc)}}, status_code=409)
    return {"success": True, "data": {"text": revised, "accepted_count": len(replacements), "model_used": False}}
