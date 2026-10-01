"""
RevelaAI Ecosystem Client

Low-level HTTP client used by RevelaAI to communicate with the
internal RevelaCode AI Gateway.

The client:
    - authenticates service-to-service requests
    - sends user-scoped context requests
    - applies network timeouts
    - handles malformed/unavailable responses safely
    - never exposes the service secret in logs
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
# CONFIGURATION
# =========================================================

REVELACODE_BACKEND_URL = (
    os.getenv(
        "REVELACODE_BACKEND_URL",
        "https://revelacode-backend.onrender.com",
    )
    .strip()
    .rstrip("/")
)

REVELAAI_SERVICE_KEY = (
    os.getenv(
        "REVELAAI_SERVICE_KEY",
        "",
    )
    .strip()
)

CONNECT_TIMEOUT = float(
    os.getenv(
        "REVELACODE_CONNECT_TIMEOUT",
        "10",
    )
)

READ_TIMEOUT = float(
    os.getenv(
        "REVELACODE_READ_TIMEOUT",
        "30",
    )
)

MAX_RESPONSE_BYTES = int(
    os.getenv(
        "REVELACODE_MAX_RESPONSE_BYTES",
        "2000000",
    )
)


# =========================================================
# ENDPOINTS
# =========================================================

AI_CONTEXT_ENDPOINT = "/api/ai/context"

AI_DOMAIN_ENDPOINT = "/api/ai"


# =========================================================
# CLIENT ERROR
# =========================================================

class EcosystemClientError(Exception):
    """
    Raised when RevelaAI cannot retrieve platform context.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        error_code: str | None = None,
    ):
        super().__init__(
            message
        )

        self.status_code = status_code
        self.error_code = error_code


# =========================================================
# CONFIG VALIDATION
# =========================================================

def service_configured() -> bool:
    """
    Return True when the internal service credential exists.
    """

    return bool(
        REVELAAI_SERVICE_KEY
    )


# =========================================================
# HEADERS
# =========================================================

def build_headers() -> dict[str, str]:
    """
    Build headers for an internal RevelaAI -> RevelaCode request.

    The service key is never logged.
    """

    if not REVELAAI_SERVICE_KEY:

        raise EcosystemClientError(
            "REVELAAI_SERVICE_KEY is not configured.",
            error_code="service_key_missing",
        )

    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "RevelaAI-Ecosystem/1.0",
        "X-REVELAAI-SERVICE-KEY": (
            REVELAAI_SERVICE_KEY
        ),
    }


# =========================================================
# URL
# =========================================================

def build_url(
    path: str,
) -> str:
    """
    Build an absolute RevelaCode backend URL.
    """

    normalized_path = (
        str(path or "")
        .strip()
    )

    if not normalized_path.startswith("/"):
        normalized_path = (
            "/"
            + normalized_path
        )

    return (
        REVELACODE_BACKEND_URL
        + normalized_path
    )


# =========================================================
# RESPONSE HANDLING
# =========================================================

def _parse_json_response(
    response: requests.Response,
) -> dict:
    """
    Parse a JSON response and normalize failures.
    """

    content_length = response.headers.get(
        "Content-Length"
    )

    if content_length:

        try:

            if int(
                content_length
            ) > MAX_RESPONSE_BYTES:

                raise EcosystemClientError(
                    "RevelaCode returned an oversized response.",
                    status_code=response.status_code,
                    error_code="response_too_large",
                )

        except ValueError:
            pass

    try:

        data = response.json()

    except ValueError as exc:

        raise EcosystemClientError(
            "RevelaCode returned invalid JSON.",
            status_code=response.status_code,
            error_code="invalid_json_response",
        ) from exc

    if not isinstance(
        data,
        dict,
    ):

        raise EcosystemClientError(
            "RevelaCode returned an unexpected response format.",
            status_code=response.status_code,
            error_code="invalid_response_format",
        )

    return data


def _validate_response(
    response: requests.Response,
) -> dict:
    """
    Validate HTTP status and return the normalized JSON body.
    """

    data = _parse_json_response(
        response
    )

    if not response.ok:

        error_message = (
            data.get("message")
            or "RevelaCode AI Gateway request failed."
        )

        error_code = (
            data.get("code")
            or data.get("error")
            or "gateway_request_failed"
        )

        raise EcosystemClientError(
            str(error_message),
            status_code=response.status_code,
            error_code=str(error_code),
        )

    return data


# =========================================================
# REQUEST
# =========================================================

def _post(
    path: str,
    payload: dict,
) -> dict:
    """
    Perform an authenticated POST request to RevelaCode.
    """

    url = build_url(
        path
    )

    headers = build_headers()

    try:

        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=(
                CONNECT_TIMEOUT,
                READ_TIMEOUT,
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
            error_code="gateway_connection_error",
        ) from exc

    except requests.RequestException as exc:

        raise EcosystemClientError(
            "RevelaCode request failed.",
            error_code="gateway_request_error",
        ) from exc

    return _validate_response(
        response
    )


# =========================================================
# CONTEXT REQUEST
# =========================================================

def get_context(
    *,
    user_id: str,
    domain: str = "general",
    message: str = "",
    include: dict[str, Any] | None = None,
) -> dict:
    """
    Retrieve user-scoped ecosystem context from RevelaCode.

    Example:

        get_context(
            user_id="123",
            domain="biashara",
            message="Why are my sales dropping?",
        )

    Returns the gateway's structured response.
    """

    normalized_user_id = (
        str(user_id or "")
        .strip()
    )

    if not normalized_user_id:

        raise EcosystemClientError(
            "user_id is required.",
            error_code="missing_user_id",
        )

    normalized_domain = (
        str(domain or "general")
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

    response = _post(
        AI_CONTEXT_ENDPOINT,
        payload,
    )

    if response.get(
        "status"
    ) != "success":

        raise EcosystemClientError(
            str(
                response.get(
                    "message",
                    "RevelaCode rejected the context request.",
                )
            ),
            error_code="context_request_rejected",
        )

    data = response.get(
        "data"
    )

    if not isinstance(
        data,
        dict,
    ):

        raise EcosystemClientError(
            "RevelaCode returned no usable ecosystem context.",
            error_code="empty_context_response",
        )

    return data


# =========================================================
# DOMAIN REQUEST
# =========================================================

def get_domain_context(
    *,
    user_id: str,
    domain: str,
    message: str = "",
    include: dict[str, Any] | None = None,
) -> dict:
    """
    Retrieve context through a domain-specific gateway route.

    Example:

        POST /api/ai/biashara
    """

    normalized_user_id = (
        str(user_id or "")
        .strip()
    )

    if not normalized_user_id:

        raise EcosystemClientError(
            "user_id is required.",
            error_code="missing_user_id",
        )

    normalized_domain = (
        str(domain or "")
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

    response = _post(
        f"{AI_DOMAIN_ENDPOINT}/{normalized_domain}",
        payload,
    )

    if response.get(
        "status"
    ) != "success":

        raise EcosystemClientError(
            str(
                response.get(
                    "message",
                    "RevelaCode rejected the domain context request.",
                )
            ),
            error_code="domain_context_request_rejected",
        )

    data = response.get(
        "data"
    )

    if not isinstance(
        data,
        dict,
    ):

        raise EcosystemClientError(
            "RevelaCode returned no usable domain context.",
            error_code="empty_domain_context",
        )

    return data


# =========================================================
# SAFE CONTEXT
# =========================================================

def try_get_context(
    *,
    user_id: str,
    domain: str = "general",
    message: str = "",
    include: dict[str, Any] | None = None,
) -> dict:
    """
    Best-effort ecosystem lookup.

    This is intended for the orchestrator.

    Failure to reach RevelaCode returns structured fallback
    metadata instead of crashing the entire AI request.
    """

    try:

        return get_context(
            user_id=user_id,
            domain=domain,
            message=message,
            include=include,
        )

    except EcosystemClientError as exc:

        return {
            "source": "revelacode_platform",
            "source_layer": "platform",
            "available": False,
            "domain": (
                str(domain or "general")
                .strip()
                .lower()
            ),
            "error": {
                "code": exc.error_code
                or "ecosystem_unavailable",
                "message": str(
                    exc
                ),
            },
            "context": {},
        }

    except Exception:

        return {
            "source": "revelacode_platform",
            "source_layer": "platform",
            "available": False,
            "domain": (
                str(domain or "general")
                .strip()
                .lower()
            ),
            "error": {
                "code": "unexpected_ecosystem_error",
                "message": (
                    "Ecosystem context is temporarily unavailable."
                ),
            },
            "context": {},
        }


# =========================================================
# HEALTH / CONNECTIVITY TEST
# =========================================================

def check_gateway() -> dict:
    """
    Check whether RevelaCode's AI Gateway is reachable.

    Note:
        /api/ai/health is deliberately public/lightweight, so
        this check does not require the service credential.
    """

    url = build_url(
        "/api/ai/health"
    )

    try:

        response = requests.get(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "RevelaAI-Ecosystem/1.0",
            },
            timeout=(
                CONNECT_TIMEOUT,
                READ_TIMEOUT,
            ),
        )

        data = _validate_response(
            response
        )

        return {
            "available": True,
            "status_code": response.status_code,
            "data": data,
        }

    except EcosystemClientError as exc:

        return {
            "available": False,
            "status_code": exc.status_code,
            "error": {
                "code": exc.error_code,
                "message": str(
                    exc
                ),
            },
        }

    except Exception:

        return {
            "available": False,
            "error": {
                "code": "gateway_health_error",
                "message": (
                    "Unable to check RevelaCode AI Gateway."
                ),
            },
        }