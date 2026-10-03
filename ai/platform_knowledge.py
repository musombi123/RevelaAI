"""
RevelaAI Platform Knowledge Client

Retrieves public, authoritative knowledge about RevelaCode.

This is separate from user-scoped ecosystem context.

Platform knowledge:
    - identity
    - capabilities
    - hubs
    - public links
    - legal documents

User context:
    - business records
    - farm records
    - school information
    - community information

RevelaAI never accesses MongoDB directly.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import requests


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

PLATFORM_ENDPOINT = (
    f"{REVELACODE_BACKEND_URL}"
    "/api/ai/platform"
)

LEGAL_ENDPOINT = (
    f"{REVELACODE_BACKEND_URL}"
    "/api/ai/platform/legal"
)

REQUEST_TIMEOUT = (
    float(
        os.getenv(
            "PLATFORM_KNOWLEDGE_TIMEOUT",
            "10",
        )
    )
)


# =========================================================
# TIME
# =========================================================

def now_utc() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


# =========================================================
# FALLBACK MANIFEST
# =========================================================

def fallback_platform_manifest() -> dict[str, Any]:
    """
    Fallback knowledge guarantees that RevelaAI still
    understands its own identity if the backend knowledge
    endpoint is temporarily unreachable.

    This is intentionally public/non-sensitive data.
    """

    return {
        "source": "revelaai_fallback_platform_knowledge",
        "source_layer": "platform_knowledge",

        "retrieved_at": now_utc(),

        "identity": {
            "platform": "RevelaCode",
            "ai": "RevelaAI",
            "ecosystem": "Jumuiya",
        },

        "hubs": {
            "biashara": {
                "supported": True,
            },
            "shamba": {
                "supported": True,
            },
            "elimu": {
                "supported": True,
            },
            "community": {
                "supported": True,
            },
        },

        "capabilities": {
            "general_assistance": {
                "supported": True,
                "runtime_status": "available",
            },

            "programming": {
                "supported": True,
                "runtime_status": "available",
            },

            "education": {
                "supported": True,
                "runtime_status": "available",
            },

            "scripture_theology": {
                "supported": True,
                "runtime_status": "available",
            },

            "creative_work": {
                "supported": True,
                "runtime_status": "available",
            },

            "image_generation": {
                "supported": True,
                "runtime_status": "available",
                "model": (
                    "black-forest-labs/FLUX.1-schnell"
                ),
            },

            "pdf_processing": {
                "supported": True,
                "runtime_status": "available",
                "processor": "PyMuPDF",
            },

            "voice": {
                "supported": True,
                "runtime_status": "available",
                "asr": "openai/whisper-large-v3",
                "tts": "hexgrad/Kokoro-82M",
            },

            "online_research": {
                "supported": True,
                "runtime_status": "connected",
            },

            "biashara_intelligence": {
                "supported": True,
                "runtime_status": "integrated",
            },

            "shamba_intelligence": {
                "supported": True,
                "runtime_status": "integrated",
            },

            "platform_context": {
                "supported": True,
                "runtime_status": "connected",
            },
        },

        "public_links": {
            "revelacode": (
                "https://revelacode-frontend.onrender.com"
            ),
            "revelacode_backend": (
                "https://revelacode-backend.onrender.com"
            ),
            "revelaai": (
                "https://revelaai.onrender.com"
            ),
            "github_frontend": (
                "https://github.com/"
                "musombi123/RevelaCode-Frontend"
            ),
            "github_backend": (
                "https://github.com/"
                "musombi123/RevelaCode-Backend"
            ),
            "github_revelaai": (
                "https://github.com/"
                "musombi123/RevelaAI"
            ),
            "documentation": (
                "https://musombiwilliam.github.io/"
            ),
            "privacy_policy": (
                "https://revelacode-backend.onrender.com/"
                "api/legal/privacy"
            ),
            "terms_of_service": (
                "https://revelacode-backend.onrender.com/"
                "api/legal/terms"
            ),
        },
    }


# =========================================================
# FETCH MANIFEST
# =========================================================

def fetch_platform_manifest() -> dict[str, Any]:
    try:

        response = requests.get(
            PLATFORM_ENDPOINT,
            headers={
                "Accept": "application/json",
                "User-Agent": (
                    "RevelaAI-PlatformKnowledge/1.0"
                ),
            },
            timeout=REQUEST_TIMEOUT,
        )

        response.raise_for_status()

        payload = (
            response.json()
        )

        data = (
            payload.get(
                "data"
            )
            if isinstance(
                payload,
                dict,
            )
            else None
        )

        if not isinstance(
            data,
            dict,
        ):
            raise ValueError(
                "Platform manifest is invalid."
            )

        return data

    except Exception:

        return fallback_platform_manifest()


# =========================================================
# FETCH LEGAL DOCUMENT
# =========================================================

def fetch_legal_document(
    document_type: str,
) -> dict[str, Any]:

    normalized = (
        str(
            document_type or ""
        )
        .strip()
        .lower()
    )

    if normalized not in {
        "privacy",
        "terms",
    }:
        return {
            "available": False,
            "error": "unsupported_document_type",
        }

    try:

        response = requests.get(
            f"{LEGAL_ENDPOINT}/{normalized}",
            headers={
                "Accept": "application/json",
                "User-Agent": (
                    "RevelaAI-LegalKnowledge/1.0"
                ),
            },
            timeout=REQUEST_TIMEOUT,
        )

        response.raise_for_status()

        payload = response.json()

        data = (
            payload.get(
                "data"
            )
            if isinstance(
                payload,
                dict,
            )
            else None
        )

        if not isinstance(
            data,
            dict,
        ):
            raise ValueError(
                "Legal document response is invalid."
            )

        return data

    except Exception:

        return {
            "available": False,
            "document_type": normalized,
            "error": "legal_document_unavailable",
        }


# =========================================================
# RELEVANCE
# =========================================================

def legal_document_requested(
    message: str,
) -> list[str]:

    text = (
        str(
            message or ""
        )
        .strip()
        .lower()
    )

    requested = []

    if any(
        phrase in text
        for phrase in [
            "privacy policy",
            "privacy",
            "data privacy",
            "personal data",
            "my data",
        ]
    ):
        requested.append(
            "privacy"
        )

    if any(
        phrase in text
        for phrase in [
            "terms",
            "terms of service",
            "terms and conditions",
            "conditions of use",
            "legal terms",
        ]
    ):
        requested.append(
            "terms"
        )

    return requested


# =========================================================
# COMPLETE KNOWLEDGE
# =========================================================

def get_platform_knowledge(
    message: str = "",
) -> dict[str, Any]:
    """
    Retrieve platform knowledge and relevant legal documents.

    Manifest retrieval happens for every AI request because
    the payload is small and this keeps the assistant aligned
    with the current platform.

    Legal content is retrieved only when relevant.
    """

    manifest = (
        fetch_platform_manifest()
    )

    legal_documents = {}

    for document_type in (
        legal_document_requested(
            message
        )
    ):

        legal_documents[
            document_type
        ] = fetch_legal_document(
            document_type
        )

    return {
        "available": True,

        "source": "revelacode_platform",

        "manifest": manifest,

        "legal_documents": (
            legal_documents
        ),

        "legal_documents_requested": (
            list(
                legal_documents.keys()
            )
        ),

        "retrieved_at": now_utc(),
    }


__all__ = [
    "fetch_platform_manifest",
    "fetch_legal_document",
    "get_platform_knowledge",
]