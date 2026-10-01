"""
RevelaAI Community Ecosystem Provider

Connects the RevelaAI intelligence layer to the existing
RevelaCode Community Hub through the internal AI Gateway.

Community remains the source of truth for:
    - community posts
    - discussions
    - hub activity
    - cross-hub communication

RevelaAI only retrieves the context needed to answer the
user's question.
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

class CommunityProvider:
    """
    RevelaAI provider for the Community Hub.
    """

    domain = "community"

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
        Retrieve Community context for the authenticated user.
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
        Best-effort Community context retrieval.

        A temporary gateway/network failure returns structured
        fallback metadata instead of terminating the AI request.
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
    # COMMUNITY FEED
    # =====================================================

    def get_feed(
        self,
        *,
        user_id: str,
        message: str = "",
    ) -> dict:
        """
        Retrieve recent Community feed context.

        Useful for questions such as:

            "What are people discussing?"
            "What is happening in the community?"
            "Show me recent community activity."
        """

        result = self.get_context(
            user_id=user_id,
            message=(
                message
                or "community feed"
            ),
            include={
                "feed": True,
            },
        )

        if not isinstance(
            result,
            dict,
        ):

            return {}

        return result

    # =====================================================
    # CROSS-HUB COMMUNITY CONTEXT
    # =====================================================

    def get_hub_context(
        self,
        *,
        user_id: str,
        hub: str,
        message: str = "",
    ) -> dict:
        """
        Retrieve Community context related to a specific hub.

        Supported Community hubs include:

            community
            biashara
            shamba
            elimu

        The filtering itself remains controlled by the
        RevelaCode platform layer.
        """

        normalized_hub = (
            str(hub or "")
            .strip()
            .lower()
        )

        result = self.get_context(
            user_id=user_id,
            message=(
                message
                or f"{normalized_hub} community activity"
            ),
            include={
                "feed": True,
            },
        )

        if not isinstance(
            result,
            dict,
        ):

            return {}

        return result

    # =====================================================
    # COMMUNITY ANALYSIS
    # =====================================================

    def get_analysis_context(
        self,
        *,
        user_id: str,
        message: str = "",
    ) -> dict:
        """
        Retrieve broader Community context for AI analysis.
        """

        return self.get_context(
            user_id=user_id,
            message=(
                message
                or "community analysis"
            ),
            include={
                "feed": True,
                "posts": True,
                "discussions": True,
                "groups": True,
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