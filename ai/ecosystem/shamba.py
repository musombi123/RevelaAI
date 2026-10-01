"""
RevelaAI Shamba Ecosystem Provider

Connects the RevelaAI intelligence layer to the existing
RevelaCode Shamba Hub.

Shamba remains responsible for:
    - farmer profiles
    - farms
    - crops
    - farm activities
    - harvests
    - agricultural records
    - farming-related platform data

RevelaAI retrieves this information only when it is relevant
to the user's question.
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

class ShambaProvider:
    """
    RevelaAI provider for the Shamba Hub.
    """

    domain = "shamba"

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
        Retrieve Shamba context for the authenticated user.
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
        Best-effort Shamba context retrieval.

        Platform/network failures return structured fallback
        metadata instead of crashing the AI pipeline.
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
    # FARMER PROFILE
    # =====================================================

    def get_farmer(
        self,
        *,
        user_id: str,
    ) -> dict:
        """
        Retrieve the user's farmer profile.
        """

        result = self.get_context(
            user_id=user_id,
            message="farmer profile",
            include={
                "farmer": True,
            },
        )

        if not isinstance(
            result,
            dict,
        ):

            return {}

        return result

    # =====================================================
    # FARM CONTEXT
    # =====================================================

    def get_farms(
        self,
        *,
        user_id: str,
        message: str = "",
    ) -> dict:
        """
        Retrieve the user's farms and relevant farm data.

        Useful for:

            farm size
            location
            soil
            irrigation
            farming type
        """

        result = self.get_context(
            user_id=user_id,
            message=(
                message
                or "my farms"
            ),
            include={
                "farmer": True,
                "farms": True,
            },
        )

        if not isinstance(
            result,
            dict,
        ):

            return {}

        return result

    # =====================================================
    # CROP CONTEXT
    # =====================================================

    def get_crops(
        self,
        *,
        user_id: str,
        message: str = "",
    ) -> dict:
        """
        Retrieve the user's farms and crop records.

        Useful for questions such as:

            "What crops am I growing?"
            "Which farm has maize?"
            "What should I plant next?"
        """

        result = self.get_context(
            user_id=user_id,
            message=(
                message
                or "my farm crops"
            ),
            include={
                "farmer": True,
                "farms": True,
                "crops": True,
            },
        )

        if not isinstance(
            result,
            dict,
        ):

            return {}

        return result

    # =====================================================
    # FARMING ANALYSIS
    # =====================================================

    def get_analysis_context(
        self,
        *,
        user_id: str,
        message: str = "",
    ) -> dict:
        """
        Retrieve the broader Shamba context required for
        agricultural analysis.

        The orchestrator should use this for questions that
        require several pieces of farm information.
        """

        return self.get_context(
            user_id=user_id,
            message=(
                message
                or "farm and crop analysis"
            ),
            include={
                "farmer": True,
                "farms": True,
                "crops": True,
                "activities": True,
                "harvests": True,
                "market": True,
                "weather": True,
            },
        )

    # =====================================================
    # AVAILABILITY
    # =====================================================

    def is_available(
        self,
    ) -> bool:
        """
        Return whether the RevelaCode ecosystem service
        credential is configured.

        This does not expose the credential.
        """

        try:

            from .client import service_configured

            return service_configured()

        except Exception:

            return False