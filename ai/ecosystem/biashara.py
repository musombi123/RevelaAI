"""
RevelaAI Biashara Ecosystem Provider

Connects the RevelaAI intelligence layer to the existing
RevelaCode Biashara platform through the internal AI Gateway.

Biashara remains the source of truth for:
    - business profiles
    - sales
    - orders
    - customers
    - products
    - inventory
    - expenses
    - dashboard metrics
    - business intelligence

RevelaAI only retrieves the context it needs.
"""

from __future__ import annotations

from typing import Any

from .client import (
    EcosystemClientError,
    get_domain_context,
    try_get_context,
)


# =========================================================
# PROVIDER
# =========================================================

class BiasharaProvider:
    """
    RevelaAI provider for the Biashara Hub.
    """

    domain = "biashara"

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
        Retrieve Biashara context for one authenticated user.

        Example:

            provider.get_context(
                user_id="123",
                message="Why are my sales dropping?",
            )
        """

        normalized_include = (
            include
            if isinstance(
                include,
                dict,
            )
            else {}
        )

        result = get_domain_context(
            user_id=str(
                user_id
            ),
            domain=self.domain,
            message=str(
                message or ""
            ),
            include=normalized_include,
        )

        return result

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
        Best-effort Biashara context lookup.

        Used by the orchestrator when ecosystem data should
        enrich an AI response but should not crash the entire
        request if the platform is temporarily unavailable.
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
    # BUSINESS PROFILE
    # =====================================================

    def get_business(
        self,
        *,
        user_id: str,
    ) -> dict:
        """
        Retrieve the authenticated user's business context.

        This uses the same gateway but asks specifically for
        business information.
        """

        result = self.get_context(
            user_id=user_id,
            message="business profile",
            include={
                "business": True,
            },
        )

        context = result.get(
            "data",
            result,
        )

        if not isinstance(
            context,
            dict,
        ):

            return {}

        return context

    # =====================================================
    # PERFORMANCE
    # =====================================================

    def get_performance(
        self,
        *,
        user_id: str,
        message: str = "",
    ) -> dict:
        """
        Retrieve business performance context.

        Suitable for questions involving:

            sales
            revenue
            profit
            orders
            customers
            performance trends
        """

        result = self.get_context(
            user_id=user_id,
            message=(
                message
                or "business performance"
            ),
            include={
                "business": True,
                "performance": True,
                "sales": True,
                "orders": True,
                "customers": True,
                "expenses": True,
            },
        )

        if not isinstance(
            result,
            dict,
        ):

            return {}

        return result

    # =====================================================
    # PRODUCTS / INVENTORY
    # =====================================================

    def get_products_and_inventory(
        self,
        *,
        user_id: str,
        message: str = "",
    ) -> dict:
        """
        Retrieve product and inventory context.

        Useful for questions such as:

            "Which products are low in stock?"
            "What should I restock?"
            "Which products are selling?"
        """

        result = self.get_context(
            user_id=user_id,
            message=(
                message
                or "products and inventory"
            ),
            include={
                "business": True,
                "products": True,
                "inventory": True,
            },
        )

        if not isinstance(
            result,
            dict,
        ):

            return {}

        return result

    # =====================================================
    # FULL BUSINESS ANALYSIS
    # =====================================================

    def get_analysis_context(
        self,
        *,
        user_id: str,
        message: str = "",
    ) -> dict:
        """
        Retrieve a broader Biashara context for analytical
        questions.

        This is intentionally explicit so the orchestrator
        can choose a heavier context request only when the
        question actually requires it.
        """

        return self.get_context(
            user_id=user_id,
            message=(
                message
                or "business analysis"
            ),
            include={
                "business": True,
                "performance": True,
                "products": True,
                "orders": True,
                "customers": True,
                "inventory": True,
                "sales": True,
                "expenses": True,
                "market": True,
                "economic": True,
            },
        )

    # =====================================================
    # AVAILABILITY
    # =====================================================

    def is_available(
        self,
    ) -> bool:
        """
        Return whether the RevelaCode gateway appears to be
        configured and reachable.

        This is a lightweight diagnostic helper.
        """

        try:

            from .client import service_configured

            return service_configured()

        except Exception:

            return False