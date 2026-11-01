"""Authenticated API for RevelaAI's defensive reverse-engineering academy."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from fastapi_routes.auth import authenticate_identity
from services.security_academy import (
    complete_lesson,
    get_course_detail,
    get_progress,
    list_courses,
    submit_quiz,
)

router = APIRouter(prefix="/api/security-academy", tags=["Security Academy"])
logger = logging.getLogger("revelaai.security_academy")


def _authenticate(request: Request, payload: dict[str, Any] | None = None):
    identity, user_id, error = authenticate_identity(
        request.headers.get("authorization", ""),
        request.headers,
        payload or {},
    )
    if error:
        return None, None, error
    return identity, user_id, None


async def _payload(request: Request) -> dict[str, Any] | None:
    try:
        body = await request.json()
    except Exception:
        return None
    return body if isinstance(body, dict) else None


def _storage_error() -> JSONResponse:
    logger.warning("Security Academy progress store is unavailable")
    return JSONResponse(
        {
            "status": "error",
            "error": {
                "code": "academy_storage_unavailable",
                "message": "Course progress is temporarily unavailable. No completion was recorded.",
            },
        },
        status_code=503,
    )


@router.get("/courses")
async def academy_courses(request: Request):
    identity, _, error = await run_in_threadpool(_authenticate, request)
    if error:
        return error
    try:
        courses = await run_in_threadpool(list_courses, identity)
        return {
            "status": "success",
            "data": {"courses": courses, "count": len(courses)},
        }
    except Exception:
        logger.exception("Security Academy course listing failed")
        return _storage_error()


@router.get("/progress")
async def academy_progress(request: Request):
    identity, _, error = await run_in_threadpool(_authenticate, request)
    if error:
        return error
    try:
        progress = await run_in_threadpool(get_progress, identity)
        return {"status": "success", "data": {"courses": progress}}
    except Exception:
        logger.exception("Security Academy progress retrieval failed")
        return _storage_error()


@router.get("/courses/{course_id}")
async def academy_course_detail(course_id: str, request: Request):
    identity, _, error = await run_in_threadpool(_authenticate, request)
    if error:
        return error
    try:
        detail = await run_in_threadpool(get_course_detail, course_id, identity)
        if detail is None:
            return JSONResponse(
                {"status": "error", "error": {"code": "course_not_found", "message": "Course not found."}},
                status_code=404,
            )
        return {"status": "success", "data": detail}
    except Exception:
        logger.exception("Security Academy course detail failed")
        return _storage_error()


@router.post("/courses/{course_id}/lessons/{lesson_id}/complete")
async def academy_complete_lesson(course_id: str, lesson_id: str, request: Request):
    identity, _, error = await run_in_threadpool(_authenticate, request)
    if error:
        return error
    try:
        progress = await run_in_threadpool(complete_lesson, course_id, lesson_id, identity)
        if progress is None:
            return JSONResponse(
                {"status": "error", "error": {"code": "course_not_found", "message": "Course not found."}},
                status_code=404,
            )
        return {"status": "success", "data": {"progress": progress}}
    except ValueError:
        return JSONResponse(
            {"status": "error", "error": {"code": "lesson_not_found", "message": "Lesson not found in this course."}},
            status_code=404,
        )
    except Exception:
        logger.exception("Security Academy lesson completion failed")
        return _storage_error()


@router.post("/courses/{course_id}/quiz")
async def academy_submit_quiz(course_id: str, request: Request):
    body = await _payload(request)
    if body is None:
        return JSONResponse(
            {"status": "error", "error": {"code": "invalid_json", "message": "Submit an answers object."}},
            status_code=400,
        )
    identity, _, error = await run_in_threadpool(_authenticate, request, body)
    if error:
        return error
    try:
        result = await run_in_threadpool(
            submit_quiz, course_id, body.get("answers"), identity
        )
        if result is None:
            return JSONResponse(
                {"status": "error", "error": {"code": "course_not_found", "message": "Course not found."}},
                status_code=404,
            )
        return {"status": "success", "data": result}
    except ValueError as exc:
        return JSONResponse(
            {"status": "error", "error": {"code": "invalid_quiz_submission", "message": str(exc)}},
            status_code=400,
        )
    except Exception:
        logger.exception("Security Academy quiz submission failed")
        return _storage_error()
