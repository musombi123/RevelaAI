"""RevelaAI legacy Flask compatibility application.

This module preserves the original Flask route map and request lifecycle for
routes still awaiting migration to native FastAPI. Do not add new routes here;
new HTTP endpoints belong in fastapi_routes/*.py and must be registered by
asgi.py. Sector-specific behavior is intentionally retained unchanged for the
manual migration pass.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import time
import uuid
from collections import OrderedDict
from pathlib import Path
from threading import Lock
from typing import Any

import jwt
from dotenv import load_dotenv

from ai.core_mesh import (
    CoreMeshError,
    get_core_mesh_dashboard,
    propose_genesis_invention,
    propose_mind_evolution,
)
from ai.unknown_learning import attach_genesis_proposal, attach_improvement_proposal, list_known, publish_known, save_teaching


# =========================================================
# ENVIRONMENT
# =========================================================

load_dotenv()


# =========================================================
# REVELACODE AUTHENTICATION
# =========================================================

JWT_SECRET = (
    os.getenv(
        "JWT_SECRET",
        "",
    ).strip()
)

JWT_ALGORITHM = "HS256"


def resolve_revelacode_user_id() -> str | None:
    """
    Resolve the authenticated RevelaCode user from the
    Authorization Bearer JWT.

    The JWT establishes identity only.

    Actual platform data must come through the approved
    RevelaCode AI gateway/provider layers.
    """

    authorization = (
        request.headers.get(
            "Authorization",
            "",
        )
        or ""
    ).strip()

    if not authorization:
        return None

    if not authorization.startswith(
        "Bearer "
    ):
        return None

    token = authorization[
        len("Bearer "):
    ].strip()

    if not token:
        return None

    if not JWT_SECRET:

        app.logger.error(
            "JWT_SECRET is not configured."
        )

        return None

    try:

        payload = jwt.decode(
            token,
            JWT_SECRET,
            algorithms=[
                JWT_ALGORITHM
            ],
            options={
                "require": [
                    "sub",
                    "iat",
                    "exp",
                ]
            },
        )

    except jwt.ExpiredSignatureError:

        app.logger.warning(
            "RevelaAI rejected expired RevelaCode JWT."
        )

        return None

    except jwt.InvalidTokenError:

        app.logger.warning(
            "RevelaAI rejected invalid RevelaCode JWT."
        )

        return None

    user_id = (
        payload.get("sub")
        or payload.get("user_id")
        or payload.get("id")
    )

    if user_id is None:
        return None

    user_id = str(
        user_id
    ).strip()

    if not user_id:
        return None

    return user_id


# =========================================================
# FLASK
# =========================================================

from flask import (
    Flask,
    Response,
    g,
    jsonify,
    request,
    send_file,
    stream_with_context,
)

from flask_cors import CORS
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.middleware.proxy_fix import ProxyFix


# =========================================================
# AI
# =========================================================

from ai.ai_client import (
    generate_hf_image,
    generate_hf_speech,
    get_text_provider_status,
    hf_configured,
    transcribe_hf_audio,
)

from ai.intent_router import (
    classify_intent,
)

from ai.global_brain_adapter import build_global_context
from ai.hub_prompts import HUB_LABELS, get_identity_answer

from ai.image_prompt import (
    build_image_prompt,
)

from ai.svg_designer import (
    generate_svg,
)

from ai.json_utils import (
    enforce_base_schema,
    error_response,
    extract_json,
)

from services.ai_service import (
    detect_capability,
    process_message,
)


# =========================================================
# EXPERT MODULES
# =========================================================

from services.expert_law import (
    analyze_legal_query,
)

from services.expert_medicine import (
    analyze_medical_query,
)


# =========================================================
# DOCUMENTS
# =========================================================

from utils.docx_utils import (
    extract_text_from_docx,
)


# =========================================================
# ROUTES
# =========================================================

from routes.chat_routes import (
    chat_bp,
    _load_personalization_context,
    _persist_turn,
)

from routes.vision_routes import vision_bp

from routes.memory_routes import (
    _require_identity,
)

from routes.living_brain_routes import (
    living_brain_bp,
)

from routes.explain_routes import (
    explain_bp,
)

from routes.memory_routes import (
    memory_bp,
)

from routes.research_routes import (
    research_bp,
)

from routes.users_routes import (
    users_bp,
)

from routes.hub_routes import (
    hub_bp,
)
from routes.meta_engineer_routes import (
    meta_engineer_bp,
)

from routes.automation_fabric_routes import automation_fabric_bp
from routes.usect_zero_routes import usect_zero_bp

from revelai.routers.sci_core import sci_router
from revelai.routers.agi_router import agi_router
from revelai.core.agi_manifest import get_self_description_answer

from whatsapp_webhook import (
    whatsapp_bp,
)


# =========================================================
# FRAMEWORK-NEUTRAL RUNTIME CONFIGURATION
# =========================================================

from services.runtime_config import (
    APP_NAME,
    AUDIO_DIR,
    AUDIO_RETENTION_SECONDS,
    BASE_DIR,
    DOCUMENT_MAX_MODEL_CHARS,
    ENVIRONMENT,
    IMAGE_DIR,
    IMAGE_RETENTION_SECONDS,
    MAX_CONTENT_LENGTH,
    PORT,
    REVELAAI_BUILD_ID,
    REVELAAI_ENABLE_HF_TTS,
    REVELAAI_IMAGE_ENGINE_VERSION,
    VOICE_MAX_BYTES,
    cleanup_generated_files,
    configured_image_model,
    get_active_text_model,
    get_active_text_provider,
    get_revelaai_text_status,
)
from services.document_service import process_uploaded_document as _process_uploaded_document
from services.image_service import (
    generate_image_asset as _generate_image_asset,
    is_image_generation_request,
    parse_image_options,
)


# =========================================================
# LOGGING
# =========================================================

LOG_LEVEL = (
    os.getenv(
        "LOG_LEVEL",
        "INFO",
    ).strip().upper()
)

logging.basicConfig(
    level=getattr(
        logging,
        LOG_LEVEL,
        logging.INFO,
    )
)


# =========================================================
# FLASK APP
# =========================================================

app = Flask(
    "app"
)

app.config.update({
    "MAX_CONTENT_LENGTH": MAX_CONTENT_LENGTH,
    "PROPAGATE_EXCEPTIONS": False,
})

app.logger.info(
    "RevelaAI v2.0 - 3 Repos Wired - Cluster0 revelacode users + "
    "revelai memory/ideas - Self-Learning per userId"
)


# =========================================================
# PROXY SUPPORT
# =========================================================

app.wsgi_app = ProxyFix(
    app.wsgi_app,
    x_for=1,
    x_proto=1,
    x_host=1,
)


# =========================================================
# CORS
# =========================================================

def parse_cors_origins() -> list[str]:
    """
    Read trusted frontend origins, with deployment configuration extending
    the built-in allowlist rather than replacing production origins.
    """

    default_origins = (
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://revelacode-frontend.onrender.com",
        "https://revelacode.co.ke",
        "https://www.revelacode.co.ke",
        "https://localhost",
    )

    configured = (
        os.getenv(
            "CORS_ORIGINS",
            "",
        )
        or ""
    )

    origins: list[str] = []

    for item in list(default_origins) + configured.split(","):

        origin = item.strip().rstrip("/")

        if origin and origin not in origins:

            origins.append(
                origin
            )

    return origins


CORS_ORIGINS = (
    parse_cors_origins()
)


CORS(
    app,
    resources={
        r"/*": {
            "origins": CORS_ORIGINS,
        }
    },
    supports_credentials=True,
    allow_headers=[
        "Content-Type",
        "Authorization",
        "userId",
        "X-User-ID",
        "X-Session-ID",
        "X-Request-ID",
    ],
    methods=[
        "GET",
        "POST",
        "PUT",
        "PATCH",
        "DELETE",
        "OPTIONS",
    ],
)


# =========================================================
# REQUEST ID
# =========================================================

@app.before_request
def attach_request_id():

    incoming = (
        request.headers.get(
            "X-Request-ID"
        )
        or ""
    ).strip()

    g.request_id = (
        incoming[:100]
        if incoming
        else uuid.uuid4().hex
    )


# =========================================================
# SCI-CORE REVERSIBLE THROTTLE GUARD
# =========================================================
from collections import deque
from routes.meta_engineer_routes import _authenticated_admin as _sci_admin_check
from revelai.sci_core.disaster_manager import THROTTLE as SCI_THROTTLE

_SCI_REQUEST_TIMES = deque()
_SCI_RATE_LOCK = Lock()

@app.before_request
def sci_core_rate_guard():
    now = time.time()
    with _SCI_RATE_LOCK:
        while _SCI_REQUEST_TIMES and now - _SCI_REQUEST_TIMES[0] > 1:
            _SCI_REQUEST_TIMES.popleft()
        _SCI_REQUEST_TIMES.append(now)
        measured_rps = len(_SCI_REQUEST_TIMES)
    if measured_rps > 200 and not SCI_THROTTLE.get("enabled"):
        from datetime import datetime, timezone
        SCI_THROTTLE.update({"enabled": True, "reason": "observed_rps_over_200", "since": datetime.now(timezone.utc).isoformat()})
    # A simulation activates a short, reversible cooldown. Exempt readiness,
    # health, and the recovery control path to avoid locking operators out.
    if SCI_THROTTLE.get("enabled"):
        since = SCI_THROTTLE.get("since")
        try:
            from datetime import datetime, timezone
            started = datetime.fromisoformat(str(since)).timestamp()
        except Exception:
            started = now
        if now - started > 60:
            SCI_THROTTLE.update({"enabled": False, "reason": None, "since": None})
        elif request.path in {"/health", "/ready", "/api/sci/shield/status", "/api/sci/shield/dashboard", "/api/sci/disaster/simulate"}:
            return None
        else:
            return jsonify({"status": "error", "code": "SCI_SHIELD_COOLDOWN", "message": "RevelaAI Shield Active - Cooling Down", "retry_after_seconds": max(1, int(60 - (now - started)))}), 429
    # The guard reports actual pressure but does not start a global cooldown
    # solely from an unauthenticated burst; upstream proxy rate limiting remains recommended.
    g.sci_core_observed_rps = measured_rps
    return None


@app.after_request
def add_response_headers(
    response,
):

    request_id = getattr(
        g,
        "request_id",
        None,
    )

    if request_id:

        response.headers[
            "X-Request-ID"
        ] = request_id

    response.headers[
        "X-Content-Type-Options"
    ] = "nosniff"

    response.headers[
        "X-Frame-Options"
    ] = "DENY"

    response.headers[
        "Referrer-Policy"
    ] = "strict-origin-when-cross-origin"

    return response


# =========================================================
# ERROR HANDLERS
# =========================================================

@app.errorhandler(
    RequestEntityTooLarge
)
def handle_request_too_large(
    error,
):

    return jsonify(
        error_response(
            "REQUEST_TOO_LARGE",
            (
                "The uploaded file or request "
                "exceeds the allowed size."
            ),
        )
    ), 413


@app.errorhandler(404)
def handle_not_found(
    error,
):

    return jsonify({
        "status": "error",
        "error": {
            "code": "NOT_FOUND",
            "message": "Resource not found.",
        },
        "request_id": getattr(
            g,
            "request_id",
            None,
        ),
    }), 404


@app.errorhandler(405)
def handle_method_not_allowed(
    error,
):

    return jsonify({
        "status": "error",
        "error": {
            "code": "METHOD_NOT_ALLOWED",
            "message": "HTTP method is not allowed.",
        },
        "request_id": getattr(
            g,
            "request_id",
            None,
        ),
    }), 405


@app.errorhandler(Exception)
def handle_unexpected_error(
    error,
):

    app.logger.exception(
        "Unhandled request error | request_id=%s",
        getattr(
            g,
            "request_id",
            None,
        ),
    )

    return jsonify({
        "status": "error",
        "error": {
            "code": "SERVER_ERROR",
            "message": (
                "RevelaAI encountered an unexpected "
                "server error."
            ),
        },
        "request_id": getattr(
            g,
            "request_id",
            None,
        ),
    }), 500


# =========================================================
# FRAMEWORK-NEUTRAL CONVERSATION STORE
# =========================================================

from services.conversation_store import (
    MAX_HISTORY,
    MAX_SESSIONS,
    SESSION_TTL_SECONDS,
    SESSION_MEMORY,
    SESSION_LOCK,
    _prune_session_memory,
    get_session,
    save_session,
    normalize_client_context,
    build_server_context,
    resolve_conversation_context,
    build_session_id,
)


def get_session_id() -> str:
    """Flask adapter only: translate request globals into a shared session ID."""
    authenticated_user_id = resolve_revelacode_user_id()
    session_id = build_session_id(
        request.headers,
        request.cookies,
        authenticated_user_id,
    )
    g.revelaai_session_id = session_id
    return session_id


# =========================================================
# SESSION COOKIE
# =========================================================

@app.after_request
def set_session_cookie(
    response,
):

    session_id = getattr(
        g,
        "revelaai_session_id",
        None,
    )

    if (
        session_id
        and not request.cookies.get(
            "revelaai_session"
        )
        and not request.headers.get(
            "X-Session-ID"
        )
    ):

        response.set_cookie(
            "revelaai_session",
            session_id,
            max_age=SESSION_TTL_SECONDS,
            secure=True,
            httponly=True,
            samesite="Lax",
        )

    return response


from services.feature_registry import FEATURES, FEATURES_DIR, load_features


# =========================================================
# DOCUMENT PROCESSING
# =========================================================

def process_uploaded_document(file_storage, *, prompt: str | None = None) -> tuple[str, dict[str, Any]]:
    """Flask compatibility adapter for the framework-neutral document service."""
    if prompt is None:
        prompt = request.form.get("message", "")
    return _process_uploaded_document(file_storage, prompt=str(prompt or ""))

# =========================================================
# IMAGE / VISUAL DETECTION
# =========================================================
#
# Capability detection is centralized in services.ai_service.
#
# This wrapper intentionally delegates to the same authority.
#
# That eliminates drift between:
#
#     app.py
#     services.ai_service.py
#
# Example:
#
#     generate a random image with writing hello kenya
#
# must be classified as:
#
#     image_generation
#



# =========================================================
# IMAGE OPTIONS
# =========================================================



# =========================================================
# IMAGE ASSET SAVERS
# =========================================================

def generate_image_asset(
    message: str,
    *,
    image_options: dict[str, Any] | None = None,
    request_base_url: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Compatibility adapter; native routes call services.image_service directly."""
    if request_base_url is None:
        try:
            request_base_url = request.host_url
        except RuntimeError:
            request_base_url = None
    if request_id is None:
        try:
            request_id = getattr(g, "request_id", None)
        except RuntimeError:
            request_id = None
    return _generate_image_asset(
        message,
        image_options=image_options,
        request_base_url=request_base_url,
        request_id=request_id,
    )

# =========================================================
# IMAGE RESPONSE
# =========================================================

def generate_image_response(
    message: str,
    *,
    image_options: dict[str, Any] | None = None,
) -> dict[str, Any]:

    app.logger.info(
        "IMAGE GENERATION BRANCH | "
        "request_id=%s | build=%s | engine_version=%s",
        getattr(
            g,
            "request_id",
            None,
        ),
        REVELAAI_BUILD_ID,
        REVELAAI_IMAGE_ENGINE_VERSION,
    )

    try:

        asset = generate_image_asset(
            message,
            image_options=image_options,
        )

    except ValueError as exc:

        app.logger.exception(
            "Image planning/validation failed | "
            "request_id=%s | error=%s",
            getattr(
                g,
                "request_id",
                None,
            ),
            exc,
        )

        return {
            "ok": False,
            "response": jsonify(
                error_response(
                    "IMAGE_REQUEST_INVALID",
                    str(exc),
                )
            ),
            "status_code": 400,
        }

    except Exception as exc:

        app.logger.exception(
            "Image generation failed | "
            "request_id=%s | error=%s",
            getattr(
                g,
                "request_id",
                None,
            ),
            exc,
        )

        return {
            "ok": False,
            "response": jsonify(
                error_response(
                    "IMAGE_GENERATION_FAILED",
                    (
                        "RevelaAI could not generate "
                        "the requested design."
                    ),
                )
            ),
            "status_code": 502,
        }

    response = enforce_base_schema(
        query=message,
        mode="image",
        data={
            "type": "image",
            "format": asset[
                "asset_type"
            ],
            "urls": [
                asset[
                    "image_url"
                ],
            ],
        },
        sources=[],
        meta={
            "provider": (
                "huggingface"
                if asset[
                    "asset_type"
                ] == "png"
                else "huggingface-svg"
            ),
            "model": (
                configured_image_model()
                if asset[
                    "asset_type"
                ] == "png"
                else None
            ),
            "build_id": REVELAAI_BUILD_ID,
            "image_engine": asset[
                "image_plan"
            ].get(
                "engine"
            ),
            "engine_version": (
                REVELAAI_IMAGE_ENGINE_VERSION
            ),
            "intent": "image_generation",
            "design": asset[
                "image_plan"
            ],
            "image": {
                "width": asset[
                    "width"
                ],
                "height": asset[
                    "height"
                ],
                "aspect_ratio": asset[
                    "aspect_ratio"
                ],
                "seed": asset[
                    "seed"
                ],
                "text_aware": bool(
                    asset[
                        "image_plan"
                    ].get(
                        "has_text"
                    )
                ),
            },
            "multimodal": {
                "type": "image",
                "format": asset[
                    "asset_type"
                ],
                "editable": (
                    asset[
                        "asset_type"
                    ] == "svg"
                ),
            },
        },
    )

    return {
        "ok": True,
        "response": jsonify(
            response
        ),
        "status_code": 200,
        "filename": asset[
            "filename"
        ],
        "filepath": asset[
            "filepath"
        ],
        "image_url": asset[
            "image_url"
        ],
        "asset_type": asset[
            "asset_type"
        ],
        "image_plan": asset[
            "image_plan"
        ],
    }


from services.conversation_store import save_image_conversation


# =========================================================
# EXECUTABLE ACTION HANDLER
# =========================================================

def execute_ai_action(
    ai_result: dict[str, Any],
    *,
    message: str,
    image_options: dict[str, Any] | None = None,
    session_id: str,
    session: dict[str, Any],
):
    """
    Execute an action returned by services.ai_service.

    Currently supported:

        image_generation

    This is a defensive execution layer.

    The normal /ai route already catches image intent before
    process_message(), but this handler ensures that if an
    action reaches the route from another capability classifier,
    it still executes instead of being interpreted as text.
    """

    if not isinstance(
        ai_result,
        dict,
    ):

        return None

    if not ai_result.get(
        "action_required",
        False,
    ):

        return None

    action = (
        ai_result.get(
            "action",
            {},
        )
    )

    if not isinstance(
        action,
        dict,
    ):

        return (
            jsonify(
                error_response(
                    "INVALID_AI_ACTION",
                    "RevelaAI returned an invalid action.",
                )
            ),
            502,
        )

    action_type = str(
        action.get(
            "type",
            "",
        )
        or ""
    ).strip().lower()

    app.logger.info(
        "EXECUTABLE AI ACTION | "
        "request_id=%s | type=%s",
        getattr(
            g,
            "request_id",
            None,
        ),
        action_type,
    )

    if action_type == "image_generation":

        result = (
            generate_image_response(
                message,
                image_options=image_options,
            )
        )

        save_image_conversation(
            session_id,
            session,
            message,
            success=bool(
                result.get(
                    "ok",
                    False,
                )
            ),
        )

        return (
            result["response"],
            result["status_code"],
        )

    app.logger.warning(
        "Unsupported executable AI action | "
        "request_id=%s | type=%s",
        getattr(
            g,
            "request_id",
            None,
        ),
        action_type,
    )

    return (
        jsonify(
            error_response(
                "UNSUPPORTED_AI_ACTION",
                (
                    "RevelaAI recognized an unsupported "
                    "executable action."
                ),
            )
        ),
        501,
    )


# =========================================================
# DYNAMIC FEATURE CHAT
# =========================================================

@app.route(
    "/chat",
    methods=["POST"],
)
def feature_chat():

    payload = (
        request.get_json(
            silent=True
        )
        or {}
    )

    user_input = (
        payload.get(
            "message",
            "",
        )
        or ""
    ).strip()

    if not user_input:

        return jsonify(
            error_response(
                "EMPTY_MESSAGE",
                "Message required.",
            )
        ), 400

    # -----------------------------------------------------
    # Prevent visual requests from being fed into arbitrary
    # dynamic text features.
    # -----------------------------------------------------

    if is_image_generation_request(
        user_input
    ):

        return jsonify({
            "status": "success",
            "mode": "image_generation",
            "message": (
                "Use the /ai endpoint for image-generation "
                "requests."
            ),
            "request_id": getattr(
                g,
                "request_id",
                None,
            ),
            "build_id": REVELAAI_BUILD_ID,
        })

    responses = {}

    for name, feature in (
        FEATURES.items()
    ):

        try:

            responses[
                name
            ] = feature.run(
                user_input
            )

        except Exception as exc:

            app.logger.warning(
                "Dynamic feature failed | "
                "feature=%s | error=%s",
                name,
                exc,
            )

            responses[
                name
            ] = {
                "error": (
                    "Feature execution failed."
                )
            }

    return jsonify({
        "status": "success",
        "input": user_input,
        "features_used": list(
            FEATURES.keys()
        ),
        "responses": responses,
        "request_id": getattr(
            g,
            "request_id",
            None,
        ),
        "build_id": REVELAAI_BUILD_ID,
    })


# =========================================================
# USECT CORE MESH - SERVER-SIDE ORCHESTRATOR INTEGRATION
# =========================================================

def _core_mesh_admin_allowed(user_id: str | None) -> bool:
    configured = (
        os.getenv("CORE_MESH_ADMIN_USER_IDS", "")
        or os.getenv("META_ENGINEER_ADMIN_USER_IDS", "")
    )
    allowed = {
        item.strip()
        for item in configured.split(",")
        if item.strip()
    }
    return bool(user_id and allowed and user_id in allowed)


def _core_mesh_error_response(exc: CoreMeshError):
    return jsonify({
        "status": "error",
        "error": {"code": exc.code, "message": str(exc)},
    }), exc.status_code


def _require_core_mesh_user():
    user_id = resolve_revelacode_user_id()
    if not user_id:
        return None, (jsonify({
            "status": "error",
            "error": {
                "code": "authentication_required",
                "message": "Sign in with a valid RevelaCode session to access core status.",
            },
        }), 401)
    return user_id, None


def _require_core_mesh_operator(user_id: str):
    configured = (
        os.getenv("CORE_MESH_ADMIN_USER_IDS", "")
        or os.getenv("META_ENGINEER_ADMIN_USER_IDS", "")
    ).strip()
    if not configured:
        return (jsonify({
            "status": "error",
            "error": {
                "code": "core_mesh_operator_not_configured",
                "message": "Configure CORE_MESH_ADMIN_USER_IDS server-side before enabling invention/evolution actions.",
            },
        }), 503)
    if not _core_mesh_admin_allowed(user_id):
        return (jsonify({
            "status": "error",
            "error": {
                "code": "core_mesh_operator_required",
                "message": "This operation is restricted to an approved Core Mesh operator.",
            },
        }), 403)
    return None


@app.route(
    "/api/core-mesh/dashboard",
    methods=["GET"],
)
def core_mesh_dashboard_api():
    user_id, failure = _require_core_mesh_user()
    if failure:
        return failure
    try:
        snapshot = get_core_mesh_dashboard(
            force_refresh=request.args.get("refresh", "").strip() == "1"
        )
    except Exception:
        app.logger.warning("Core Mesh dashboard snapshot failed.")
        return jsonify({
            "status": "error",
            "error": {"code": "core_mesh_status_unavailable", "message": "Core Mesh status could not be assembled."},
        }), 503
    return jsonify({"status": "success", "data": snapshot})


@app.route(
    "/api/core-mesh/genesis/invent",
    methods=["POST"],
)
def core_mesh_genesis_invent_api():
    user_id, failure = _require_core_mesh_user()
    if failure:
        return failure
    operator_failure = _require_core_mesh_operator(user_id)
    if operator_failure:
        return operator_failure
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"status": "error", "error": {"code": "invalid_json", "message": "Send a JSON object containing demand."}}), 400
    try:
        result = propose_genesis_invention(body.get("demand", ""))
    except CoreMeshError as exc:
        return _core_mesh_error_response(exc)
    except Exception:
        app.logger.warning("Core Mesh Genesis proposal request failed.")
        return jsonify({"status": "error", "error": {"code": "genesis_proposal_failed", "message": "Genesis could not create the proposal."}}), 502
    return jsonify({"status": "success", "data": result}), 202


@app.route(
    "/api/core-mesh/mind/evolve",
    methods=["POST"],
)
def core_mesh_mind_evolve_api():
    user_id, failure = _require_core_mesh_user()
    if failure:
        return failure
    operator_failure = _require_core_mesh_operator(user_id)
    if operator_failure:
        return operator_failure
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"status": "error", "error": {"code": "invalid_json", "message": "Send a JSON object containing objective and tool_name."}}), 400
    try:
        result = propose_mind_evolution(
            body.get("objective", ""),
            body.get("tool_name", "offline_vault_fixture"),
        )
    except CoreMeshError as exc:
        return _core_mesh_error_response(exc)
    except Exception:
        app.logger.warning("Core Mesh Mind evolution request failed.")
        return jsonify({"status": "error", "error": {"code": "mind_evolution_failed", "message": "Infinite Mind could not create the proposal."}}), 502
    return jsonify({"status": "success", "data": result}), 202


# =========================================================
# LIVING BRAIN — USER-TAUGHT KNOWLEDGE
# =========================================================

@app.route("/v1/learn/unknown", methods=["POST"])
def learn_unknown_api():
    user_id, failure = _require_core_mesh_user()
    if failure:
        return failure
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"status": "error", "error": {"code": "invalid_json", "message": "Send topic and steps."}}), 400
    country = str(request.args.get("country") or body.get("country") or "KE").strip()[:80]
    language = str(request.args.get("lang") or body.get("language") or "").strip()[:20]
    try:
        saved = save_teaching(
            topic=body.get("topic", ""),
            user_id=user_id,
            steps=body.get("steps"),
            country=country,
            language=language,
            photo_hash=str(body.get("photo_hash") or "").strip(),
            consent_to_share=body.get("consent_to_share") is True,
            source_request=str(body.get("source_request") or ""),
        )
    except PermissionError as exc:
        return jsonify({"status": "blocked", "error": {"code": "worldwide_guardian_block", "message": str(exc)}}), 403
    except ValueError as exc:
        return jsonify({"status": "error", "error": {"code": "invalid_teaching_submission", "message": str(exc)}}), 400
    except OSError:
        app.logger.warning("Living Brain could not persist a teaching record.")
        return jsonify({"status": "error", "error": {"code": "learning_storage_unavailable", "message": "Knowledge could not be saved; no tool proposal was triggered."}}), 503

    result = {"saved": True, **saved, "genesis": {"status": "not_requested"}}
    if saved.get("genesis_needed") and saved.get("consent_to_share") is True:
        steps = body.get("steps") if isinstance(body.get("steps"), list) else []
        short_steps = "; ".join(str(step).strip()[:90] for step in steps[:3] if str(step).strip())
        demand = (
            f"Create a safe reviewable tool proposal for {str(body.get('topic') or '')[:140]}. "
            f"Country {saved.get('country')}; language {saved.get('language')}. "
            f"Unverified user notes: {short_steps[:170]}. Include a localized supplier directory, quote-required BOM, "
            "hardware guide, tests and safety gates. Await human merge."
        )[:495]
        try:
            proposal = propose_genesis_invention(demand, country=saved["country"], language=saved["language"])
            attached = attach_genesis_proposal(saved["topic_key"], proposal)
            result["genesis"] = {
                "status": attached.get("status", "await_merge"),
                "proposal": attached.get("proposal", {}),
                "human_approval_required": True,
                "automatic_execution": False,
                "automatic_merge": False,
            }
        except CoreMeshError as exc:
            result["genesis"] = {"status": "awaiting_genesis", "error_code": exc.code, "retry_allowed": True}
    elif not saved.get("consent_to_share"):
        result["genesis"] = {"status": "private_until_explicit_sharing_consent", "proposal_created": False}
    return jsonify({"status": "accepted", "data": result}), 202


@app.route("/v1/learn/known", methods=["GET"])
def learn_known_api():
    _, failure = _require_core_mesh_user()
    if failure:
        return failure
    records = list_known()
    return jsonify({"status": "success", "data": {"count": len(records), "known": records}})


@app.route("/v1/learn/known/<topic_key>/publish", methods=["POST"])
def publish_known_learning_api(topic_key: str):
    user_id, failure = _require_core_mesh_user()
    if failure:
        return failure
    operator_failure = _require_core_mesh_operator(user_id)
    if operator_failure:
        return operator_failure
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"status": "error", "error": {"code": "invalid_json", "message": "Send tool_name, endpoint and merge_commit."}}), 400
    try:
        result = publish_known(
            topic_key=topic_key,
            operator_id=user_id,
            tool_name=body.get("tool_name", ""),
            endpoint=body.get("endpoint", ""),
            merge_commit=body.get("merge_commit", ""),
        )
    except PermissionError as exc:
        return jsonify({"status": "error", "error": {"code": "learning_consent_required", "message": str(exc)}}), 403
    except ValueError as exc:
        return jsonify({"status": "error", "error": {"code": "learning_publish_rejected", "message": str(exc)}}), 422
    result["mind"] = {"status": "not_staged"}
    tool_name = str(result.get("tool_name") or "")
    try:
        objective = f"Review measured worldwide outcomes for {tool_name}; propose one evidence-gated improvement."
        proposal = propose_mind_evolution(objective, tool_name)
        attach_improvement_proposal(topic_key, proposal)
        result["mind"] = {
            "status": "await_merge",
            "proposal": {key: proposal[key] for key in ("status", "version", "tool_name", "selected_mutation", "await_merge_path") if key in proposal},
            "human_approval_required": True,
            "automatic_merge": False,
        }
    except CoreMeshError as exc:
        result["mind"] = {"status": "not_staged", "error_code": exc.code, "retry_allowed": True}
    except ValueError:
        result["mind"] = {"status": "not_staged", "error_code": "mind_proposal_rejected", "retry_allowed": True}
    return jsonify({"status": "success", "data": result}), 202


# =========================================================
# ROOT
# =========================================================

@app.route(
    "/",
    methods=["GET"],
)
def root():

    return jsonify({
        "status": "success",
        "service": "revelaai",
        "app": APP_NAME,
        "environment": ENVIRONMENT,
        "build_id": REVELAAI_BUILD_ID,
        "text_provider": (
            get_active_text_provider()
        ),
        "text_model": (
            get_active_text_model()
        ),
        "image_engine": (
            REVELAAI_IMAGE_ENGINE_VERSION
        ),
        "message": (
            "RevelaAI is live."
        ),
    })


# =========================================================
# CAPABILITIES
# =========================================================

@app.route(
    "/capabilities",
    methods=["GET"],
)
def capabilities():

    online_available = False

    try:

        from services.scraper import (
            get_live_research,
            is_realtime_query,
        )

        online_available = (
            callable(
                get_live_research
            )
            and callable(
                is_realtime_query
            )
        )

    except Exception:

        online_available = False

    pdf_available = False

    try:

        from ai.pdf_processor import (
            process_pdf,
        )

        pdf_available = callable(
            process_pdf
        )

    except Exception:

        pdf_available = False

    text_status = (
        get_revelaai_text_status()
    )

    active_text_provider = (
        get_active_text_provider()
    )

    active_text_model = (
        get_active_text_model()
    )

    gemini_info = {}

    providers = (
        text_status.get(
            "providers",
            {},
        )
    )

    if isinstance(
        providers,
        dict,
    ):

        possible_gemini_info = (
            providers.get(
                "gemini",
                {},
            )
        )

        if isinstance(
            possible_gemini_info,
            dict,
        ):

            gemini_info = (
                possible_gemini_info
            )

    return jsonify({
        "status": "success",
        "service": "revelaai",
        "build_id": REVELAAI_BUILD_ID,

        "capabilities": {

            # =================================================
            # TEXT
            # =================================================

            "text": {
                "enabled": (
                    active_text_provider
                    != "none"
                ),
                "provider": (
                    active_text_provider
                ),
                "model": active_text_model,
                "fallback_available": bool(
                    gemini_info.get(
                        "fallback_model"
                    )
                ),
                "providers": text_status,
            },

            # =================================================
            # IMAGE
            # =================================================

            "image_generation": {
                "enabled": bool(
                    configured_image_model()
                    or REVELAAI_IMAGE_ENGINE_VERSION
                ),
                "provider": "huggingface",
                "routing": {
                    "primary": "ai-client",
                    "planner": "image_prompt",
                    "text_aware": True,
                    "fallback": True,
                    "provider_aware": True,
                    "server_execution": True,
                },
                "engines": {
                    "raster": "huggingface",
                    "structured_vector": "svg",
                },
                "formats": [
                    "square",
                    "portrait",
                    "landscape",
                    "wide",
                    "story",
                    "banner",
                    "social_portrait",
                    "presentation",
                    "phone",
                ],
                "canva_style": {
                    "enabled": True,
                    "planner": "image_planner",
                    "structured_svg": True,
                    "editable_assets": True,
                },
            },

            # =================================================
            # RESEARCH
            # =================================================

            "online_research": {
                "enabled": True,
                "available": online_available,
                "provider": "services.scraper",
            },

            # =================================================
            # PDF
            # =================================================

            "pdf": {
                "enabled": True,
                "available": pdf_available,
                "processor": "PyMuPDF",
            },

            # =================================================
            # VOICE
            # =================================================

            "voice": {
                "enabled": bool(
                    hf_configured()
                ),
                "provider": "huggingface",
                "asr_model": os.getenv(
                    "HF_ASR_MODEL",
                    "openai/whisper-large-v3",
                ),
                "tts_model": os.getenv(
                    "HF_TTS_MODEL",
                    "hexgrad/Kokoro-82M",
                ),
                "tts_enabled": (
                    REVELAAI_ENABLE_HF_TTS
                ),
            },

            # =================================================
            # ECOSYSTEM
            # =================================================

            "ecosystem": {
                "enabled": True,
                "provider": "RevelaCode Backend",
                "gateway": "services.ai_service",
                "user_identity": "RevelaCode JWT",
                "domains": [
                    "theology",
                    "elimu",
                    "shamba",
                    "biashara",
                    "community",
                ],
            },
        },
    })


# =========================================================
# MAIN AI / IMAGE ENDPOINT
# =========================================================

@app.route(
    "/ai",
    methods=["POST"],
)
def ai_assistant():

    cleanup_generated_files()

    session_id = (
        get_session_id()
    )

    user_id = (
        resolve_revelacode_user_id()
    )

    # Smart memory is best-effort: only a valid JWT that also passes
    # RevelaCode's protected user-existence check can read/write memory.
    memory_user_oid = None
    if user_id:
        try:
            memory_user_oid, verified_user_id, memory_auth_error = _require_identity()
            if memory_auth_error or verified_user_id != user_id:
                memory_user_oid = None
                app.logger.info(
                    "Smart memory identity check did not pass; continuing chat without memory"
                )
        except Exception:
            memory_user_oid = None
            app.logger.warning(
                "Smart memory identity check failed; continuing chat without memory",
                exc_info=True,
            )

    session = get_session(
        session_id
    )

    try:

        # -------------------------------------------------
        # INPUT
        # -------------------------------------------------

        message = ""
        attachment_metadata = None
        raw_client_context: Any = None
        image_options: dict[str, Any] = {}

        uploaded = (
            request.files.get(
                "file"
            )
            or request.files.get(
                "attachment"
            )
        )

        if uploaded:

            brain_payload = {
                "hub": request.form.get("hub", "general"),
                "visionDescription": request.form.get("visionDescription", ""),
            }

            raw_client_context = (
                request.form.get(
                    "context",
                    "",
                )
                or ""
            )

            try:

                image_options = parse_image_options({
                    "aspect_ratio": request.form.get(
                        "aspect_ratio"
                    ),
                    "width": request.form.get(
                        "width"
                    ),
                    "height": request.form.get(
                        "height"
                    ),
                    "seed": request.form.get(
                        "seed"
                    ),
                })

            except ValueError as exc:

                return jsonify(
                    error_response(
                        "INVALID_IMAGE_OPTIONS",
                        str(exc),
                    )
                ), 400

            try:

                (
                    message,
                    attachment_metadata,
                ) = process_uploaded_document(
                    uploaded
                )

            except ValueError as exc:

                return jsonify(
                    error_response(
                        "INVALID_DOCUMENT",
                        str(exc),
                    )
                ), 400

            except RuntimeError as exc:

                return jsonify(
                    error_response(
                        "DOCUMENT_PROCESSING_FAILED",
                        str(exc),
                    )
                ), 502

        else:

            payload = (
                request.get_json(
                    silent=True
                )
                or {}
            )
            brain_payload = payload

            message = (
                payload.get(
                    "message",
                    "",
                )
                or ""
            ).strip()

            raw_client_context = (
                payload.get(
                    "context",
                    [],
                )
            )

            try:

                image_options = parse_image_options(
                    payload
                )

            except ValueError as exc:

                return jsonify(
                    error_response(
                        "INVALID_IMAGE_OPTIONS",
                        str(exc),
                    )
                ), 400

        if not message:

            return jsonify(
                error_response(
                    "EMPTY_MESSAGE",
                    "Message or file required.",
                )
            ), 400

        # -------------------------------------------------
        # CONVERSATION MEMORY
        # -------------------------------------------------

        (
            previous_context,
            memory_source,
        ) = resolve_conversation_context(
            session,
            raw_client_context,
        )

        # Shared global-brain context enriches the existing provider pipeline.
        # It shapes instructions and capability metadata; it adds no model.
        brain_context, interaction = build_global_context(
            message=message,
            hub=brain_payload.get("hub") or "auto",
            payload=brain_payload,
        )
        app.logger.info(
            "HUB INTELLIGENCE | requested=%s | hub_used=%s | hub_detected=%s",
            interaction.get("hubRequested"), interaction.get("hub"), interaction.get("hubDetected"),
        )
        previous_context = (previous_context + [brain_context])[-MAX_HISTORY:]

        if memory_user_oid is not None:
            personalization = _load_personalization_context(memory_user_oid)
            if personalization:
                previous_context = (
                    previous_context + [personalization]
                )[-MAX_HISTORY:]

        app.logger.info(
            "CONVERSATION MEMORY | "
            "request_id=%s | session=%s | "
            "source=%s | messages=%s",
            getattr(
                g,
                "request_id",
                None,
            ),
            session_id,
            memory_source,
            len(
                previous_context
            ),
        )

        # -------------------------------------------------
        # INTENT + CAPABILITY
        # -------------------------------------------------

        intent = classify_intent(
            message
        )

        capability = detect_capability(
            message,
            intent=intent,
        )

        image_request = (
            capability == "image_generation"
        )

        if image_request:

            intent = (
                "image_generation"
            )

        app.logger.info(
            "REQUEST ROUTING | "
            "request_id=%s | capability=%s | image=%s | "
            "intent=%s | build=%s | message=%s",
            getattr(
                g,
                "request_id",
                None,
            ),
            capability,
            image_request,
            intent,
            REVELAAI_BUILD_ID,
            message[:200],
        )

        lowered = (
            message.lower()
        )

        session[
            "topic"
        ] = intent

        # -------------------------------------------------
        # DIRECT IMAGE EXECUTION
        # -------------------------------------------------
        #
        # This path executes the image capability BEFORE the
        # text model sees the message.
        #
        # This is the primary protection against responses like:
        #
        #   "I can help generate an image, but..."
        #

        if image_request:

            image_result = (
                generate_image_response(
                    message,
                    image_options=image_options,
                )
            )

            save_image_conversation(
                session_id,
                session,
                message,
                success=bool(
                    image_result.get(
                        "ok",
                        False,
                    )
                ),
            )

            return (
                image_result["response"],
                image_result["status_code"],
            )

        # -------------------------------------------------
        # SAVE USER MESSAGE
        # -------------------------------------------------

        session[
            "messages"
        ].append({
            "role": "user",
            "content": message,
        })

        session[
            "messages"
        ] = session[
            "messages"
        ][-MAX_HISTORY:]

        # -------------------------------------------------
        # EXPERT MODULES
        # -------------------------------------------------

        expert_payload = None

        if (
            "law" in intent
            or "legal" in lowered
        ):

            expert_payload = (
                analyze_legal_query(
                    message
                )
            )

        elif (
            "medical" in intent
            or "medicine" in lowered
        ):

            expert_payload = (
                analyze_medical_query(
                    message
                )
            )

        # -------------------------------------------------
        # CENTRAL PIPELINE
        # -------------------------------------------------

        identity_reply = get_identity_answer(message, interaction.get("hub", "auto"))
        self_description_reply = get_self_description_answer(message)
        if identity_reply or self_description_reply:
            direct_reply = identity_reply or self_description_reply
            direct_intent = "identity" if identity_reply else "self_description"
            ai_result = {
                "response": direct_reply, "confidence": "high", "intent": direct_intent,
                "domain": interaction.get("hub", "auto"),
                "provider": "revelaai-manifest" if self_description_reply else "revelaai-hub-identity",
                "model": "agi-manifest-policy" if self_description_reply else "hub-identity-policy",
            }
        else:
            ai_result = process_message(
                message=message, context=previous_context, intent=intent,
                session_id=session_id, user_id=user_id,
                country=str(brain_payload.get("country") or "KE"),
                language=str(brain_payload.get("language") or ""),
            )

        # -------------------------------------------------
        # DEFENSIVE EXECUTABLE ACTION HANDLING
        # -------------------------------------------------

        action_result = execute_ai_action(
            ai_result,
            message=message,
            image_options=image_options,
            session_id=session_id,
            session=session,
        )

        if action_result is not None:

            return action_result

        # -------------------------------------------------
        # RESPONSE
        # -------------------------------------------------

        assistant_text = (
            ai_result.get(
                "response",
                "",
            )
            or ""
        ).strip()

        # Never mask a failed model call with canned deterministic chat text.
        if ai_result.get("error") or not assistant_text:
            app.logger.error(
                "MODEL RESPONSE UNAVAILABLE | hub_used=%s | request_id=%s",
                interaction.get("hub"), getattr(g, "request_id", None),
            )
            return jsonify(error_response(
                "MODEL_UNAVAILABLE",
                "RevelaAI's configured text model did not return a usable answer. Please try again shortly.",
            )), 503

        requested_hub = interaction.get("hubRequested", "auto")
        selected_hub = interaction.get("hub", "general")
        if requested_hub == "auto" and selected_hub != "auto":
            route_tag = f"[Auto → {HUB_LABELS.get(selected_hub, selected_hub.title())}]"
            if not assistant_text.startswith("[Auto →"):
                assistant_text = route_tag + "\n\n" + assistant_text

        # -------------------------------------------------
        # SAVE ASSISTANT RESPONSE
        # -------------------------------------------------

        session[
            "messages"
        ].append({
            "role": "assistant",
            "content": assistant_text,
        })

        if memory_user_oid is not None:
            _persist_turn(
                memory_user_oid,
                session_id,
                str(interaction.get("hub") or ai_result.get("domain") or intent or "general"),
                message,
                assistant_text,
            )

        save_session(
            session_id,
            session,
        )

        # -------------------------------------------------
        # JSON MODE
        # -------------------------------------------------

        wants_json = any(
            keyword in lowered
            for keyword in [
                "respond in json",
                "return json",
                "output json",
            ]
        )

        data = (
            extract_json(
                assistant_text
            )
            if wants_json
            else {
                "content": assistant_text
            }
        )

        if not isinstance(
            data,
            dict,
        ):

            data = {
                "content": assistant_text
            }

        if expert_payload:

            data[
                "expert_module"
            ] = expert_payload

        orchestrator_data = (
            ai_result.get(
                "orchestrator",
                {},
            )
        )

        if not isinstance(
            orchestrator_data,
            dict,
        ):

            orchestrator_data = {}

        core_mesh_data = orchestrator_data.get("core_mesh", {})
        if not isinstance(core_mesh_data, dict):
            core_mesh_data = {}
        else:
            core_mesh_data = {
                "mode": str(core_mesh_data.get("mode") or "advisory_only")[:40],
                "selected_core": str(core_mesh_data.get("selected_core") or "orchestrator")[:40],
                "route_reason": str(core_mesh_data.get("route_reason") or "")[:280],
                "domain": str(core_mesh_data.get("domain") or "general")[:80],
                "intent": str(core_mesh_data.get("intent") or "general")[:80],
                "mesh_status": str(core_mesh_data.get("mesh_status") or "not_probed")[:40],
                "cores": {
                    str(name)[:16]: {
                        "id": str(info.get("id") or "")[:40],
                        "status": str(info.get("status") or "unknown")[:40],
                        "reachable": info.get("reachable") if info.get("reachable") in (True, False, None) else None,
                        "version": str(info.get("version") or "")[:40],
                    }
                    for name, info in core_mesh_data.get("cores", {}).items()
                    if isinstance(name, str) and isinstance(info, dict)
                } if isinstance(core_mesh_data.get("cores"), dict) else {},
                "safety": {
                    "operation_executed": False,
                    "human_approval_required": True,
                    "automatic_merge": False,
                    "automatic_execution": False,
                },
            }

        online_data = (
            orchestrator_data.get(
                "online",
                {},
            )
        )

        if not isinstance(
            online_data,
            dict,
        ):

            online_data = {}

        sources = (
            online_data.get(
                "sources",
                [],
            )
        )

        if not isinstance(
            sources,
            list,
        ):

            sources = []

        raw_tool_execution = ai_result.get("tool_execution")
        if not isinstance(raw_tool_execution, dict):
            _orchestrator_for_tool = ai_result.get("orchestrator")
            raw_tool_execution = (
                _orchestrator_for_tool.get("usect_zero_tool")
                if isinstance(_orchestrator_for_tool, dict)
                else None
            )

        usect_tool_metadata = None
        if isinstance(raw_tool_execution, dict):
            usect_tool_metadata = {
                "name": str(
                    raw_tool_execution.get("name")
                    or raw_tool_execution.get("tool")
                    or "usect_zero"
                )[:80],
                "operation": str(raw_tool_execution.get("operation") or "unknown")[:40],
                "status": str(raw_tool_execution.get("status") or "unknown")[:40],
                "executed": bool(raw_tool_execution.get("executed", False)),
                "fallback": bool(raw_tool_execution.get("fallback", False)),
            }
            for _field in ("http_status", "error_code"):
                _value = raw_tool_execution.get(_field)
                if isinstance(_value, (int, str)) and not isinstance(_value, bool):
                    usect_tool_metadata[_field] = str(_value)[:100] if isinstance(_value, str) else _value
            _tool_message = raw_tool_execution.get("message")
            if isinstance(_tool_message, str) and _tool_message.strip():
                usect_tool_metadata["message"] = _tool_message.strip()[:240]

            # Only a deliberately small evidence summary crosses into the browser.
            _raw_result = raw_tool_execution.get("result")
            _allowed_result_fields = (
                "file_count", "language_counts", "git_head", "manifest_sha256",
                "read_only", "target", "proposal_id", "id", "status",
                "compiled", "artifact_count", "source_count",
            )
            if isinstance(_raw_result, dict):
                _summary = {}
                for _field in _allowed_result_fields:
                    if _field not in _raw_result:
                        continue
                    _value = _raw_result[_field]
                    if isinstance(_value, str):
                        _summary[_field] = _value[:240]
                    elif isinstance(_value, (int, float, bool)) or _value is None:
                        _summary[_field] = _value
                    elif isinstance(_value, dict):
                        _summary[_field] = {
                            str(_key)[:60]: _item
                            for _key, _item in list(_value.items())[:12]
                            if isinstance(_item, (str, int, float, bool)) or _item is None
                        }
                    elif isinstance(_value, list):
                        _summary[_field] = [
                            _item[:160] if isinstance(_item, str) else _item
                            for _item in _value[:6]
                            if isinstance(_item, (str, int, float, bool)) or _item is None
                        ]
                if _summary:
                    usect_tool_metadata["result_summary"] = _summary

        _unknown_learning = orchestrator_data.get("unknown_learning", {})
        if not isinstance(_unknown_learning, dict):
            _unknown_learning = {}
        _unknown_public = {
            "is_unknown": bool(_unknown_learning.get("is_unknown", False)),
            "topic": str(_unknown_learning.get("topic") or "")[:120],
            "wisdom_score": _unknown_learning.get("wisdom_score"),
            "threshold": _unknown_learning.get("threshold", 0.5),
            "next_action": str(_unknown_learning.get("next_action") or "use_existing_knowledge")[:40],
            "automatic_retries": False,
            "known_matches": _unknown_learning.get("known_matches", [])[:3] if isinstance(_unknown_learning.get("known_matches"), list) else [],
        }

        meta = {
            "unknown_learning": _unknown_public,
            "ai_model": ai_result.get(
                "model"
            ),

            "provider": ai_result.get(
                "provider",
                get_active_text_provider(),
            ),

            "memory": {
                "enabled": True,
                "type": "conversation",
                "source": memory_source,
                "context_messages": len(
                    previous_context
                ),
                "session_id": session_id,
                "server_session": (
                    "bounded_in_memory"
                ),
                "browser_restore_supported": True,
            },

            "intent": ai_result.get(
                "intent",
                intent,
            ),

            "domain": interaction.get("hub") or ai_result.get(
                "domain",
                "general",
            ),

            "hub": interaction.get("hub", "general"),
            "hub_used": interaction.get("hub", "general"),
            "hub_requested": interaction.get("hubRequested", "auto"),
            "hub_detected": interaction.get("hubDetected", "general"),

            "domains": ai_result.get(
                "domains",
                [],
            ),

            "emotion": ai_result.get(
                "emotion",
                "unknown",
            ),

            "interaction_tone": interaction["interactionTone"],
            "capabilities": interaction["capabilities"],

            "confidence": ai_result.get(
                "confidence",
                "medium",
            ),

            "online": online_data,

            "biashara": (
                orchestrator_data.get(
                    "biashara",
                    {},
                )
            ),

            "agriculture": (
                orchestrator_data.get(
                    "agriculture",
                    {},
                )
            ),

            "ecosystem": (
                orchestrator_data.get(
                    "ecosystem",
                    {},
                )
            ),

            "multimodal": (
                attachment_metadata
                or orchestrator_data.get(
                    "multimodal",
                    {},
                )
            ),

            "usect_zero_tool": usect_tool_metadata,

            "core_mesh": core_mesh_data,

            "build_id": REVELAAI_BUILD_ID,
        }

        return jsonify(
            enforce_base_schema(
                query=message,
                mode=intent,
                data=data,
                sources=sources,
                meta=meta,
            )
        )

    except Exception as exc:

        app.logger.exception(
            "AI request failed | request_id=%s | error=%s",
            getattr(
                g,
                "request_id",
                None,
            ),
            exc,
        )

        return jsonify(
            error_response(
                "SERVER_ERROR",
                (
                    "RevelaAI could not complete "
                    "the request."
                ),
            )
        ), 500


# =========================================================
# GENERATED IMAGE SERVING
# =========================================================

@app.route(
    "/ai/images/<filename>",
    methods=["GET"],
)
def serve_generated_image(
    filename,
):

    cleanup_generated_files()

    safe_filename = os.path.basename(
        filename
    )

    if safe_filename != filename:

        return jsonify({
            "status": "error",
            "error": {
                "code": "INVALID_FILENAME",
                "message": "Invalid image filename.",
            },
            "build_id": REVELAAI_BUILD_ID,
        }), 400

    filepath = os.path.join(
        IMAGE_DIR,
        safe_filename,
    )

    if not os.path.isfile(
        filepath
    ):

        return jsonify({
            "status": "error",
            "error": {
                "code": "IMAGE_NOT_FOUND",
                "message": "Image not found.",
            },
            "build_id": REVELAAI_BUILD_ID,
        }), 404

    extension = (
        Path(
            safe_filename
        ).suffix.lower()
    )

    mime_map = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".svg": "image/svg+xml",
    }

    mime_type = mime_map.get(
        extension
    )

    if mime_type is None:

        return jsonify({
            "status": "error",
            "error": {
                "code": "UNSUPPORTED_IMAGE_FORMAT",
                "message": (
                    "Unsupported generated image format."
                ),
            },
            "build_id": REVELAAI_BUILD_ID,
        }), 415

    response = send_file(
        filepath,
        mimetype=mime_type,
        max_age=300,
    )

    response.headers[
        "Cache-Control"
    ] = "public, max-age=300"

    return response


# =========================================================
# STREAMING ENDPOINT
# =========================================================

@app.route(
    "/ai/stream",
    methods=["POST"],
)
def ai_stream():

    payload = (
        request.get_json(
            silent=True
        )
        or {}
    )

    message = (
        payload.get(
            "message",
            "",
        )
        or ""
    ).strip()

    if not message:

        return jsonify(
            error_response(
                "EMPTY_MESSAGE",
                "Message required.",
            )
        ), 400

    try:

        image_options = parse_image_options(
            payload
        )

    except ValueError as exc:

        return jsonify(
            error_response(
                "INVALID_IMAGE_OPTIONS",
                str(exc),
            )
        ), 400

    session_id = (
        get_session_id()
    )

    user_id = (
        resolve_revelacode_user_id()
    )

    session = get_session(
        session_id
    )

    raw_client_context = (
        payload.get(
            "context",
            [],
        )
    )

    (
        previous_context,
        memory_source,
    ) = resolve_conversation_context(
        session,
        raw_client_context,
    )

    app.logger.info(
        "STREAM CONVERSATION MEMORY | "
        "request_id=%s | session=%s | "
        "source=%s | messages=%s",
        getattr(
            g,
            "request_id",
            None,
        ),
        session_id,
        memory_source,
        len(
            previous_context
        ),
    )

    intent = classify_intent(
        message
    )

    capability = detect_capability(
        message,
        intent=intent,
    )

    image_request = (
        capability == "image_generation"
    )

    if image_request:

        intent = (
            "image_generation"
        )

    app.logger.info(
        "STREAM ROUTING | "
        "request_id=%s | capability=%s | image=%s | "
        "intent=%s | build=%s | "
        "text_provider=%s | text_model=%s",
        getattr(
            g,
            "request_id",
            None,
        ),
        capability,
        image_request,
        intent,
        REVELAAI_BUILD_ID,
        get_active_text_provider(),
        get_active_text_model(),
    )

    session[
        "topic"
    ] = intent

    # =====================================================
    # IMAGE STREAMING
    # =====================================================

    if image_request:

        @stream_with_context
        def generate_image_stream():

            try:

                asset = generate_image_asset(
                    message,
                    image_options=image_options,
                )

                session[
                    "messages"
                ].append({
                    "role": "user",
                    "content": message,
                })

                session[
                    "messages"
                ].append({
                    "role": "assistant",
                    "content": (
                        "Generated a design based on the request: "
                        f"{message}"
                    ),
                })

                save_session(
                    session_id,
                    session,
                )

                image_payload = {
                    "success": True,
                    "mode": "image",
                    "query": message,

                    "data": {
                        "type": "image",
                        "format": asset[
                            "asset_type"
                        ],
                        "urls": [
                            asset[
                                "image_url"
                            ],
                        ],
                    },

                    "sources": [],

                    "meta": {
                        "provider": (
                            "huggingface"
                            if asset[
                                "asset_type"
                            ] == "png"
                            else "huggingface-svg"
                        ),

                        "model": (
                            configured_image_model()
                            if asset[
                                "asset_type"
                            ] == "png"
                            else None
                        ),

                        "build_id": REVELAAI_BUILD_ID,

                        "intent": "image_generation",

                        "image_engine": asset[
                            "image_plan"
                        ].get(
                            "engine"
                        ),

                        "engine_version": (
                            REVELAAI_IMAGE_ENGINE_VERSION
                        ),

                        "memory": {
                            "enabled": True,
                            "type": "conversation",
                            "source": memory_source,
                            "context_messages": len(
                                previous_context
                            ),
                            "session_id": session_id,
                        },

                        "design": asset[
                            "image_plan"
                        ],

                        "image": {
                            "width": asset[
                                "width"
                            ],
                            "height": asset[
                                "height"
                            ],
                            "aspect_ratio": asset[
                                "aspect_ratio"
                            ],
                            "seed": asset[
                                "seed"
                            ],
                        },

                        "multimodal": {
                            "type": "image",
                            "format": asset[
                                "asset_type"
                            ],
                            "editable": (
                                asset[
                                    "asset_type"
                                ] == "svg"
                            ),
                        },
                    },
                }

                yield (
                    "event: image\n"
                    "data: "
                    f"{json.dumps(image_payload)}\n\n"
                )

                yield (
                    "event: done\n"
                    "data: [DONE]\n\n"
                )

            except ValueError as exc:

                app.logger.exception(
                    "AI stream image request invalid | "
                    "request_id=%s | error=%s",
                    getattr(
                        g,
                        "request_id",
                        None,
                    ),
                    exc,
                )

                error_payload = {
                    "success": False,
                    "code": "IMAGE_REQUEST_INVALID",
                    "message": str(exc),
                }

                yield (
                    "event: error\n"
                    "data: "
                    f"{json.dumps(error_payload)}\n\n"
                )

            except Exception as exc:

                app.logger.exception(
                    "AI stream image failed | "
                    "request_id=%s | error=%s",
                    getattr(
                        g,
                        "request_id",
                        None,
                    ),
                    exc,
                )

                error_payload = {
                    "success": False,
                    "code": "IMAGE_GENERATION_FAILED",
                    "message": (
                        "Image generation failed."
                    ),
                }

                yield (
                    "event: error\n"
                    "data: "
                    f"{json.dumps(error_payload)}\n\n"
                )

        response = Response(
            generate_image_stream(),
            mimetype="text/event-stream",
        )

        response.headers[
            "Cache-Control"
        ] = "no-cache"

        response.headers[
            "X-Accel-Buffering"
        ] = "no"

        response.headers[
            "Connection"
        ] = "keep-alive"

        return response

    # =====================================================
    # NORMAL STREAMING
    # =====================================================

    session[
        "messages"
    ].append({
        "role": "user",
        "content": message,
    })

    session[
        "messages"
    ] = session[
        "messages"
    ][-MAX_HISTORY:]

    save_session(
        session_id,
        session,
    )

    @stream_with_context
    def generate():

        try:

            ai_result = process_message(
                message=message,
                context=previous_context,
                intent=intent,
                session_id=session_id,
                user_id=user_id,
            )

            # -------------------------------------------------
            # Defensive action handling
            # -------------------------------------------------

            if ai_result.get(
                "action_required",
                False,
            ):

                action = (
                    ai_result.get(
                        "action",
                        {},
                    )
                )

                action_type = str(
                    action.get(
                        "type",
                        "",
                    )
                    or ""
                ).strip().lower()

                if action_type == "image_generation":

                    asset = generate_image_asset(
                        message,
                        image_options=image_options,
                    )

                    session[
                        "messages"
                    ].append({
                        "role": "assistant",
                        "content": (
                            "Generated a design based on the request: "
                            f"{message}"
                        ),
                    })

                    save_session(
                        session_id,
                        session,
                    )

                    image_payload = {
                        "success": True,
                        "mode": "image",
                        "query": message,

                        "data": {
                            "type": "image",
                            "format": asset[
                                "asset_type"
                            ],
                            "urls": [
                                asset[
                                    "image_url"
                                ],
                            ],
                        },

                        "sources": [],

                        "meta": {
                            "provider": (
                                "huggingface"
                                if asset[
                                    "asset_type"
                                ] == "png"
                                else "huggingface-svg"
                            ),

                            "model": (
                                configured_image_model()
                                if asset[
                                    "asset_type"
                                ] == "png"
                                else None
                            ),

                            "build_id": REVELAAI_BUILD_ID,

                            "intent": "image_generation",

                            "image_engine": asset[
                                "image_plan"
                            ].get(
                                "engine"
                            ),

                            "engine_version": (
                                REVELAAI_IMAGE_ENGINE_VERSION
                            ),

                            "design": asset[
                                "image_plan"
                            ],

                            "image": {
                                "width": asset[
                                    "width"
                                ],
                                "height": asset[
                                    "height"
                                ],
                                "aspect_ratio": asset[
                                    "aspect_ratio"
                                ],
                                "seed": asset[
                                    "seed"
                                ],
                            },
                        },
                    }

                    yield (
                        "event: image\n"
                        "data: "
                        f"{json.dumps(image_payload)}\n\n"
                    )

                    yield (
                        "event: done\n"
                        "data: [DONE]\n\n"
                    )

                    return

                yield (
                    "event: error\n"
                    "data: "
                    + json.dumps({
                        "success": False,
                        "code": (
                            "UNSUPPORTED_AI_ACTION"
                        ),
                        "message": (
                            "RevelaAI recognized an unsupported "
                            "action."
                        ),
                    })
                    + "\n\n"
                )

                return

            response_text = (
                ai_result.get(
                    "response",
                    "",
                )
                or ""
            ).strip()

            if not response_text:

                response_text = (
                    "No response generated."
                )

            session[
                "messages"
            ].append({
                "role": "assistant",
                "content": response_text,
            })

            save_session(
                session_id,
                session,
            )

            yield (
                "event: message\n"
                f"data: {response_text}\n\n"
            )

            metadata = {
                "intent": (
                    ai_result.get(
                        "intent",
                        intent,
                    )
                ),

                "domain": (
                    ai_result.get(
                        "domain",
                        "general",
                    )
                ),

                "provider": (
                    ai_result.get(
                        "provider",
                        get_active_text_provider(),
                    )
                ),

                "model": (
                    ai_result.get(
                        "model",
                        get_active_text_model(),
                    )
                ),

                "capability": (
                    ai_result.get(
                        "capability",
                        "text",
                    )
                ),

                "build_id": REVELAAI_BUILD_ID,

                "memory": {
                    "enabled": True,
                    "type": "conversation",
                    "source": memory_source,
                    "context_messages": len(
                        previous_context
                    ),
                    "session_id": session_id,
                },
            }

            yield (
                "event: metadata\n"
                "data: "
                f"{json.dumps(metadata)}\n\n"
            )

            yield (
                "event: done\n"
                "data: [DONE]\n\n"
            )

        except Exception as exc:

            app.logger.exception(
                "AI stream failed | "
                "request_id=%s | error=%s",
                getattr(
                    g,
                    "request_id",
                    None,
                ),
                exc,
            )

            yield (
                "event: error\n"
                "data: "
                + json.dumps({
                    "success": False,
                    "code": "STREAM_REQUEST_FAILED",
                    "message": (
                        "RevelaAI could not complete "
                        "the request."
                    ),
                })
                + "\n\n"
            )

    response = Response(
        generate(),
        mimetype="text/event-stream",
    )

    response.headers[
        "Cache-Control"
    ] = "no-cache"

    response.headers[
        "X-Accel-Buffering"
    ] = "no"

    response.headers[
        "Connection"
    ] = "keep-alive"

    return response


# =========================================================
# VOICE HELPERS
# =========================================================

def audio_extension_for_mime(
    mime_type: str,
) -> str:

    mapping = {
        "audio/wav": ".wav",
        "audio/x-wav": ".wav",
        "audio/mpeg": ".mp3",
        "audio/mp3": ".mp3",
        "audio/ogg": ".ogg",
        "audio/opus": ".opus",
        "audio/flac": ".flac",
        "audio/x-flac": ".flac",
        "audio/webm": ".webm",
    }

    return mapping.get(
        str(
            mime_type or ""
        ).lower(),
        ".audio",
    )


# =========================================================
# VOICE ENDPOINT
# =========================================================

@app.route(
    "/voice",
    methods=["POST"],
)
def voice():

    cleanup_generated_files()

    uploaded = (
        request.files.get(
            "audio"
        )
    )

    if uploaded is None:

        return jsonify({
            "status": "error",
            "error": {
                "code": "AUDIO_REQUIRED",
                "message": (
                    "No audio file was provided."
                ),
            },
            "build_id": REVELAAI_BUILD_ID,
        }), 400

    audio_bytes = (
        uploaded.read()
    )

    if not audio_bytes:

        return jsonify({
            "status": "error",
            "error": {
                "code": "EMPTY_AUDIO",
                "message": (
                    "Uploaded audio is empty."
                ),
            },
            "build_id": REVELAAI_BUILD_ID,
        }), 400

    if len(
        audio_bytes
    ) > VOICE_MAX_BYTES:

        return jsonify({
            "status": "error",
            "error": {
                "code": "AUDIO_TOO_LARGE",
                "message": (
                    "Audio exceeds the maximum "
                    "allowed size."
                ),
            },
            "build_id": REVELAAI_BUILD_ID,
        }), 413

    # -----------------------------------------------------
    # TRANSCRIPTION
    # -----------------------------------------------------

    try:

        transcription = (
            transcribe_hf_audio(
                audio_bytes
            )
        )

    except Exception as exc:

        app.logger.exception(
            "Voice transcription failed | "
            "request_id=%s | error=%s",
            getattr(
                g,
                "request_id",
                None,
            ),
            exc,
        )

        return jsonify({
            "status": "error",
            "error": {
                "code": "VOICE_TRANSCRIPTION_FAILED",
                "message": (
                    "Voice transcription is "
                    "temporarily unavailable."
                ),
            },
            "build_id": REVELAAI_BUILD_ID,
        }), 502

    heard = str(
        transcription.get(
            "text",
            "",
        )
        or ""
    ).strip()

    if not heard:

        return jsonify({
            "status": "error",
            "error": {
                "code": "EMPTY_TRANSCRIPTION",
                "message": (
                    "No speech could be transcribed."
                ),
            },
            "build_id": REVELAAI_BUILD_ID,
        }), 400

    # -----------------------------------------------------
    # SESSION / USER
    # -----------------------------------------------------

    session_id = (
        get_session_id()
    )

    user_id = (
        resolve_revelacode_user_id()
    )

    session = get_session(
        session_id
    )

    previous_context = (
        build_server_context(
            session
        )
    )

    app.logger.info(
        "VOICE CONVERSATION MEMORY | "
        "request_id=%s | session=%s | messages=%s",
        getattr(
            g,
            "request_id",
            None,
        ),
        session_id,
        len(
            previous_context
        ),
    )

    # -----------------------------------------------------
    # INTENT + CAPABILITY
    # -----------------------------------------------------

    intent = classify_intent(
        heard
    )

    capability = detect_capability(
        heard,
        intent=intent,
    )

    if capability == "image_generation":

        intent = (
            "image_generation"
        )

        app.logger.info(
            "VOICE IMAGE ROUTING | "
            "request_id=%s | build=%s",
            getattr(
                g,
                "request_id",
                None,
            ),
            REVELAAI_BUILD_ID,
        )

    session[
        "topic"
    ] = intent

    # -----------------------------------------------------
    # VOICE IMAGE REQUEST
    # -----------------------------------------------------

    if capability == "image_generation":

        try:

            image_result = (
                generate_image_response(
                    heard
                )
            )

            if not image_result.get(
                "ok",
                False,
            ):

                return (
                    image_result[
                        "response"
                    ],
                    image_result[
                        "status_code"
                    ],
                )

            image_url = (
                image_result.get(
                    "image_url"
                )
            )

            image_asset_type = (
                image_result.get(
                    "asset_type",
                    "png",
                )
            )

            save_image_conversation(
                session_id,
                session,
                heard,
                success=True,
            )

            return jsonify({
                "status": "success",
                "heard": heard,
                "response": (
                    "Image generated successfully."
                ),
                "image_url": image_url,
                "asset_type": image_asset_type,
                "audio_url": None,

                "voice": {
                    "input": transcription,
                    "output": {
                        "available": False,
                        "reason": (
                            "image_generation_request"
                        ),
                    },
                },

                "meta": {
                    "intent": "image_generation",
                    "domain": "image",
                    "provider": (
                        "huggingface"
                        if image_asset_type == "png"
                        else "huggingface-svg"
                    ),
                    "model": (
                        configured_image_model()
                        if image_asset_type == "png"
                        else None
                    ),
                    "build_id": REVELAAI_BUILD_ID,
                    "image_engine": (
                        image_result.get(
                            "image_plan",
                            {},
                        ).get(
                            "engine"
                        )
                    ),
                    "memory": {
                        "enabled": True,
                        "type": "conversation",
                        "source": "server_session",
                        "context_messages": len(
                            previous_context
                        ),
                        "session_id": session_id,
                    },
                },
            })

        except Exception as exc:

            app.logger.exception(
                "Voice image generation failed | "
                "request_id=%s | error=%s",
                getattr(
                    g,
                    "request_id",
                    None,
                ),
                exc,
            )

            return jsonify({
                "status": "error",
                "error": {
                    "code": (
                        "VOICE_IMAGE_GENERATION_FAILED"
                    ),
                    "message": (
                        "Image generation is "
                        "temporarily unavailable."
                    ),
                },
                "build_id": REVELAAI_BUILD_ID,
            }), 502

    # -----------------------------------------------------
    # SAVE NORMAL VOICE USER MESSAGE
    # -----------------------------------------------------

    session[
        "messages"
    ].append({
        "role": "user",
        "content": heard,
    })

    session[
        "messages"
    ] = session[
        "messages"
    ][-MAX_HISTORY:]

    # -----------------------------------------------------
    # NORMAL AI PIPELINE
    # -----------------------------------------------------

    try:

        ai_result = process_message(
            message=heard,
            context=previous_context,
            intent=intent,
            session_id=session_id,
            user_id=user_id,
        )

    except Exception as exc:

        app.logger.exception(
            "Voice AI processing failed | "
            "request_id=%s | error=%s",
            getattr(
                g,
                "request_id",
                None,
            ),
            exc,
        )

        return jsonify({
            "status": "error",
            "error": {
                "code": "VOICE_AI_FAILED",
                "message": (
                    "RevelaAI could not process "
                    "the transcribed request."
                ),
            },
            "build_id": REVELAAI_BUILD_ID,
        }), 502

    # -----------------------------------------------------
    # DEFENSIVE ACTION HANDLING
    # -----------------------------------------------------

    if ai_result.get(
        "action_required",
        False,
    ):

        action = (
            ai_result.get(
                "action",
                {},
            )
        )

        action_type = str(
            action.get(
                "type",
                "",
            )
            or ""
        ).strip().lower()

        if action_type == "image_generation":

            try:

                image_result = (
                    generate_image_response(
                        heard
                    )
                )

                if image_result.get(
                    "ok",
                    False,
                ):

                    save_image_conversation(
                        session_id,
                        session,
                        heard,
                        success=True,
                    )

                return (
                    image_result["response"],
                    image_result["status_code"],
                )

            except Exception as exc:

                app.logger.exception(
                    "Voice executable image action failed | "
                    "request_id=%s | error=%s",
                    getattr(
                        g,
                        "request_id",
                        None,
                    ),
                    exc,
                )

                return jsonify({
                    "status": "error",
                    "error": {
                        "code": (
                            "VOICE_IMAGE_GENERATION_FAILED"
                        ),
                        "message": (
                            "Image generation failed."
                        ),
                    },
                    "build_id": REVELAAI_BUILD_ID,
                }), 502

        return jsonify({
            "status": "error",
            "error": {
                "code": "UNSUPPORTED_AI_ACTION",
                "message": (
                    "RevelaAI recognized an unsupported action."
                ),
            },
            "build_id": REVELAAI_BUILD_ID,
        }), 501

    response_text = str(
        ai_result.get(
            "response",
            "",
        )
        or ""
    ).strip()

    if not response_text:

        return jsonify({
            "status": "error",
            "error": {
                "code": "EMPTY_AI_RESPONSE",
                "message": (
                    "RevelaAI returned an empty response."
                ),
            },
            "build_id": REVELAAI_BUILD_ID,
        }), 502

    session[
        "messages"
    ].append({
        "role": "assistant",
        "content": response_text,
    })

    save_session(
        session_id,
        session,
    )

    # -----------------------------------------------------
    # TTS
    # -----------------------------------------------------

    if not REVELAAI_ENABLE_HF_TTS:

        return jsonify({
            "status": "success",
            "heard": heard,
            "response": response_text,
            "audio_url": None,

            "voice": {
                "input": transcription,
                "output": {
                    "available": False,
                    "reason": "tts_disabled",
                },
            },

            "meta": {
                "intent": ai_result.get(
                    "intent",
                    intent,
                ),
                "domain": ai_result.get(
                    "domain",
                    "general",
                ),
                "provider": ai_result.get(
                    "provider",
                    get_active_text_provider(),
                ),
                "model": ai_result.get(
                    "model",
                    get_active_text_model(),
                ),
                "build_id": REVELAAI_BUILD_ID,

                "memory": {
                    "enabled": True,
                    "type": "conversation",
                    "source": "server_session",
                    "context_messages": len(
                        previous_context
                    ),
                    "session_id": session_id,
                },
            },
        })

    try:

        audio_output = (
            generate_hf_speech(
                response_text
            )
        )

    except Exception as exc:

        app.logger.exception(
            "Voice synthesis failed | "
            "request_id=%s | error=%s",
            getattr(
                g,
                "request_id",
                None,
            ),
            exc,
        )

        return jsonify({
            "status": "success",
            "heard": heard,
            "response": response_text,
            "audio_url": None,

            "voice": {
                "input": transcription,
                "output": {
                    "available": False,
                    "reason": "tts_provider_failed",
                },
            },

            "meta": {
                "intent": ai_result.get(
                    "intent",
                    intent,
                ),
                "domain": ai_result.get(
                    "domain",
                    "general",
                ),
                "provider": ai_result.get(
                    "provider",
                    get_active_text_provider(),
                ),
                "model": ai_result.get(
                    "model",
                    get_active_text_model(),
                ),
                "build_id": REVELAAI_BUILD_ID,

                "memory": {
                    "enabled": True,
                    "type": "conversation",
                    "source": "server_session",
                    "context_messages": len(
                        previous_context
                    ),
                    "session_id": session_id,
                },
            },
        })

    if not audio_output:

        return jsonify({
            "status": "success",
            "heard": heard,
            "response": response_text,
            "audio_url": None,

            "voice": {
                "input": transcription,
                "output": {
                    "available": False,
                    "reason": "empty_tts_response",
                },
            },

            "meta": {
                "intent": ai_result.get(
                    "intent",
                    intent,
                ),
                "domain": ai_result.get(
                    "domain",
                    "general",
                ),
                "provider": ai_result.get(
                    "provider",
                    get_active_text_provider(),
                ),
                "model": ai_result.get(
                    "model",
                    get_active_text_model(),
                ),
                "build_id": REVELAAI_BUILD_ID,

                "memory": {
                    "enabled": True,
                    "type": "conversation",
                    "source": "server_session",
                    "context_messages": len(
                        previous_context
                    ),
                    "session_id": session_id,
                },
            },
        })

    mime_type = (
        os.getenv(
            "HF_TTS_MIME_TYPE",
            "audio/wav",
        ).strip()
        or "audio/wav"
    )

    extension = (
        audio_extension_for_mime(
            mime_type
        )
    )

    filename = (
        "revelaai_voice_"
        f"{uuid.uuid4().hex}"
        f"{extension}"
    )

    output_path = os.path.join(
        AUDIO_DIR,
        filename,
    )

    try:

        with open(
            output_path,
            "wb",
        ) as handle:

            handle.write(
                audio_output
            )

    except Exception as exc:

        app.logger.exception(
            "Voice audio could not be saved | "
            "request_id=%s | error=%s",
            getattr(
                g,
                "request_id",
                None,
            ),
            exc,
        )

        return jsonify({
            "status": "success",
            "heard": heard,
            "response": response_text,
            "audio_url": None,

            "voice": {
                "input": transcription,
                "output": {
                    "available": False,
                    "reason": "audio_save_failed",
                },
            },

            "meta": {
                "intent": ai_result.get(
                    "intent",
                    intent,
                ),
                "domain": ai_result.get(
                    "domain",
                    "general",
                ),
                "provider": ai_result.get(
                    "provider",
                    get_active_text_provider(),
                ),
                "model": ai_result.get(
                    "model",
                    get_active_text_model(),
                ),
                "build_id": REVELAAI_BUILD_ID,

                "memory": {
                    "enabled": True,
                    "type": "conversation",
                    "source": "server_session",
                    "context_messages": len(
                        previous_context
                    ),
                    "session_id": session_id,
                },
            },
        })

    audio_url = (
        request.host_url.rstrip("/")
        + "/voice/audio/"
        + filename
    )

    return jsonify({
        "status": "success",

        "heard": heard,

        "response": response_text,

        "audio_url": audio_url,

        "voice": {
            "input": {
                "provider": "huggingface",
                "model": transcription.get(
                    "model"
                ),
            },

            "output": {
                "provider": "huggingface",
                "model": os.getenv(
                    "HF_TTS_MODEL",
                    "hexgrad/Kokoro-82M",
                ),
                "mime_type": mime_type,
                "available": True,
            },
        },

        "meta": {
            "intent": ai_result.get(
                "intent",
                intent,
            ),

            "domain": ai_result.get(
                "domain",
                "general",
            ),

            "provider": ai_result.get(
                "provider",
                get_active_text_provider(),
            ),

            "model": ai_result.get(
                "model",
                get_active_text_model(),
            ),

            "build_id": REVELAAI_BUILD_ID,

            "memory": {
                "enabled": True,
                "type": "conversation",
                "source": "server_session",
                "context_messages": len(
                    previous_context
                ),
                "session_id": session_id,
            },
        },
    })


# =========================================================
# SERVE GENERATED AUDIO
# =========================================================

@app.route(
    "/voice/audio/<filename>",
    methods=["GET"],
)
def serve_audio(
    filename,
):

    cleanup_generated_files()

    safe_filename = os.path.basename(
        filename
    )

    if safe_filename != filename:

        return jsonify({
            "status": "error",
            "error": {
                "code": "INVALID_FILENAME",
                "message": (
                    "Invalid audio filename."
                ),
            },
            "build_id": REVELAAI_BUILD_ID,
        }), 400

    filepath = os.path.join(
        AUDIO_DIR,
        safe_filename,
    )

    if not os.path.isfile(
        filepath
    ):

        return jsonify({
            "status": "error",
            "error": {
                "code": "AUDIO_NOT_FOUND",
                "message": "Audio not found.",
            },
            "build_id": REVELAAI_BUILD_ID,
        }), 404

    extension = (
        Path(
            safe_filename
        ).suffix.lower()
    )

    mime_map = {
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
        ".ogg": "audio/ogg",
        ".opus": "audio/opus",
        ".flac": "audio/flac",
        ".webm": "audio/webm",
    }

    mime_type = mime_map.get(
        extension,
        "application/octet-stream",
    )

    response = send_file(
        filepath,
        mimetype=mime_type,
        max_age=300,
    )

    response.headers[
        "Cache-Control"
    ] = "public, max-age=300"

    return response


# =========================================================
# HEALTH
# =========================================================

@app.route(
    "/health",
    methods=["GET"],
)
def health():

    online_available = False

    try:

        from services.scraper import (
            get_live_research,
            is_realtime_query,
        )

        online_available = (
            callable(
                get_live_research
            )
            and callable(
                is_realtime_query
            )
        )

    except Exception:

        online_available = False

    pdf_available = False

    try:

        from ai.pdf_processor import (
            process_pdf,
        )

        pdf_available = callable(
            process_pdf
        )

    except Exception:

        pdf_available = False

    text_status = (
        get_revelaai_text_status()
    )

    active_text_provider = (
        get_active_text_provider()
    )

    active_text_model = (
        get_active_text_model()
    )

    return jsonify({
        "status": "ok",
        "service": "revelaai",
        "environment": ENVIRONMENT,

        "build": {
            "id": REVELAAI_BUILD_ID,

            "image_routing": (
                "ai-client-managed"
            ),

            "image_engine": (
                REVELAAI_IMAGE_ENGINE_VERSION
            ),

            "conversation_memory": (
                "client-context-plus-session"
            ),

            "capability_routing": (
                "server-authoritative"
            ),
        },

        "providers": {

            # =================================================
            # TEXT
            # =================================================

            "text": {
                "provider": (
                    active_text_provider
                ),

                "configured": (
                    active_text_provider
                    != "none"
                ),

                "model": (
                    active_text_model
                ),

                "status": text_status,
            },

            # =================================================
            # IMAGE
            # =================================================

            "image": {
                "provider": "huggingface",

                "configured": (
                    hf_configured()
                    and bool(
                        configured_image_model()
                    )
                ),

                "primary_model": (
                    configured_image_model()
                ),

                "routing": {
                    "owner": "ai_client",
                    "planner": "image_prompt",
                    "text_aware": True,
                    "fallback": True,
                    "provider_aware": True,
                    "server_execution": True,
                },

                "structured_svg": True,
            },

            # =================================================
            # VOICE
            # =================================================

            "voice": {
                "provider": "huggingface",

                "configured": (
                    hf_configured()
                ),

                "asr_model": os.getenv(
                    "HF_ASR_MODEL",
                    "openai/whisper-large-v3",
                ),

                "tts_model": os.getenv(
                    "HF_TTS_MODEL",
                    "hexgrad/Kokoro-82M",
                ),

                "tts_enabled": (
                    REVELAAI_ENABLE_HF_TTS
                ),
            },
        },

        "online_research": {
            "available": online_available,
        },

        "pdf": {
            "available": pdf_available,
        },

        "ecosystem": {
            "enabled": True,
            "gateway": "services.ai_service",
            "authenticated_user_bridge": (
                "RevelaCode JWT -> user_id"
            ),
            "domains": [
                "theology",
                "elimu",
                "shamba",
                "biashara",
                "community",
            ],
        },

        "features_loaded": len(
            FEATURES
        ),

        "session_memory": {
            "active_sessions": len(
                SESSION_MEMORY
            ),
            "max_sessions": MAX_SESSIONS,
            "ttl_seconds": SESSION_TTL_SECONDS,
            "max_history_messages": MAX_HISTORY,
            "server_storage": "in_memory",
            "browser_context_supported": True,
        },
    })


# =========================================================
# READINESS
# =========================================================

@app.route(
    "/ready",
    methods=["GET"],
)
def ready():

    text_provider = (
        get_active_text_provider()
    )

    text_model = (
        get_active_text_model()
    )

    checks: dict[str, Any] = {}

    # -----------------------------------------------------
    # TEXT IS THE CORE REQUIRED SERVICE
    # -----------------------------------------------------

    checks[
        "text_provider"
    ] = (
        text_provider
        != "none"
    )

    checks[
        "text_model"
    ] = bool(
        text_model
    )

    # -----------------------------------------------------
    # HUGGING FACE MULTIMODAL
    #
    # Optional for core text readiness.
    # -----------------------------------------------------

    checks[
        "huggingface"
    ] = hf_configured()

    checks[
        "image_model"
    ] = bool(
        configured_image_model()
    )

    # -----------------------------------------------------
    # ONLINE RESEARCH
    # -----------------------------------------------------

    try:

        from services.scraper import (
            get_live_research,
            is_realtime_query,
        )

        checks[
            "online_research"
        ] = (
            callable(
                get_live_research
            )
            and callable(
                is_realtime_query
            )
        )

    except Exception:

        checks[
            "online_research"
        ] = False

    # -----------------------------------------------------
    # PDF
    # -----------------------------------------------------

    try:

        from ai.pdf_processor import (
            process_pdf,
        )

        checks[
            "pdf_processor"
        ] = callable(
            process_pdf
        )

    except Exception:

        checks[
            "pdf_processor"
        ] = False

    # -----------------------------------------------------
    # CORE READINESS
    #
    # Gemini text must be available.
    # Optional multimodal services do not prevent core text
    # readiness.
    # -----------------------------------------------------

    core_ready = (
        bool(
            checks[
                "text_provider"
            ]
        )
        and bool(
            checks[
                "text_model"
            ]
        )
    )

    return jsonify({
        "status": (
            "ready"
            if core_ready
            else "degraded"
        ),

        "service": "revelaai",

        "build_id": REVELAAI_BUILD_ID,

        "text": {
            "provider": text_provider,
            "model": text_model,
        },

        "checks": checks,

        "core": {
            "ready": core_ready,
            "text_required": True,
            "huggingface_multimodal_optional": True,
        },
    }), (
        200
        if core_ready
        else 503
    )


# =========================================================
# BLUEPRINT REGISTRATION
# =========================================================

try:

    app.register_blueprint(
        vision_bp,
        url_prefix="/api/vision",
    )

except Exception as exc:

    app.logger.warning(
        "vision_bp registration failed | error=%s",
        exc,
    )


try:

    app.register_blueprint(
        chat_bp,
        url_prefix="/api/chat",
    )

except Exception as exc:

    app.logger.warning(
        "chat_bp registration failed | error=%s",
        exc,
    )


try:

    app.register_blueprint(
        living_brain_bp,
        url_prefix="/api/revelaai/v2",
    )

except Exception as exc:

    app.logger.warning(
        "living_brain_bp registration failed | error=%s",
        exc,
    )


try:

    app.register_blueprint(
        explain_bp
    )

except Exception as exc:

    app.logger.warning(
        "explain_bp registration failed | error=%s",
        exc,
    )


try:

    app.register_blueprint(
        memory_bp,
        url_prefix="/api/memory",
    )

except Exception as exc:

    app.logger.warning(
        "memory_bp registration failed | error=%s",
        exc,
    )


try:

    app.register_blueprint(
        research_bp
    )

except Exception as exc:

    app.logger.warning(
        "research_bp registration failed | error=%s",
        exc,
    )


try:

    app.register_blueprint(
        users_bp
    )

except Exception as exc:

    app.logger.warning(
        "users_bp registration failed | error=%s",
        exc,
    )


try:

    app.register_blueprint(
        whatsapp_bp
    )

except Exception as exc:

    app.logger.warning(
        "whatsapp_bp registration failed | error=%s",
        exc,
    )


try:

    app.register_blueprint(
        hub_bp
    )

except Exception as exc:

    app.logger.warning(
        "hub_bp registration failed | error=%s",
        exc,
    )


try:

    app.register_blueprint(
        meta_engineer_bp,
        url_prefix="/api/meta-engineer",
    )

except Exception as exc:

    app.logger.warning(
        "meta_engineer_bp registration failed | error=%s",
        exc,
    )


try:

    app.register_blueprint(
        usect_zero_bp,
        url_prefix="/api/usect-zero",
    )

except Exception as exc:

    app.logger.warning(
        "usect_zero_bp registration failed | error=%s",
        exc,
    )


try:

    app.register_blueprint(
        sci_router,
        url_prefix="/api/sci",
    )

except Exception as exc:

    app.logger.warning(
        "sci_router registration failed | error=%s",
        exc,
    )


try:

    app.register_blueprint(
        agi_router,
        url_prefix="/api/agi",
    )

except Exception as exc:

    app.logger.warning(
        "agi_router registration failed | error=%s",
        exc,
    )



try:

    app.register_blueprint(
        automation_fabric_bp,
        url_prefix="/api/automation-fabric",
    )

except Exception as exc:

    app.logger.warning(
        "automation_fabric_bp registration failed | error=%s",
        exc,
    )


# =========================================================
# DEVELOPMENT ENTRYPOINT ONLY
# =========================================================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=PORT,
        debug=(
            ENVIRONMENT
            == "development"
        ),
    )
