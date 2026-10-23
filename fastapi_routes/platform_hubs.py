"""Authenticated pass-throughs to RevelaCode's authoritative hub/profile APIs.

This router deliberately persists no Elimu progress, hub membership, profiles, or
certificates. The existing RevelaCode Backend remains the system of record.
"""
from __future__ import annotations

import logging
import re
from typing import Any

import requests
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from fastapi_routes.auth import REVELACODE_BACKEND_URL, authenticate_identity

router = APIRouter(tags=["RevelaCode Platform Bridge"])
logger = logging.getLogger("revelaai.fastapi.platform_hubs")

_ELIMU_CERTIFICATE_ID = re.compile(r"RC-EL-[A-F0-9]{16}\Z")
_ACCOUNT_CERTIFICATE_ID = re.compile(r"RC-AC-[A-F0-9]{16}\Z")
_ALLOWED_CERTIFICATE_ID = re.compile(r"RC-(?:EL|AC)-[A-F0-9]{16}\Z")
_TIMEOUT = (3.0, 12.0)


def _authenticate(request: Request, payload: dict[str, Any] | None = None):
    _identity, user_id, error = authenticate_identity(
        request.headers.get("Authorization", ""),
        dict(request.headers),
        payload or {},
    )
    return user_id, error


def _proxy_sync(
    request: Request,
    method: str,
    upstream_path: str,
    *,
    payload: dict[str, Any] | None = None,
    params: dict[str, str] | None = None,
    public: bool = False,
) -> Response:
    """Forward only to fixed backend paths and return the upstream response without cookies."""
    if not public:
        _user_id, error = _authenticate(request, payload)
        if error is not None:
            return error

    if not REVELACODE_BACKEND_URL.startswith("https://"):
        logger.error("Platform bridge rejected a non-HTTPS RevelaCode backend origin")
        return JSONResponse(
            {"status": "error", "code": "platform_backend_not_configured"},
            status_code=503,
        )

    headers = {
        "Accept": request.headers.get("Accept", "application/json"),
    }
    authorization = request.headers.get("Authorization", "").strip()
    if authorization:
        headers["Authorization"] = authorization
    if payload is not None:
        headers["Content-Type"] = "application/json"

    try:
        upstream = requests.request(
            method.upper(),
            REVELACODE_BACKEND_URL + upstream_path,
            headers=headers,
            params=params,
            json=payload,
            timeout=_TIMEOUT,
            allow_redirects=False,
            proxies={"http": "", "https": ""},
        )
    except requests.RequestException:
        logger.warning("RevelaCode platform bridge request failed | path=%s", upstream_path)
        return JSONResponse(
            {
                "status": "error",
                "code": "platform_backend_unavailable",
                "message": "The RevelaCode platform service is temporarily unavailable.",
            },
            status_code=503,
        )

    if 300 <= upstream.status_code < 400:
        logger.warning("RevelaCode platform bridge rejected redirect | path=%s", upstream_path)
        return JSONResponse(
            {"status": "error", "code": "platform_backend_redirect_rejected"},
            status_code=502,
        )

    forwarded_headers: dict[str, str] = {}
    for name in ("content-type", "content-disposition", "cache-control", "etag", "last-modified"):
        value = upstream.headers.get(name)
        if value:
            forwarded_headers[name] = value
    forwarded_headers.setdefault("cache-control", "no-store")
    forwarded_headers["X-Content-Type-Options"] = "nosniff"
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=forwarded_headers,
    )


async def _payload(request: Request) -> dict[str, Any] | JSONResponse:
    if request.headers.get("content-length"):
        try:
            if int(request.headers["content-length"]) > 65536:
                return JSONResponse(
                    {"status": "error", "code": "request_too_large"},
                    status_code=413,
                )
        except ValueError:
            return JSONResponse(
                {"status": "error", "code": "invalid_content_length"},
                status_code=400,
            )
    try:
        value = await request.json()
    except Exception:
        return JSONResponse(
            {"status": "error", "code": "invalid_json"},
            status_code=400,
        )
    if not isinstance(value, dict):
        return JSONResponse(
            {"status": "error", "code": "json_object_required"},
            status_code=422,
        )
    return value


@router.get("/api/elimu/hubs")
async def list_elimu_hubs(request: Request):
    return await run_in_threadpool(
        _proxy_sync, request, "GET", "/api/study/elimu/hubs"
    )


@router.get("/api/elimu/hubs/{hub_id}")
async def get_elimu_hub(hub_id: str, request: Request):
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,120}", hub_id):
        return JSONResponse({"status": "error", "code": "invalid_hub_id"}, status_code=422)
    return await run_in_threadpool(
        _proxy_sync, request, "GET", f"/api/study/elimu/hubs/{hub_id}"
    )


@router.get("/api/elimu/progress")
async def get_elimu_progress(
    request: Request,
    hub_id: str | None = Query(default=None, max_length=120),
):
    params = {"hub_id": hub_id} if hub_id else None
    return await run_in_threadpool(
        _proxy_sync, request, "GET", "/api/study/elimu/progress", params=params
    )


@router.post("/api/elimu/progress")
async def save_elimu_progress(request: Request):
    payload = await _payload(request)
    if isinstance(payload, JSONResponse):
        return payload
    return await run_in_threadpool(
        _proxy_sync, request, "POST", "/api/study/elimu/progress", payload=payload
    )


@router.post("/api/certificates/generate")
async def generate_elimu_certificate(request: Request):
    payload = await _payload(request)
    if isinstance(payload, JSONResponse):
        return payload
    return await run_in_threadpool(
        _proxy_sync,
        request,
        "POST",
        "/api/study/elimu/certificates/generate",
        payload=payload,
    )


@router.get("/api/certificates/{certificate_id}")
async def download_elimu_certificate(certificate_id: str, request: Request):
    if not _ELIMU_CERTIFICATE_ID.fullmatch(certificate_id):
        return JSONResponse(
            {"status": "error", "code": "invalid_elimu_certificate_id"},
            status_code=422,
        )
    return await run_in_threadpool(
        _proxy_sync,
        request,
        "GET",
        f"/api/study/elimu/certificates/{certificate_id}",
    )


@router.get("/api/verify/certificate/{certificate_id}")
async def verify_platform_certificate(certificate_id: str, request: Request):
    """Publicly verify either an account certificate or an Elimu learning certificate."""
    if not _ALLOWED_CERTIFICATE_ID.fullmatch(certificate_id):
        return JSONResponse(
            {"valid": False, "reason": "certificate_not_found"},
            status_code=404,
        )
    if _ELIMU_CERTIFICATE_ID.fullmatch(certificate_id):
        upstream_path = f"/api/study/elimu/certificates/verify/{certificate_id}"
    elif _ACCOUNT_CERTIFICATE_ID.fullmatch(certificate_id):
        upstream_path = f"/api/verify/certificate/{certificate_id}"
    else:
        return JSONResponse(
            {"valid": False, "reason": "certificate_not_found"},
            status_code=404,
        )
    return await run_in_threadpool(
        _proxy_sync, request, "GET", upstream_path, public=True
    )


@router.get("/api/accounts/profile/download")
async def download_account_profile(
    request: Request,
    output_format: str = Query(default="pdf", alias="format", pattern="^(pdf|json)$"),
):
    return await run_in_threadpool(
        _proxy_sync,
        request,
        "GET",
        "/api/accounts/profile/download",
        params={"format": output_format},
    )


@router.post("/api/accounts/certificates")
async def create_account_certificate(request: Request):
    payload = await _payload(request)
    if isinstance(payload, JSONResponse):
        return payload
    return await run_in_threadpool(
        _proxy_sync, request, "POST", "/api/accounts/certificates", payload=payload
    )


@router.get("/api/accounts/certificates/{certificate_id}/download")
async def download_account_certificate(certificate_id: str, request: Request):
    if not _ACCOUNT_CERTIFICATE_ID.fullmatch(certificate_id):
        return JSONResponse(
            {"status": "error", "code": "invalid_account_certificate_id"},
            status_code=422,
        )
    return await run_in_threadpool(
        _proxy_sync,
        request,
        "GET",
        f"/api/accounts/certificates/{certificate_id}/download",
    )
