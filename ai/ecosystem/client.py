"""
RevelaAI Ecosystem Client

Low-level HTTP client used by RevelaAI to communicate with the
internal RevelaCode AI Gateway.

Responsibilities:

    - authenticate service-to-service requests
    - retrieve user-scoped ecosystem context
    - execute specialized ecosystem intelligence
    - apply network timeouts
    - validate backend responses
    - provide safe structured errors
    - never expose service credentials in logs

Architecture:

    RevelaAI
        ↓
    EcosystemClient
        ↓
    RevelaCode AI Gateway
        ↓
    Jumuiya / platform services
"""

from __future__ import annotations

import os
from typing import Any

import requests
from dotenv import load_dotenv


# =========================================================
# ENVIRONMENT
# =========================================================

load_dotenv()


# =========================================================
# CLIENT ERROR
# =========================================================

class EcosystemClientError(Exception):
    """
    Raised when RevelaAI cannot communicate with the
    RevelaCode ecosystem gateway.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        error_code: str | None = None,
    ) -> None:

        super().__init__(
            message
        )

        self.status_code = status_code
        self.error_code = error_code


# =========================================================
# CLIENT
# =========================================================

class EcosystemClient:
    """
    Low-level HTTP client for the RevelaCode AI Gateway.

    One instance is normally used by each ecosystem provider.
    """

    # -----------------------------------------------------
    # ENDPOINTS
    # -----------------------------------------------------

    AI_HEALTH_ENDPOINT = (
        "/api/ai/health"
    )

    AI_CONTEXT_ENDPOINT = (
        "/api/ai/context"
    )

    AI_DOMAIN_ENDPOINT = (
        "/api/ai"
    )

    AI_BIASHARA_INTELLIGENCE_ENDPOINT = (
        "/api/ai/biashara/intelligence"
    )

    # -----------------------------------------------------
    # INIT
    # -----------------------------------------------------

    def __init__(
        self,
        *,
        backend_url: str | None = None,
        service_key: str | None = None,
        connect_timeout: float | None = None,
        read_timeout: float | None = None,
        max_response_bytes: int | None = None,
    ) -> None:

        self.backend_url = (
            backend_url
            if backend_url is not None
            else os.getenv(
                "REVELACODE_BACKEND_URL",
                "https://revelacode-backend.onrender.com",
            )
        ).strip().rstrip("/")

        self.service_key = (
            service_key
            if service_key is not None
            else os.getenv(
                "REVELAAI_SERVICE_KEY",
                "",
            )
        ).strip()

        self.connect_timeout = (
            float(
                connect_timeout
            )
            if connect_timeout is not None
            else float(
                os.getenv(
                    "REVELACODE_CONNECT_TIMEOUT",
                    "10",
                )
            )
        )

        self.read_timeout = (
            float(
                read_timeout
            )
            if read_timeout is not None
            else float(
                os.getenv(
                    "REVELACODE_READ_TIMEOUT",
                    "60",
                )
            )
        )

        self.max_response_bytes = (
            int(
                max_response_bytes
            )
            if max_response_bytes is not None
            else int(
                os.getenv(
                    "REVELACODE_MAX_RESPONSE_BYTES",
                    "2000000",
                )
            )
        )

    # =====================================================
    # CONFIGURATION
    # =====================================================

    def service_configured(self) -> bool:
        """
        Return True when the internal service credential exists.
        """

        return bool(
            self.service_key
        )

    # =====================================================
    # HEADERS
    # =====================================================

    def build_headers(
        self,
    ) -> dict[str, str]:
        """
        Build authenticated internal-service headers.

        The service credential is never logged.
        """

        if not self.service_key:

            raise EcosystemClientError(
                "REVELAAI_SERVICE_KEY is not configured.",
                error_code="service_key_missing",
            )

        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": (
                "RevelaAI-Ecosystem/1.0"
            ),
            "X-REVELAAI-SERVICE-KEY": (
                self.service_key
            ),
        }

    # =====================================================
    # URL
    # =====================================================

    def build_url(
        self,
        path: str,
    ) -> str:
        """
        Build an absolute RevelaCode backend URL.
        """

        normalized_path = str(
            path or ""
        ).strip()

        if not normalized_path.startswith(
            "/"
        ):
            normalized_path = (
                "/"
                + normalized_path
            )

        return (
            self.backend_url
            + normalized_path
        )

    # =====================================================
    # RESPONSE SIZE
    # =====================================================

    def _validate_response_size(
        self,
        response: requests.Response,
    ) -> None:
        """
        Reject responses larger than the configured limit.
        """

        content_length = response.headers.get(
            "Content-Length"
        )

        if not content_length:
            return

        try:

            size = int(
                content_length
            )

        except (
            TypeError,
            ValueError,
        ):
            return

        if size > self.max_response_bytes:

            raise EcosystemClientError(
                "RevelaCode returned an oversized response.",
                status_code=(
                    response.status_code
                ),
                error_code="response_too_large",
            )

    # =====================================================
    # JSON PARSER
    # =====================================================

    def _parse_json_response(
        self,
        response: requests.Response,
    ) -> dict[str, Any]:
        """
        Parse a JSON response safely.
        """

        self._validate_response_size(
            response
        )

        try:

            data = response.json()

        except ValueError as exc:

            raise EcosystemClientError(
                "RevelaCode returned invalid JSON.",
                status_code=(
                    response.status_code
                ),
                error_code="invalid_json_response",
            ) from exc

        if not isinstance(
            data,
            dict,
        ):

            raise EcosystemClientError(
                (
                    "RevelaCode returned an unexpected "
                    "response format."
                ),
                status_code=(
                    response.status_code
                ),
                error_code="invalid_response_format",
            )

        return data

    # =====================================================
    # RESPONSE STATUS
    # =====================================================

    @staticmethod
    def _response_succeeded(
        data: dict[str, Any],
    ) -> bool:
        """
        Support both common gateway success conventions.

        Supported:

            {"status": "success"}

        and:

            {"success": true}
        """

        if data.get(
            "success"
        ) is True:
            return True

        return (
            str(
                data.get(
                    "status",
                    "",
                )
            )
            .strip()
            .lower()
            == "success"
        )

    # =====================================================
    # ERROR EXTRACTION
    # =====================================================

    @staticmethod
    def _extract_error_message(
        data: dict[str, Any],
    ) -> str:

        error = data.get(
            "error"
        )

        if isinstance(
            error,
            dict,
        ):

            message = error.get(
                "message"
            )

            if message:
                return str(
                    message
                )

        for key in (
            "message",
            "detail",
        ):

            value = data.get(
                key
            )

            if value:
                return str(
                    value
                )

        return (
            "RevelaCode AI Gateway request failed."
        )

    @staticmethod
    def _extract_error_code(
        data: dict[str, Any],
    ) -> str:

        error = data.get(
            "error"
        )

        if isinstance(
            error,
            dict,
        ):

            code = error.get(
                "code"
            )

            if code:
                return str(
                    code
                )

        for key in (
            "code",
            "error_code",
        ):

            value = data.get(
                key
            )

            if value:
                return str(
                    value
                )

        return (
            "gateway_request_failed"
        )

    # =====================================================
    # RESPONSE VALIDATION
    # =====================================================

    def _validate_response(
        self,
        response: requests.Response,
    ) -> dict[str, Any]:
        """
        Validate HTTP and application-level responses.
        """

        data = self._parse_json_response(
            response
        )

        if not response.ok:

            raise EcosystemClientError(
                self._extract_error_message(
                    data
                ),
                status_code=(
                    response.status_code
                ),
                error_code=(
                    self._extract_error_code(
                        data
                    )
                ),
            )

        return data

    # =====================================================
    # POST
    # =====================================================

    def _post(
        self,
        path: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Perform an authenticated POST request.
        """

        url = self.build_url(
            path
        )

        headers = self.build_headers()

        try:

            response = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=(
                    self.connect_timeout,
                    self.read_timeout,
                ),
            )

        except requests.Timeout as exc:

            raise EcosystemClientError(
                "Timed out while contacting RevelaCode.",
                error_code="gateway_timeout",
            ) from exc

        except requests.ConnectionError as exc:

            raise EcosystemClientError(
                "Could not connect to RevelaCode.",
                error_code=(
                    "gateway_connection_error"
                ),
            ) from exc

        except requests.RequestException as exc:

            raise EcosystemClientError(
                "RevelaCode request failed.",
                error_code=(
                    "gateway_request_error"
                ),
            ) from exc

        return self._validate_response(
            response
        )

    # =====================================================
    # GET
    # =====================================================

    def _get(
        self,
        path: str,
    ) -> dict[str, Any]:
        """
        Perform a public GET request.
        """

        url = self.build_url(
            path
        )

        try:

            response = requests.get(
                url,
                headers={
                    "Accept": "application/json",
                    "User-Agent": (
                        "RevelaAI-Ecosystem/1.0"
                    ),
                },
                timeout=(
                    self.connect_timeout,
                    self.read_timeout,
                ),
            )

        except requests.Timeout as exc:

            raise EcosystemClientError(
                "Timed out while contacting RevelaCode.",
                error_code="gateway_timeout",
            ) from exc

        except requests.ConnectionError as exc:

            raise EcosystemClientError(
                "Could not connect to RevelaCode.",
                error_code=(
                    "gateway_connection_error"
                ),
            ) from exc

        except requests.RequestException as exc:

            raise EcosystemClientError(
                "RevelaCode request failed.",
                error_code=(
                    "gateway_request_error"
                ),
            ) from exc

        return self._validate_response(
            response
        )

    # =====================================================
    # GENERAL CONTEXT
    # =====================================================

    def get_context(
        self,
        *,
        user_id: str,
        domain: str = "general",
        message: str = "",
        include: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Retrieve user-scoped ecosystem context.
        """

        normalized_user_id = str(
            user_id or ""
        ).strip()

        if not normalized_user_id:

            raise EcosystemClientError(
                "user_id is required.",
                error_code="missing_user_id",
            )

        normalized_domain = (
            str(
                domain or "general"
            )
            .strip()
            .lower()
        )

        payload = {
            "user_id": normalized_user_id,
            "domain": normalized_domain,
            "message": str(
                message or ""
            ),
            "include": (
                include
                if isinstance(
                    include,
                    dict,
                )
                else {}
            ),
        }

        response = self._post(
            self.AI_CONTEXT_ENDPOINT,
            payload,
        )

        if not self._response_succeeded(
            response
        ):

            raise EcosystemClientError(
                self._extract_error_message(
                    response
                ),
                error_code=(
                    self._extract_error_code(
                        response
                    )
                ),
            )

        data = response.get(
            "data"
        )

        if not isinstance(
            data,
            dict,
        ):

            raise EcosystemClientError(
                (
                    "RevelaCode returned no usable "
                    "ecosystem context."
                ),
                error_code=(
                    "empty_context_response"
                ),
            )

        return data

    # =====================================================
    # DOMAIN CONTEXT
    # =====================================================

    def get_domain_context(
        self,
        *,
        user_id: str,
        domain: str,
        message: str = "",
        include: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Retrieve context through a domain-specific
        gateway route.
        """

        normalized_user_id = str(
            user_id or ""
        ).strip()

        if not normalized_user_id:

            raise EcosystemClientError(
                "user_id is required.",
                error_code="missing_user_id",
            )

        normalized_domain = (
            str(
                domain or ""
            )
            .strip()
            .lower()
        )

        if not normalized_domain:

            raise EcosystemClientError(
                "domain is required.",
                error_code="missing_domain",
            )

        payload = {
            "user_id": normalized_user_id,
            "message": str(
                message or ""
            ),
            "include": (
                include
                if isinstance(
                    include,
                    dict,
                )
                else {}
            ),
        }

        response = self._post(
            (
                f"{self.AI_DOMAIN_ENDPOINT}/"
                f"{normalized_domain}"
            ),
            payload,
        )

        if not self._response_succeeded(
            response
        ):

            raise EcosystemClientError(
                self._extract_error_message(
                    response
                ),
                error_code=(
                    self._extract_error_code(
                        response
                    )
                ),
            )

        data = response.get(
            "data"
        )

        if not isinstance(
            data,
            dict,
        ):

            raise EcosystemClientError(
                (
                    "RevelaCode returned no usable "
                    "domain context."
                ),
                error_code=(
                    "empty_domain_context"
                ),
            )

        return data

    # =====================================================
    # SPECIALIZED INTELLIGENCE
    # =====================================================

    def run_operation(
        self,
        *,
        domain: str,
        operation: str,
        user_id: str,
        payload: dict[str, Any] | None = None,
        message: str = "",
    ) -> dict[str, Any]:
        """
        Execute a specialized ecosystem intelligence
        operation.

        Currently supported by the internal gateway:

            Biashara:
                market_analysis
                market_forecast
                product_forecast
                market_trends
                economic_indicators
        """

        normalized_domain = (
            str(
                domain or ""
            )
            .strip()
            .lower()
        )

        normalized_operation = (
            str(
                operation or ""
            )
            .strip()
            .lower()
        )

        normalized_user_id = str(
            user_id or ""
        ).strip()

        if not normalized_domain:

            raise EcosystemClientError(
                "domain is required.",
                error_code="missing_domain",
            )

        if not normalized_operation:

            raise EcosystemClientError(
                "operation is required.",
                error_code="missing_operation",
            )

        if not normalized_user_id:

            raise EcosystemClientError(
                "user_id is required.",
                error_code="missing_user_id",
            )

        if normalized_domain != "biashara":

            raise EcosystemClientError(
                (
                    "Specialized intelligence is not "
                    f"configured for domain '{normalized_domain}'."
                ),
                error_code=(
                    "unsupported_intelligence_domain"
                ),
            )

        request_payload = {
            "domain": normalized_domain,
            "operation": normalized_operation,
            "user_id": normalized_user_id,
            "message": str(
                message or ""
            ),
            "payload": (
                payload
                if isinstance(
                    payload,
                    dict,
                )
                else {}
            ),
        }

        response = self._post(
            self.AI_BIASHARA_INTELLIGENCE_ENDPOINT,
            request_payload,
        )

        if not self._response_succeeded(
            response
        ):

            raise EcosystemClientError(
                self._extract_error_message(
                    response
                ),
                error_code=(
                    self._extract_error_code(
                        response
                    )
                ),
            )

        data = response.get(
            "data"
        )

        if not isinstance(
            data,
            dict,
        ):

            raise EcosystemClientError(
                (
                    "RevelaCode returned no usable "
                    "intelligence result."
                ),
                error_code=(
                    "empty_intelligence_response"
                ),
            )

        return data

    # =====================================================
    # SAFE CONTEXT
    # =====================================================

    def try_get_context(
        self,
        *,
        user_id: str,
        domain: str = "general",
        message: str = "",
        include: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Best-effort ecosystem lookup.

        Failures become structured unavailable metadata.
        """

        try:

            return self.get_context(
                user_id=user_id,
                domain=domain,
                message=message,
                include=include,
            )

        except EcosystemClientError as exc:

            return {
                "source": (
                    "revelacode_platform"
                ),
                "source_layer": (
                    "platform"
                ),
                "available": False,
                "domain": (
                    str(
                        domain or "general"
                    )
                    .strip()
                    .lower()
                ),
                "error": {
                    "code": (
                        exc.error_code
                        or "ecosystem_unavailable"
                    ),
                    "message": str(
                        exc
                    ),
                },
                "context": {},
            }

        except Exception:

            return {
                "source": (
                    "revelacode_platform"
                ),
                "source_layer": (
                    "platform"
                ),
                "available": False,
                "domain": (
                    str(
                        domain or "general"
                    )
                    .strip()
                    .lower()
                ),
                "error": {
                    "code": (
                        "unexpected_ecosystem_error"
                    ),
                    "message": (
                        "Ecosystem context is "
                        "temporarily unavailable."
                    ),
                },
                "context": {},
            }

    # =====================================================
    # SAFE INTELLIGENCE
    # =====================================================

    def try_run_operation(
        self,
        *,
        domain: str,
        operation: str,
        user_id: str,
        payload: dict[str, Any] | None = None,
        message: str = "",
    ) -> dict[str, Any]:
        """
        Best-effort specialized intelligence lookup.
        """

        try:

            return self.run_operation(
                domain=domain,
                operation=operation,
                user_id=user_id,
                payload=payload,
                message=message,
            )

        except EcosystemClientError as exc:

            return {
                "available": False,
                "domain": (
                    str(
                        domain or ""
                    )
                    .strip()
                    .lower()
                ),
                "operation": (
                    str(
                        operation or ""
                    )
                    .strip()
                    .lower()
                ),
                "error": {
                    "code": (
                        exc.error_code
                        or "intelligence_unavailable"
                    ),
                    "message": str(
                        exc
                    ),
                },
                "result": {},
            }

        except Exception:

            return {
                "available": False,
                "domain": (
                    str(
                        domain or ""
                    )
                    .strip()
                    .lower()
                ),
                "operation": (
                    str(
                        operation or ""
                    )
                    .strip()
                    .lower()
                ),
                "error": {
                    "code": (
                        "unexpected_intelligence_error"
                    ),
                    "message": (
                        "Specialized intelligence is "
                        "temporarily unavailable."
                    ),
                },
                "result": {},
            }

    # =====================================================
    # GATEWAY HEALTH
    # =====================================================

    def check_gateway(
        self,
    ) -> dict[str, Any]:
        """
        Check whether the RevelaCode AI Gateway is reachable.
        """

        try:

            response = self._get(
                self.AI_HEALTH_ENDPOINT
            )

            return {
                "available": True,
                "status_code": 200,
                "data": response,
            }

        except EcosystemClientError as exc:

            return {
                "available": False,
                "status_code": (
                    exc.status_code
                ),
                "error": {
                    "code": (
                        exc.error_code
                    ),
                    "message": str(
                        exc
                    ),
                },
            }

        except Exception:

            return {
                "available": False,
                "error": {
                    "code": (
                        "gateway_health_error"
                    ),
                    "message": (
                        "Unable to check "
                        "RevelaCode AI Gateway."
                    ),
                },
            }


# =========================================================
# PUBLIC EXPORTS
# =========================================================

__all__ = [
    "EcosystemClient",
    "EcosystemClientError",
]
# ============================================================
# BACKWARD-COMPATIBILITY WRAPPERS
# ============================================================
# Older ecosystem providers import these functions directly.
# Keep them available while the new EcosystemClient class is
# the primary implementation.

_default_client: EcosystemClient | None = None


def _get_default_client() -> EcosystemClient:
    global _default_client

    if _default_client is None:
        _default_client = EcosystemClient()

    return _default_client


def service_configured():
    return _get_default_client().service_configured()


def build_headers():
    return _get_default_client().build_headers()


def build_url(path):
    return _get_default_client().build_url(path)


def get_context(
    user_id=None,
    session_id=None,
    domain=None,
    include=None,
):
    return _get_default_client().get_context(
        user_id=user_id,
        session_id=session_id,
        domain=domain,
        include=include,
    )


def get_domain_context(
    domain,
    user_id=None,
    session_id=None,
    include=None,
):
    return _get_default_client().get_domain_context(
        domain=domain,
        user_id=user_id,
        session_id=session_id,
        include=include,
    )


def try_get_context(
    user_id=None,
    session_id=None,
    domain=None,
    include=None,
):
    return _get_default_client().try_get_context(
        user_id=user_id,
        session_id=session_id,
        domain=domain,
        include=include,
    )


def run_operation(
    domain,
    operation,
    user_id=None,
    payload=None,
    message=None,
):
    return _get_default_client().run_operation(
        domain=domain,
        operation=operation,
        user_id=user_id,
        payload=payload,
        message=message,
    )


def try_run_operation(
    domain,
    operation,
    user_id=None,
    payload=None,
    message=None,
):
    return _get_default_client().try_run_operation(
        domain=domain,
        operation=operation,
        user_id=user_id,
        payload=payload,
        message=message,
    )


def check_gateway():
    return _get_default_client().check_gateway()


__all__ = [
    "EcosystemClient",
    "EcosystemClientError",
    "service_configured",
    "build_headers",
    "build_url",
    "get_context",
    "get_domain_context",
    "try_get_context",
    "run_operation",
    "try_run_operation",
    "check_gateway",
]