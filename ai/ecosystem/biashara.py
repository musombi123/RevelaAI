"""
RevelaAI Biashara Ecosystem Provider

Adapter between RevelaAI and the RevelaCode Backend
Biashara services.

The provider does not access MongoDB directly.

All platform communication goes through EcosystemClient
and the internal RevelaCode AI Gateway.
"""

from __future__ import annotations

from typing import Any

from .client import EcosystemClient


class BiasharaProvider:
    """
    RevelaAI adapter for the Biashara domain.
    """

    domain = "biashara"

    def __init__(
        self,
        client: EcosystemClient | None = None,
    ) -> None:
        self.client = (
            client
            if client is not None
            else EcosystemClient()
        )

    # =====================================================
    # GENERAL CONTEXT
    # =====================================================

    def get_context(
        self,
        *,
        user_id: str,
        message: str = "",
        include: dict[str, bool] | None = None,
    ) -> dict:
        """
        Retrieve ordinary Biashara platform context.
        """

        return self.client.get_domain_context(
            user_id=user_id,
            domain=self.domain,
            message=message,
            include=include or {},
        )

    # =====================================================
    # SAFE CONTEXT
    # =====================================================

    def try_get_context(
        self,
        *,
        user_id: str,
        message: str = "",
        include: dict[str, bool] | None = None,
    ) -> dict:
        """
        Non-throwing version of get_context().
        """

        return self.client.try_get_context(
            user_id=user_id,
            domain=self.domain,
            message=message,
            include=include or {},
        )

    # =====================================================
    # SPECIALIZED INTELLIGENCE
    # =====================================================

    def run_operation(
        self,
        *,
        operation: str,
        user_id: str,
        payload: dict[str, Any] | None = None,
        message: str = "",
    ) -> dict:
        """
        Execute a specialized Biashara intelligence
        operation through the RevelaCode AI Gateway.

        Examples:

            market_analysis
            market_forecast
            product_forecast
            market_trends
            economic_indicators
        """

        return self.client.run_operation(
            domain=self.domain,
            operation=operation,
            user_id=user_id,
            payload=payload or {},
            message=message,
        )

    # =====================================================
    # MARKET ANALYSIS
    # =====================================================

    def analyze_market(
        self,
        *,
        user_id: str,
        payload: dict[str, Any] | None = None,
        message: str = "",
    ) -> dict:
        """
        Run the backend's complete Biashara market analysis.
        """

        return self.run_operation(
            operation="market_analysis",
            user_id=user_id,
            payload=payload or {},
            message=message,
        )

    # =====================================================
    # NEXT-WEEK MARKET FORECAST
    # =====================================================

    def forecast_next_week(
        self,
        *,
        user_id: str,
        payload: dict[str, Any] | None = None,
        message: str = "",
    ) -> dict:
        """
        Run the backend's seven-day market forecast.
        """

        return self.run_operation(
            operation="market_forecast",
            user_id=user_id,
            payload=payload or {},
            message=message,
        )

    # =====================================================
    # PRODUCT FORECAST
    # =====================================================

    def forecast_product(
        self,
        *,
        user_id: str,
        product: dict[str, Any],
        forecast_days: int = 7,
        message: str = "",
    ) -> dict:
        """
        Forecast demand/sales for one product.
        """

        payload = {
            **product,
            "forecast_days": forecast_days,
        }

        return self.run_operation(
            operation="product_forecast",
            user_id=user_id,
            payload=payload,
            message=message,
        )

    # =====================================================
    # MARKET TRENDS
    # =====================================================

    def get_market_trends(
        self,
        *,
        user_id: str,
        area_id: str = "",
        category: str = "",
        indicator: str = "",
        days: int = 30,
        message: str = "",
    ) -> dict:
        """
        Retrieve historical/current market trend data.
        """

        payload = {
            "area_id": area_id,
            "category": category,
            "indicator": indicator,
            "days": days,
        }

        return self.run_operation(
            operation="market_trends",
            user_id=user_id,
            payload=payload,
            message=message,
        )

    # =====================================================
    # ECONOMIC INDICATORS
    # =====================================================

    def get_economic_indicators(
        self,
        *,
        user_id: str,
        refresh: bool = False,
        message: str = "",
    ) -> dict:
        """
        Retrieve current economic indicators.
        """

        return self.run_operation(
            operation="economic_indicators",
            user_id=user_id,
            payload={
                "refresh": refresh,
            },
            message=message,
        )

    # =====================================================
    # AVAILABILITY
    # =====================================================

    def is_available(self) -> bool:
        """
        Check whether the Biashara gateway is reachable.
        """

        try:

            result = self.client.check_gateway()

            return bool(
                isinstance(
                    result,
                    dict,
                )
            )

        except Exception:

            return False


__all__ = [
    "BiasharaProvider",
]