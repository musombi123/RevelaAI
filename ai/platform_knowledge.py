"""
RevelaAI Platform Knowledge Client

Retrieves authoritative public knowledge about RevelaCode.

Sources:
    - RevelaCode public platform information
    - RevelaCode public legal documents
    - Official public URLs

Important:

    RevelaAI never accesses MongoDB directly.

    Public legal documents are retrieved through the
    public RevelaCode HTTP endpoints.
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

REQUEST_TIMEOUT = max(
    4,
    float(
        os.getenv(
            "PLATFORM_KNOWLEDGE_TIMEOUT",
            "10",
        )
    ),
)


# =========================================================
# TIME
# =========================================================

def now_utc() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


# =========================================================
# PUBLIC URL HELPERS
# =========================================================

def public_url(
    env_name: str,
    fallback: str,
) -> str:
    return (
        os.getenv(
            env_name,
            fallback,
        )
        .strip()
        .rstrip("/")
    )


# =========================================================
# FALLBACK MANIFEST
# =========================================================

def fallback_platform_manifest() -> dict[str, Any]:
    """
    Safe fallback containing only public,
    non-sensitive RevelaCode information.
    """

    revelacode_url = public_url(
        "REVELACODE_PUBLIC_URL",
        "https://revelacode-frontend.onrender.com",
    )

    revelacode_backend_url = public_url(
        "REVELACODE_BACKEND_PUBLIC_URL",
        "https://revelacode-backend.onrender.com",
    )

    revelaai_url = public_url(
        "REVELAAI_PUBLIC_URL",
        "https://revelaai.onrender.com",
    )

    github_frontend = (
        os.getenv(
            "REVELACODE_GITHUB_FRONTEND",
            "https://github.com/musombi123/RevelaCode-Frontend",
        )
        .strip()
    )

    github_backend = (
        os.getenv(
            "REVELACODE_GITHUB_BACKEND",
            "https://github.com/musombi123/RevelaCode-Backend",
        )
        .strip()
    )

    github_ai = (
        os.getenv(
            "REVELAAI_GITHUB",
            "https://github.com/musombi123/RevelaAI",
        )
        .strip()
    )

    public_docs = (
        os.getenv(
            "REVELACODE_DOCS_URL",
            "https://musombiwilliam.github.io/",
        )
        .strip()
    )

    return {
        "source": (
            "revelaai_fallback_platform_knowledge"
        ),

        "source_layer": "platform_knowledge",

        "retrieved_at": now_utc(),

        "identity": {
            "platform": "RevelaCode",
            "ai": "RevelaAI",
            "ecosystem": "Jumuiya",
            "description": (
                "RevelaCode is a technology platform with "
                "RevelaAI as its intelligence layer and "
                "Jumuiya as its connected ecosystem."
            ),
        },

        "architecture": {
            "platform_layer": "RevelaCode Backend",
            "intelligence_layer": "RevelaAI",
            "ecosystem": "Jumuiya",
        },

        "hubs": {
            "biashara": {
                "name": "Biashara",
                "supported": True,
                "description": (
                    "Business operations, marketplace, "
                    "products, sales, customers, inventory, "
                    "expenses and business intelligence."
                ),
            },

            "shamba": {
                "name": "Shamba",
                "supported": True,
                "description": (
                    "Agricultural and farm intelligence."
                ),
            },

            "elimu": {
                "name": "Elimu",
                "supported": True,
                "description": (
                    "Education and learning support."
                ),
            },

            "community": {
                "name": "Community",
                "supported": True,
                "description": (
                    "Community communication and discussions."
                ),
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
            "revelacode": revelacode_url,
            "revelacode_backend": (
                revelacode_backend_url
            ),
            "revelaai": revelaai_url,

            "github_frontend": github_frontend,
            "github_backend": github_backend,
            "github_revelaai": github_ai,

            "documentation": public_docs,

            "privacy_policy": (
                f"{revelacode_backend_url}"
                "/api/legal/privacy"
            ),

            "terms_of_service": (
                f"{revelacode_backend_url}"
                "/api/legal/terms"
            ),
        },
    }


# =========================================================
# FETCH PLATFORM MANIFEST
# =========================================================

def fetch_platform_manifest() -> dict[str, Any]:
    """
    Fetch the platform manifest when available.

    Falls back to the safe public manifest if the endpoint
    is unavailable.
    """

    try:

        response = requests.get(
            PLATFORM_ENDPOINT,
            headers={
                "Accept": "application/json",
                "User-Agent": (
                    "RevelaAI-PlatformKnowledge/2.0"
                ),
            },
            timeout=REQUEST_TIMEOUT,
        )

        response.raise_for_status()

        payload = response.json()

        if not isinstance(
            payload,
            dict,
        ):
            raise ValueError(
                "Platform manifest must be an object."
            )

        # Support both:
        #
        # {"data": {...}}
        #
        # and:
        #
        # {...manifest...}

        if isinstance(
            payload.get("data"),
            dict,
        ):

            data = payload[
                "data"
            ]

        else:

            data = payload

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
# EXTRACT DOCUMENT PAYLOAD
# =========================================================

def _extract_document_payload(
    payload: Any,
    document_type: str,
) -> dict[str, Any] | None:
    """
    Normalize several supported public-document
    response shapes.

    Supported:

        {
            "status": "success",
            "type": "terms",
            "content": "...",
            "version": "2.0"
        }

    and:

        {
            "data": {
                "content": "...",
                "version": "2.0"
            }
        }
    """

    if not isinstance(
        payload,
        dict,
    ):
        return None

    candidate = payload

    nested = payload.get(
        "data"
    )

    if isinstance(
        nested,
        dict,
    ):
        candidate = nested

    content = str(
        candidate.get(
            "content",
            "",
        )
        or candidate.get(
            "text",
            "",
        )
        or candidate.get(
            "full_text",
            "",
        )
        or ""
    ).strip()

    if not content:
        return None

    version = (
        candidate.get(
            "version",
            "1.0",
        )
        or "1.0"
    )

    resolved_type = (
        candidate.get(
            "type",
            document_type,
        )
        or document_type
    )

    updated_at = (
        candidate.get(
            "updated_at"
        )
        or candidate.get(
            "effective_at"
        )
    )

    if hasattr(
        updated_at,
        "isoformat",
    ):
        updated_at = (
            updated_at.isoformat()
        )

    return {
        "available": True,
        "source": "revelacode_public_legal_endpoint",
        "document_type": str(
            resolved_type
        ).strip().lower(),
        "version": str(
            version
        ),
        "content": content,
        "updated_at": updated_at,
    }


# =========================================================
# FETCH LEGAL DOCUMENT DIRECTLY
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
            "document_type": normalized,
            "error": (
                "unsupported_document_type"
            ),
        }

    # The REAL public endpoint is:
    #
    # /api/legal/<doc_type>
    #
    # It is not the /api/ai/platform/legal endpoint.

    public_endpoint = (
        f"{REVELACODE_BACKEND_URL}"
        f"/api/legal/{normalized}"
    )

    try:

        response = requests.get(
            public_endpoint,
            headers={
                "Accept": "application/json",
                "User-Agent": (
                    "RevelaAI-LegalKnowledge/2.0"
                ),
            },
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
        )

        response.raise_for_status()

        payload = response.json()

        document = (
            _extract_document_payload(
                payload,
                normalized,
            )
        )

        if document is None:

            return {
                "available": False,
                "document_type": normalized,
                "url": public_endpoint,
                "error": (
                    "legal_document_content_missing"
                ),
            }

        document[
            "url"
        ] = public_endpoint

        document[
            "retrieved_at"
        ] = now_utc()

        return document

    except Exception as exc:

        return {
            "available": False,
            "document_type": normalized,
            "url": public_endpoint,
            "retrieved_at": now_utc(),
            "error": (
                "legal_document_unavailable"
            ),
            "error_detail": str(
                exc
            ),
        }


# =========================================================
# LEGAL REQUEST DETECTION
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
    """

    manifest = (
        fetch_platform_manifest()
    )

    legal_documents = {}

    requested_documents = (
        legal_document_requested(
            message
        )
    )

    for document_type in (
        requested_documents
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
            requested_documents
        ),

        "retrieved_at": now_utc(),
    }


__all__ = [
    "fetch_platform_manifest",
    "fetch_legal_document",
    "legal_document_requested",
    "get_platform_knowledge",
]

