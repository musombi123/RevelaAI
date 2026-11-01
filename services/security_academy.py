"""Progress and assessment logic for the built-in defensive security academy."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from bson import ObjectId

from services.memory_store import security_course_progress
from services.security_academy_catalog import COURSES, COURSE_GUARDRAILS

PASS_PERCENT = 75


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _course(course_id: str) -> dict[str, Any] | None:
    return next((item for item in COURSES if item["id"] == course_id), None)


def _iso(value: Any) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else value


def course_summary(course: dict[str, Any], progress: dict[str, Any] | None = None) -> dict[str, Any]:
    record = progress or {}
    completed = set(record.get("completedLessons") or [])
    lesson_count = len(course.get("lessons") or [])
    return {
        "id": course["id"],
        "title": course["title"],
        "subtitle": course["subtitle"],
        "category": course["category"],
        "level": course["level"],
        "duration_minutes": course["duration_minutes"],
        "description": course["description"],
        "outcomes": list(course.get("outcomes") or []),
        "tags": list(course.get("tags") or []),
        "lesson_count": lesson_count,
        "completed_lessons": len(completed),
        "progress_percent": round((len(completed) / lesson_count) * 100) if lesson_count else 0,
        "status": str(record.get("status") or "not_started"),
        "best_quiz_percent": int(record.get("bestQuizPercent") or 0),
        "updated_at": _iso(record.get("updatedAt")),
    }


def list_courses(user_oid: ObjectId) -> list[dict[str, Any]]:
    records = {
        item.get("courseId"): item
        for item in security_course_progress().find({"userId": user_oid})
    }
    return [course_summary(item, records.get(item["id"])) for item in COURSES]


def get_progress(user_oid: ObjectId) -> list[dict[str, Any]]:
    records = {
        item.get("courseId"): item
        for item in security_course_progress().find({"userId": user_oid})
    }
    return [course_summary(item, records.get(item["id"])) for item in COURSES]


def get_course_detail(course_id: str, user_oid: ObjectId) -> dict[str, Any] | None:
    course = _course(course_id)
    if not course:
        return None
    record = security_course_progress().find_one({"userId": user_oid, "courseId": course_id}) or {}
    detail = deepcopy(course)
    # Never disclose answer keys before the learner submits a quiz.
    for question in detail.get("quiz", []):
        question.pop("answer", None)
    return {
        "course": detail,
        "progress": course_summary(course, record),
        "completed_lessons": list(record.get("completedLessons") or []),
        "quiz_attempts": [
            {
                "score_percent": int(item.get("scorePercent") or 0),
                "passed": bool(item.get("passed")),
                "submitted_at": _iso(item.get("submittedAt")),
            }
            for item in (record.get("quizAttempts") or [])[-10:]
        ],
        "guardrails": COURSE_GUARDRAILS,
    }


def complete_lesson(course_id: str, lesson_id: str, user_oid: ObjectId) -> dict[str, Any] | None:
    course = _course(course_id)
    if not course:
        return None
    lesson_ids = {item["id"] for item in course.get("lessons", [])}
    if lesson_id not in lesson_ids:
        raise ValueError("lesson_not_found")

    collection = security_course_progress()
    now = _now()
    collection.update_one(
        {"userId": user_oid, "courseId": course_id},
        {
            "$setOnInsert": {
                "userId": user_oid,
                "courseId": course_id,
                "courseTitle": course["title"],
                "quizAttempts": [],
                "bestQuizPercent": 0,
                "status": "in_progress",
                "createdAt": now,
            },
            "$addToSet": {"completedLessons": lesson_id},
            "$set": {"updatedAt": now, "courseTitle": course["title"]},
        },
        upsert=True,
    )
    record = collection.find_one({"userId": user_oid, "courseId": course_id}) or {}
    all_lessons_done = lesson_ids.issubset(set(record.get("completedLessons") or []))
    has_passed_quiz = any(bool(attempt.get("passed")) for attempt in record.get("quizAttempts") or [])
    status = "completed" if all_lessons_done and has_passed_quiz else "in_progress"
    collection.update_one(
        {"userId": user_oid, "courseId": course_id},
        {"$set": {"status": status, "updatedAt": now}},
    )
    record = collection.find_one({"userId": user_oid, "courseId": course_id}) or record
    return course_summary(course, record)


def grade_quiz(course_id: str, answers: Any) -> dict[str, Any] | None:
    course = _course(course_id)
    if not course:
        return None
    if not isinstance(answers, dict):
        raise ValueError("answers_must_be_an_object")

    questions = course.get("quiz") or []
    expected_ids = {item["id"] for item in questions}
    clean_answers = {
        str(key)[:80]: str(value)[:20]
        for key, value in answers.items()
        if isinstance(key, str) and isinstance(value, str)
    }
    if set(clean_answers) != expected_ids:
        raise ValueError("answer_every_question_exactly_once")

    feedback = []
    correct = 0
    for question in questions:
        selected = clean_answers[question["id"]]
        is_correct = selected == question["answer"]
        correct += int(is_correct)
        selected_label = next(
            (item["text"] for item in question["options"] if item["id"] == selected),
            "No valid option selected",
        )
        correct_label = next(
            item["text"] for item in question["options"] if item["id"] == question["answer"]
        )
        feedback.append({
            "question_id": question["id"],
            "question": question["question"],
            "selected_option": selected,
            "selected_text": selected_label,
            "correct": is_correct,
            "correct_option": question["answer"],
            "correct_text": correct_label,
            "explanation": question["explanation"],
        })

    total = len(questions)
    score = round((correct / total) * 100) if total else 0
    return {
        "course_id": course_id,
        "score_percent": score,
        "correct_answers": correct,
        "total_questions": total,
        "passed": score >= PASS_PERCENT,
        "pass_percent": PASS_PERCENT,
        "feedback": feedback,
    }


def submit_quiz(course_id: str, answers: Any, user_oid: ObjectId) -> dict[str, Any] | None:
    course = _course(course_id)
    if not course:
        return None
    result = grade_quiz(course_id, answers)
    now = _now()
    attempt = {
        "scorePercent": result["score_percent"],
        "correctAnswers": result["correct_answers"],
        "totalQuestions": result["total_questions"],
        "passed": result["passed"],
        "submittedAt": now,
    }
    collection = security_course_progress()
    collection.update_one(
        {"userId": user_oid, "courseId": course_id},
        {
            "$setOnInsert": {
                "userId": user_oid,
                "courseId": course_id,
                "courseTitle": course["title"],
                "completedLessons": [],
                "quizAttempts": [],
                "bestQuizPercent": 0,
                "createdAt": now,
            },
            "$push": {"quizAttempts": {"$each": [attempt], "$slice": -10}},
            "$max": {"bestQuizPercent": result["score_percent"]},
            "$set": {"updatedAt": now, "courseTitle": course["title"]},
        },
        upsert=True,
    )
    record = collection.find_one({"userId": user_oid, "courseId": course_id}) or {}
    lesson_ids = {item["id"] for item in course.get("lessons", [])}
    all_lessons_done = lesson_ids.issubset(set(record.get("completedLessons") or []))
    has_passed_quiz = any(bool(item.get("passed")) for item in record.get("quizAttempts") or [])
    status = "completed" if all_lessons_done and has_passed_quiz else "in_progress"
    collection.update_one(
        {"userId": user_oid, "courseId": course_id},
        {"$set": {"status": status, "updatedAt": now}},
    )
    result["progress"] = course_summary(course, record)
    return result
