"""
RevelaAI Elimu Ecosystem Provider

Connects the RevelaAI intelligence layer to the existing
RevelaCode Elimu Hub through the internal AI Gateway.

Elimu remains the source of truth for:
    - education profiles
    - schools
    - classes
    - lessons
    - assignments
    - fees
    - CBC projects

RevelaAI consumes this information for contextual assistance,
analysis, explanation, and educational guidance.
"""

from __future__ import annotations

from typing import Any

from .client import (
    get_domain_context,
    try_get_context,
)


# =========================================================
# PROVIDER
# =========================================================

class ElimuProvider:
    """
    RevelaAI provider for the Elimu Hub.
    """

    domain = "elimu"

    # =====================================================
    # CONTEXT
    # =====================================================

    def get_context(
        self,
        *,
        user_id: str,
        message: str = "",
        include: dict[str, Any] | None = None,
    ) -> dict:
        """
        Retrieve Elimu context for the authenticated user.
        """

        normalized_include = (
            include
            if isinstance(
                include,
                dict,
            )
            else {}
        )

        return get_domain_context(
            user_id=str(
                user_id
            ),
            domain=self.domain,
            message=str(
                message or ""
            ),
            include=normalized_include,
        )

    # =====================================================
    # SAFE CONTEXT
    # =====================================================

    def try_get_context(
        self,
        *,
        user_id: str,
        message: str = "",
        include: dict[str, Any] | None = None,
    ) -> dict:
        """
        Best-effort Elimu context retrieval.

        Gateway failures do not have to terminate an AI
        conversation.
        """

        return try_get_context(
            user_id=str(
                user_id
            ),
            domain=self.domain,
            message=str(
                message or ""
            ),
            include=(
                include
                if isinstance(
                    include,
                    dict,
                )
                else {}
            ),
        )

    # =====================================================
    # EDUCATION PROFILE
    # =====================================================

    def get_profile(
        self,
        *,
        user_id: str,
    ) -> dict:
        """
        Retrieve the user's education profile.
        """

        result = self.get_context(
            user_id=user_id,
            message="education profile",
            include={
                "profile": True,
            },
        )

        if not isinstance(
            result,
            dict,
        ):

            return {}

        return result

    # =====================================================
    # SCHOOL
    # =====================================================

    def get_school(
        self,
        *,
        user_id: str,
    ) -> dict:
        """
        Retrieve the user's school context.
        """

        result = self.get_context(
            user_id=user_id,
            message="my school",
            include={
                "school": True,
            },
        )

        if not isinstance(
            result,
            dict,
        ):

            return {}

        return result

    # =====================================================
    # LEARNING CONTEXT
    # =====================================================

    def get_learning_context(
        self,
        *,
        user_id: str,
        message: str = "",
    ) -> dict:
        """
        Retrieve lessons, assignments, and education profile
        context for learning-related questions.
        """

        result = self.get_context(
            user_id=user_id,
            message=(
                message
                or "my learning information"
            ),
            include={
                "profile": True,
                "school": True,
                "lessons": True,
                "assignments": True,
            },
        )

        if not isinstance(
            result,
            dict,
        ):

            return {}

        return result

    # =====================================================
    # STUDENT CONTEXT
    # =====================================================

    def get_student_context(
        self,
        *,
        user_id: str,
        message: str = "",
    ) -> dict:
        """
        Retrieve student-oriented context.

        Includes:
            - education profile
            - assignments
            - fees
            - CBC projects
        """

        result = self.get_context(
            user_id=user_id,
            message=(
                message
                or "my student information"
            ),
            include={
                "profile": True,
                "assignments": True,
                "fees": True,
                "projects": True,
            },
        )

        if not isinstance(
            result,
            dict,
        ):

            return {}

        return result

    # =====================================================
    # TEACHER / SCHOOL CONTEXT
    # =====================================================

    def get_teacher_context(
        self,
        *,
        user_id: str,
        message: str = "",
    ) -> dict:
        """
        Retrieve school-side educational context.

        Useful for teacher/school questions involving:

            - school
            - classes
            - lessons
            - assignments
            - education profile
        """

        result = self.get_context(
            user_id=user_id,
            message=(
                message
                or "school teaching information"
            ),
            include={
                "profile": True,
                "school": True,
                "lessons": True,
                "assignments": True,
            },
        )

        if not isinstance(
            result,
            dict,
        ):

            return {}

        return result

    # =====================================================
    # FULL EDUCATION ANALYSIS
    # =====================================================

    def get_analysis_context(
        self,
        *,
        user_id: str,
        message: str = "",
    ) -> dict:
        """
        Retrieve broader Elimu context for educational
        analysis and assistance.
        """

        return self.get_context(
            user_id=user_id,
            message=(
                message
                or "education analysis"
            ),
            include={
                "profile": True,
                "school": True,
                "lessons": True,
                "assignments": True,
                "fees": True,
                "projects": True,
            },
        )

    # =====================================================
    # AVAILABILITY
    # =====================================================

    def is_available(
        self,
    ) -> bool:
        """
        Return whether the RevelaCode ecosystem credential
        required by this provider is configured.
        """

        try:

            from .client import service_configured

            return service_configured()

        except Exception:

            return False