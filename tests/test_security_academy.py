from bson import ObjectId

from services import security_academy as academy
from services.security_academy_catalog import COURSES, COURSE_GUARDRAILS


def test_catalog_has_six_complete_tracks_with_labs_and_assessments():
    assert len(COURSES) == 6
    assert len({course["id"] for course in COURSES}) == 6
    for course in COURSES:
        assert len(course["lessons"]) >= 3
        assert len(course["quiz"]) >= 4
        assert all(lesson.get("lab", {}).get("steps") for lesson in course["lessons"])
        assert all("answer" in question for question in course["quiz"])


def test_quiz_grade_is_calculated_on_the_server():
    course = COURSES[0]
    correct_answers = {
        question["id"]: question["answer"]
        for question in course["quiz"]
    }
    result = academy.grade_quiz(course["id"], correct_answers)

    assert result["score_percent"] == 100
    assert result["passed"] is True
    assert result["correct_answers"] == result["total_questions"]
    assert len(result["feedback"]) == len(course["quiz"])


def test_failed_quiz_does_not_meet_pass_mark():
    course = COURSES[0]
    incorrect_answers = {
        question["id"]: next(
            option["id"]
            for option in question["options"]
            if option["id"] != question["answer"]
        )
        for question in course["quiz"]
    }
    result = academy.grade_quiz(course["id"], incorrect_answers)

    assert result["score_percent"] == 0
    assert result["passed"] is False
    assert result["pass_percent"] == 75


def test_quiz_requires_exactly_one_answer_per_question():
    course = COURSES[0]
    with __import__("pytest").raises(ValueError, match="answer_every_question_exactly_once"):
        academy.grade_quiz(course["id"], {})


def test_course_detail_never_exposes_quiz_answer_keys(monkeypatch):
    class ReadOnlyProgress:
        @staticmethod
        def find_one(query):
            return {
                "userId": query["userId"],
                "courseId": query["courseId"],
                "completedLessons": [],
                "quizAttempts": [],
            }

    monkeypatch.setattr(academy, "security_course_progress", lambda: ReadOnlyProgress())
    detail = academy.get_course_detail(COURSES[0]["id"], ObjectId())

    assert detail is not None
    assert detail["course"]["quiz"]
    assert all("answer" not in question for question in detail["course"]["quiz"])
    assert detail["guardrails"]["binary_execution_by_api"] is False
    assert detail["guardrails"]["remote_scanning_by_api"] is False


def test_guardrails_require_human_review_and_block_unsafe_scope():
    assert COURSE_GUARDRAILS["lab_mode"] == "local_or_isolated_training_only"
    assert COURSE_GUARDRAILS["human_review_required_for_consequential_changes"] is True
    assert COURSE_GUARDRAILS["automatic_merge_or_deployment"] is False
