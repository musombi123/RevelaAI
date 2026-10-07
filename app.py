"""
RevelaAI Production Application

Architecture:

    RevelaCode Frontend
          |
          v
      RevelaAI API
          |
    +-----+--------------------+
    |                          |
    v                          v
 Orchestrator              AI Client
    |                          |
    |                          +--> Hugging Face / GPT-OSS
    |                          +--> Hugging Face / FLUX
    |                          +--> Hugging Face / Whisper
    |                          +--> Hugging Face / TTS
    |
    +--> RevelaCode Backend gateway
    +--> Online research
    +--> Biashara intelligence
    +--> Shamba intelligence
    +--> PDF processing

Production principles:

    - Never expose provider credentials.
    - Do not use Flask development server in production.
    - Bound request/upload sizes.
    - Use structured JSON errors.
    - Keep session state bounded.
    - Use trusted CORS origins.
    - Protect generated-file paths.
    - Do not expose database testing endpoints.
    - Keep image/audio files temporary.
    - Image requests must never silently fall through to text AI.
    - Conversation intent changes must never erase conversation memory.
    - Browser-provided conversation context may rehydrate server memory.
    - Image model/provider routing is owned by ai.ai_client.py.
    - Image planning is owned by ai.image_planner.py.
    - Structured designs are rendered through ai.svg_designer.py.
"""

from __future__ import annotations

import importlib
import inspect
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
    )
    .strip()
)

JWT_ALGORITHM = "HS256"


def resolve_revelacode_user_id() -> str | None:
    """
    Resolve the authenticated RevelaCode user from the
    Authorization Bearer JWT.

    The JWT is only used to establish identity.

    Actual platform data is retrieved through the
    RevelaCode AI Gateway.
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
    hf_configured,
    transcribe_hf_audio,
)

from ai.intent_router import (
    classify_intent,
)

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

from whatsapp_webhook import (
    whatsapp_bp,
)


# =========================================================
# APPLICATION CONFIGURATION
# =========================================================

BASE_DIR = (
    Path(
        __file__
    ).resolve().parent
)


APP_NAME = (
    os.getenv(
        "APP_NAME",
        "RevelaAI",
    )
    .strip()
    or "RevelaAI"
)


ENVIRONMENT = (
    os.getenv(
        "ENVIRONMENT",
        "production",
    )
    .strip()
    .lower()
    or "production"
)


PORT = int(
    os.getenv(
        "PORT",
        "5000",
    )
)


MAX_CONTENT_LENGTH = int(
    os.getenv(
        "MAX_CONTENT_LENGTH",
        str(
            25 * 1024 * 1024
        ),
    )
)


# ---------------------------------------------------------
# Conversation memory
# ---------------------------------------------------------
#
# Keep the browser and backend context windows aligned.
#
# The frontend currently sends the last 12 messages.
#
MAX_HISTORY = int(
    os.getenv(
        "MAX_HISTORY",
        "12",
    )
)


MAX_SESSIONS = int(
    os.getenv(
        "MAX_SESSIONS",
        "500",
    )
)


SESSION_TTL_SECONDS = int(
    os.getenv(
        "SESSION_TTL_SECONDS",
        str(
            60 * 60
        ),
    )
)


DOCUMENT_MAX_MODEL_CHARS = int(
    os.getenv(
        "DOCUMENT_MAX_MODEL_CHARS",
        "90000",
    )
)


VOICE_MAX_BYTES = int(
    os.getenv(
        "VOICE_MAX_BYTES",
        str(
            10 * 1024 * 1024
        ),
    )
)


IMAGE_RETENTION_SECONDS = int(
    os.getenv(
        "IMAGE_RETENTION_SECONDS",
        str(
            60 * 60
        ),
    )
)


AUDIO_RETENTION_SECONDS = int(
    os.getenv(
        "AUDIO_RETENTION_SECONDS",
        str(
            60 * 60
        ),
    )
)


# =========================================================
# BUILD / RELEASE IDENTITY
# =========================================================

REVELAAI_BUILD_ID = (
    os.getenv(
        "REVELAAI_BUILD_ID",
        "canva-image-v1-memory-v1",
    )
    .strip()
    or "canva-image-v1-memory-v1"
)


# =========================================================
# FEATURE FLAGS
# =========================================================

REVELAAI_ENABLE_HF_TTS = (
    os.getenv(
        "REVELAAI_ENABLE_HF_TTS",
        "false",
    )
    .strip()
    .lower()
    in {
        "1",
        "true",
        "yes",
        "on",
    }
)


# =========================================================
# IMAGE ENGINE CONFIGURATION
# =========================================================
#
# The image model/provider/dimensions/inference parameters
# are owned by ai.ai_client.py.
#
# This application layer only exposes the engine identity and
# does not duplicate model routing defaults.
#

REVELAAI_IMAGE_ENGINE_VERSION = (
    os.getenv(
        "REVELAAI_IMAGE_ENGINE_VERSION",
        "canva-studio-v1",
    )
    .strip()
    or "canva-studio-v1"
)


# Read-only reporting helper. Generation itself remains owned
# by ai.ai_client.py.
def configured_image_model() -> str:
    return (
        os.getenv(
            "HF_IMAGE_MODEL",
            "black-forest-labs/FLUX.1-dev",
        )
        .strip()
        or "black-forest-labs/FLUX.1-dev"
    )


# =========================================================
# LOGGING
# =========================================================

LOG_LEVEL = (
    os.getenv(
        "LOG_LEVEL",
        "INFO",
    )
    .strip()
    .upper()
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
    __name__
)

app.config.update({
    "MAX_CONTENT_LENGTH": MAX_CONTENT_LENGTH,
    "PROPAGATE_EXCEPTIONS": False,
})


# =========================================================
# PROXY SUPPORT
# =========================================================

# Render sits behind a proxy/load balancer.
# ProxyFix allows request.host_url and scheme information
# to correctly reflect the public HTTPS URL.

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
    Read trusted frontend origins from the environment.
    """

    raw = (
        os.getenv(
            "CORS_ORIGINS",
            (
                "http://localhost:5173,"
                "http://127.0.0.1:5173,"
                "https://revelacode-frontend.onrender.com,"
                "https://localhost"
            ),
        )
        or ""
    )

    origins = []

    for item in raw.split(","):

        origin = item.strip()

        if origin:

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
    """
    Give every request a correlation ID.
    """

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
    """
    Production catch-all.

    The complete exception is logged server-side.
    Clients receive a safe message rather than a traceback.
    """

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
# BOUNDED SESSION MEMORY
# =========================================================

SESSION_MEMORY: OrderedDict[
    str,
    dict[str, Any]
] = OrderedDict()


SESSION_LOCK = Lock()


def _prune_session_memory() -> None:
    """
    Remove expired sessions and enforce the maximum count.
    """

    now = time.time()

    expired = []

    for session_id, session in (
        SESSION_MEMORY.items()
    ):

        updated_at = float(
            session.get(
                "updated_at",
                now,
            )
        )

        if (
            now - updated_at
            > SESSION_TTL_SECONDS
        ):

            expired.append(
                session_id
            )

    for session_id in expired:

        SESSION_MEMORY.pop(
            session_id,
            None,
        )

    while len(
        SESSION_MEMORY
    ) > MAX_SESSIONS:

        SESSION_MEMORY.popitem(
            last=False
        )


def get_session_id() -> str:
    """
    Resolve the conversation identifier.

    Preferred:
        X-Session-ID

    Fallback:
        secure browser cookie

    Final fallback:
        short-lived generated ID
    """

    header_id = (
        request.headers.get(
            "X-Session-ID"
        )
        or ""
    ).strip()

    if header_id:

        session_id = (
            header_id[:128]
        )

    else:

        cookie_id = (
            request.cookies.get(
                "revelaai_session"
            )
            or ""
        ).strip()

        if cookie_id:

            session_id = (
                cookie_id[:128]
            )

        else:

            session_id = (
                uuid.uuid4().hex
            )

    g.revelaai_session_id = (
        session_id
    )

    return session_id


def get_session(
    session_id: str,
) -> dict[str, Any]:
    """
    Retrieve or initialize bounded session state.
    """

    with SESSION_LOCK:

        _prune_session_memory()

        existing = (
            SESSION_MEMORY.get(
                session_id
            )
        )

        if existing is None:

            session = {
                "topic": None,
                "messages": [],
                "updated_at": time.time(),
            }

            SESSION_MEMORY[
                session_id
            ] = session

            return session

        existing[
            "updated_at"
        ] = time.time()

        SESSION_MEMORY.move_to_end(
            session_id
        )

        return existing


def save_session(
    session_id: str,
    session: dict[str, Any],
) -> None:

    session[
        "messages"
    ] = list(
        session.get(
            "messages",
            [],
        )
    )[-MAX_HISTORY:]

    session[
        "updated_at"
    ] = time.time()

    with SESSION_LOCK:

        SESSION_MEMORY[
            session_id
        ] = session

        SESSION_MEMORY.move_to_end(
            session_id
        )

        _prune_session_memory()


# =========================================================
# CLIENT CONVERSATION CONTEXT
# =========================================================

def normalize_client_context(
    raw_context: Any,
) -> list[dict[str, str]]:
    """
    Normalize conversation context supplied by the frontend.

    Supported structured input:

        [
            {"role": "user", "content": "..."},
            {"role": "assistant", "content": "..."}
        ]

    Backward compatibility is also supported for the older
    frontend format:

        User: ...
        Assistant: ...
    """

    # -----------------------------------------------------
    # STRUCTURED CONTEXT
    # -----------------------------------------------------

    if isinstance(
        raw_context,
        list,
    ):

        normalized: list[
            dict[str, str]
        ] = []

        for item in raw_context:

            if not isinstance(
                item,
                dict,
            ):
                continue

            role = str(
                item.get(
                    "role",
                    "user",
                )
                or "user"
            ).strip().lower()

            if role not in {
                "user",
                "assistant",
            }:

                role = "user"

            content = str(
                item.get(
                    "content",
                    "",
                )
                or ""
            ).strip()

            if not content:
                continue

            normalized.append({
                "role": role,
                "content": content,
            })

        return normalized[
            -MAX_HISTORY:
        ]

    # -----------------------------------------------------
    # LEGACY TEXT CONTEXT
    # -----------------------------------------------------

    if isinstance(
        raw_context,
        str,
    ):

        context_text = (
            raw_context.strip()
        )

        if not context_text:
            return []

        normalized: list[
            dict[str, str]
        ] = []

        for line in (
            context_text.splitlines()
        ):

            line = line.strip()

            if not line:
                continue

            if line.startswith(
                "User:"
            ):

                content = (
                    line[
                        len("User:"):
                    ].strip()
                )

                if content:

                    normalized.append({
                        "role": "user",
                        "content": content,
                    })

            elif line.startswith(
                "Assistant:"
            ):

                content = (
                    line[
                        len("Assistant:"):
                    ].strip()
                )

                if content:

                    normalized.append({
                        "role": "assistant",
                        "content": content,
                    })

        return normalized[
            -MAX_HISTORY:
        ]

    return []


def build_server_context(
    session: dict[str, Any],
) -> list[dict[str, str]]:
    """
    Build normalized conversation context from the server
    session.
    """

    messages = (
        session.get(
            "messages",
            [],
        )
    )

    if not isinstance(
        messages,
        list,
    ):

        return []

    normalized: list[
        dict[str, str]
    ] = []

    for item in messages:

        if not isinstance(
            item,
            dict,
        ):
            continue

        role = str(
            item.get(
                "role",
                "user",
            )
            or "user"
        ).strip().lower()

        if role not in {
            "user",
            "assistant",
        }:

            role = "user"

        content = str(
            item.get(
                "content",
                "",
            )
            or ""
        ).strip()

        if not content:
            continue

        normalized.append({
            "role": role,
            "content": content,
        })

    return normalized[
        -MAX_HISTORY:
    ]


def resolve_conversation_context(
    session: dict[str, Any],
    client_context: Any = None,
) -> tuple[
    list[dict[str, str]],
    str,
]:
    """
    Resolve the best available conversation memory.

    Priority:

        1. Client/browser context
        2. Server session context

    When client context exists, it is also used to
    rehydrate the server-side session so conversation
    continuity survives ordinary server-session loss.
    """

    normalized_client = (
        normalize_client_context(
            client_context
        )
    )

    if normalized_client:

        session[
            "messages"
        ] = list(
            normalized_client[
                -MAX_HISTORY:
            ]
        )

        return (
            normalized_client[
                -MAX_HISTORY:
            ],
            "client_context",
        )

    server_context = (
        build_server_context(
            session
        )
    )

    return (
        server_context,
        "server_session",
    )


# =========================================================
# SESSION COOKIE
# =========================================================

@app.after_request
def set_session_cookie(
    response,
):
    """
    Set a session cookie for same-origin deployments.

    The frontend can also explicitly use X-Session-ID.
    """

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


# =========================================================
# GENERATED FILE DIRECTORIES
# =========================================================

DEFAULT_IMAGE_DIR = os.path.join(
    tempfile.gettempdir(),
    "revelaai_images",
)


DEFAULT_AUDIO_DIR = os.path.join(
    tempfile.gettempdir(),
    "revelaai_audio",
)


IMAGE_DIR = (
    os.getenv(
        "REVELAAI_IMAGE_DIR",
        DEFAULT_IMAGE_DIR,
    ).strip()
    or DEFAULT_IMAGE_DIR
)


AUDIO_DIR = (
    os.getenv(
        "REVELAAI_AUDIO_DIR",
        DEFAULT_AUDIO_DIR,
    ).strip()
    or DEFAULT_AUDIO_DIR
)


os.makedirs(
    IMAGE_DIR,
    exist_ok=True,
)


os.makedirs(
    AUDIO_DIR,
    exist_ok=True,
)


# =========================================================
# FILE CLEANUP
# =========================================================

def cleanup_generated_files() -> None:
    """
    Remove old generated image/audio files.

    Render's normal filesystem is temporary, so this is
    intentionally lightweight.
    """

    now = time.time()

    directories = [
        (
            IMAGE_DIR,
            IMAGE_RETENTION_SECONDS,
        ),
        (
            AUDIO_DIR,
            AUDIO_RETENTION_SECONDS,
        ),
    ]

    for directory, retention in (
        directories
    ):

        try:

            for path in Path(
                directory
            ).iterdir():

                if not path.is_file():
                    continue

                try:

                    age = (
                        now
                        - path.stat().st_mtime
                    )

                    if age > retention:

                        path.unlink(
                            missing_ok=True
                        )

                except (
                    OSError,
                    ValueError,
                ):

                    continue

        except OSError:

            continue


# =========================================================
# DYNAMIC FEATURE LOADING
# =========================================================

FEATURES_DIR = (
    BASE_DIR
    / "features"
)


def load_features():
    """
    Dynamically load optional generated feature classes.

    Failed optional features do not prevent the API from
    starting.
    """

    features = {}

    if not FEATURES_DIR.is_dir():

        return features

    for path in FEATURES_DIR.iterdir():

        if (
            not path.is_file()
            or path.suffix != ".py"
        ):

            continue

        if path.name in {
            "loader.py",
            "__init__.py",
        }:

            continue

        module_name = (
            f"features.{path.stem}"
        )

        try:

            module = (
                importlib.import_module(
                    module_name
                )
            )

            for name, obj in (
                inspect.getmembers(
                    module,
                    inspect.isclass,
                )
            ):

                if (
                    obj.__module__
                    == module_name
                ):

                    features[
                        name.lower()
                    ] = obj()

        except Exception as exc:

            app.logger.warning(
                "Optional feature failed to load | "
                "feature=%s | error=%s",
                path.name,
                exc,
            )

    return features


FEATURES = load_features()


# =========================================================
# DOCUMENT PROCESSING
# =========================================================

def process_uploaded_document(
    file_storage,
) -> tuple[str, dict[str, Any]]:
    """
    Process supported uploaded documents.

    Returns:
        message_text, metadata
    """

    if file_storage is None:

        raise ValueError(
            "No file was supplied."
        )

    filename = (
        file_storage.filename
        or ""
    ).strip()

    if not filename:

        raise ValueError(
            "Uploaded file has no filename."
        )

    safe_name = os.path.basename(
        filename
    )

    extension = (
        Path(
            safe_name
        ).suffix.lower()
    )

    data = file_storage.read()

    if not data:

        raise ValueError(
            "Uploaded file is empty."
        )

    # -----------------------------------------------------
    # PDF
    # -----------------------------------------------------

    if extension == ".pdf":

        try:

            from ai.pdf_processor import (
                process_pdf,
            )

        except ImportError as exc:

            raise RuntimeError(
                "PDF processor is not installed."
            ) from exc

        result = process_pdf(
            data
        )

        extracted_text = str(
            result.get(
                "text",
                "",
            )
            or ""
        ).strip()

        if not extracted_text:

            raise ValueError(
                "The PDF contains no readable text."
            )

        document_text = (
            extracted_text[
                :DOCUMENT_MAX_MODEL_CHARS
            ]
        )

        prompt = (
            request.form.get(
                "message",
                "",
            )
            or ""
        ).strip()

        if prompt:

            message = (
                f"{prompt}\n\n"
                f"Document: {safe_name}\n"
                f"Document content:\n"
                f"{document_text}"
            )

        else:

            message = (
                f"Analyze the following PDF "
                f"document: {safe_name}\n\n"
                f"{document_text}"
            )

        metadata = {
            "type": "pdf",
            "filename": safe_name,
            "mime_type": (
                file_storage.mimetype
                or "application/pdf"
            ),
            "pages": (
                result.get(
                    "metadata",
                    {},
                ).get(
                    "pages"
                )
            ),
            "chunks": len(
                result.get(
                    "chunks",
                    [],
                )
                if isinstance(
                    result.get(
                        "chunks",
                        [],
                    ),
                    list,
                )
                else []
            ),
            "ocr_pages": (
                result.get(
                    "metadata",
                    {},
                ).get(
                    "ocr_pages",
                    0,
                )
            ),
            "truncated_for_model": (
                len(extracted_text)
                > DOCUMENT_MAX_MODEL_CHARS
            ),
        }

        return (
            message,
            metadata,
        )

    # -----------------------------------------------------
    # DOCX
    # -----------------------------------------------------

    if extension == ".docx":

        content = str(
            extract_text_from_docx(
                data
            )
            or ""
        ).strip()

        if not content:

            raise ValueError(
                "The DOCX document contains no readable text."
            )

        content = content[
            :DOCUMENT_MAX_MODEL_CHARS
        ]

        prompt = (
            request.form.get(
                "message",
                "",
            )
            or ""
        ).strip()

        if prompt:

            message = (
                f"{prompt}\n\n"
                f"Document: {safe_name}\n"
                f"Document content:\n"
                f"{content}"
            )

        else:

            message = (
                f"Analyze the following document: "
                f"{safe_name}\n\n"
                f"{content}"
            )

        return (
            message,
            {
                "type": "docx",
                "filename": safe_name,
                "mime_type": (
                    file_storage.mimetype
                    or (
                        "application/vnd.openxmlformats-officedocument."
                        "wordprocessingml.document"
                    )
                ),
                "truncated_for_model": (
                    len(content)
                    >= DOCUMENT_MAX_MODEL_CHARS
                ),
            },
        )

    # -----------------------------------------------------
    # TEXT
    # -----------------------------------------------------

    if extension in {
        ".txt",
        ".md",
        ".csv",
        ".json",
        ".py",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".html",
        ".css",
    }:

        content = data.decode(
            "utf-8",
            errors="replace",
        ).strip()

        if not content:

            raise ValueError(
                "The uploaded text file is empty."
            )

        content = content[
            :DOCUMENT_MAX_MODEL_CHARS
        ]

        prompt = (
            request.form.get(
                "message",
                "",
            )
            or ""
        ).strip()

        if prompt:

            message = (
                f"{prompt}\n\n"
                f"File: {safe_name}\n"
                f"File content:\n"
                f"{content}"
            )

        else:

            message = (
                f"Analyze the following file: "
                f"{safe_name}\n\n"
                f"{content}"
            )

        return (
            message,
            {
                "type": "text_document",
                "filename": safe_name,
                "mime_type": (
                    file_storage.mimetype
                    or "text/plain"
                ),
                "truncated_for_model": (
                    len(content)
                    >= DOCUMENT_MAX_MODEL_CHARS
                ),
            },
        )

    # -----------------------------------------------------
    # Unsupported
    # -----------------------------------------------------

    raise ValueError(
        (
            "Unsupported file type. "
            "Supported documents are PDF, DOCX, TXT, MD, "
            "CSV, JSON and common source-code text files."
        )
    )


# =========================================================
# IMAGE INTENT
# =========================================================

IMAGE_INTENT_PHRASES = {
    "generate image",
    "generate an image",
    "create image",
    "create an image",
    "make an image",
    "make me an image",
    "draw",
    "draw an image",
    "generate a picture",
    "create a picture",
    "make a picture",
    "image generation",
    "generate an illustration",
    "create an illustration",
    "make an illustration",
    "generate artwork",
    "create artwork",
    "make artwork",
    "generate a photo",
    "create a photo",
    "make a photo",
    "generate art",
    "create art",
    "make art",
    "create a logo",
    "make a logo",
    "design a logo",
    "generate a logo",
    "create a poster",
    "make a poster",
    "design a poster",
    "generate a poster",
    "create a banner",
    "make a banner",
    "design a banner",
    "generate a banner",
    "create a flyer",
    "make a flyer",
    "design a flyer",
    "generate a flyer",
    "create a graphic",
    "make a graphic",
    "design a graphic",
    "generate a graphic",
}


IMAGE_DESIGN_RE = re.compile(
    r"\b(?:create|make|design|generate|draw|produce)"
    r"\s+(?:me\s+)?(?:a|an)?\s*"
    r"(?:logo|poster|banner|flyer|illustration|graphic|artwork|"
    r"social post|social media design|thumbnail|invitation|certificate|"
    r"infographic|diagram|cover)\b",
    re.I,
)


def is_image_generation_request(
    message: str,
) -> bool:
    """
    Determine whether the user's request explicitly asks
    for image/design generation.

    Runs before the general intent router so GPT-OSS cannot
    accidentally treat a visual request as a normal question.
    """

    lowered = (
        str(
            message or ""
        )
        .strip()
        .lower()
    )

    if not lowered:
        return False

    if IMAGE_DESIGN_RE.search(
        lowered
    ):

        return True

    return any(
        phrase in lowered
        for phrase in IMAGE_INTENT_PHRASES
    )


# =========================================================
# IMAGE REQUEST OPTIONS
# =========================================================

def _optional_int(
    value: Any,
    label: str,
) -> int | None:
    """Parse an optional integer, allowing blank form values."""

    if value is None:
        return None

    if isinstance(
        value,
        str,
    ):

        value = value.strip()

        if not value:
            return None

    try:

        return int(value)

    except (
        TypeError,
        ValueError,
    ) as exc:

        raise ValueError(
            f"Image {label} must be an integer."
        ) from exc


def parse_image_options(
    source: Any,
) -> dict[str, Any]:
    """
    Read optional Canva-style image controls.

    Supported:
        aspect_ratio
        width
        height
        seed

    Examples:

        {
            "aspect_ratio": "square"
        }

        {
            "aspect_ratio": "story",
            "seed": 42
        }

        {
            "width": 1280,
            "height": 720
        }
    """

    if not isinstance(
        source,
        dict,
    ):

        return {}

    options: dict[str, Any] = {}

    # -----------------------------------------------------
    # Aspect ratio
    # -----------------------------------------------------

    aspect_ratio = (
        source.get(
            "aspect_ratio"
        )
        or source.get(
            "image_aspect_ratio"
        )
        or ""
    )

    aspect_ratio = str(
        aspect_ratio
    ).strip().lower()

    if aspect_ratio:

        options[
            "aspect_ratio"
        ] = aspect_ratio

    # -----------------------------------------------------
    # Width / height / seed
    # -----------------------------------------------------

    width = _optional_int(
        source.get(
            "width"
        ),
        "width",
    )

    height = _optional_int(
        source.get(
            "height"
        ),
        "height",
    )

    seed = _optional_int(
        source.get(
            "seed"
        ),
        "seed",
    )

    if width is not None:
        options[
            "width"
        ] = width

    if height is not None:
        options[
            "height"
        ] = height

    if seed is not None:
        options[
            "seed"
        ] = seed

    return options


# =========================================================
# IMAGE ASSET GENERATION
# =========================================================

def _save_svg_asset(
    svg: str,
) -> tuple[str, str]:
    """Save validated SVG and return filename/path."""

    filename = (
        "revelaai_"
        f"{uuid.uuid4().hex}.svg"
    )

    filepath = os.path.join(
        IMAGE_DIR,
        filename,
    )

    with open(
        filepath,
        "w",
        encoding="utf-8",
    ) as handle:

        handle.write(
            svg
        )

    return (
        filename,
        filepath,
    )


def _save_raster_asset(
    image: Any,
) -> tuple[str, str]:
    """Save a PIL-compatible image and return filename/path."""

    filename = (
        "revelaai_"
        f"{uuid.uuid4().hex}.png"
    )

    filepath = os.path.join(
        IMAGE_DIR,
        filename,
    )

    image.save(
        filepath,
        format="PNG",
    )

    return (
        filename,
        filepath,
    )


def generate_image_asset(
    message: str,
    *,
    image_options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Generate and persist one visual asset.

    Returns:
        {
            filename,
            filepath,
            image_url,
            asset_type,
            image_plan,
        }

    Raises:
        ValueError / RuntimeError / provider exceptions
        which are handled by the calling route.
    """

    options = (
        image_options
        if isinstance(
            image_options,
            dict,
        )
        else {}
    )

    # -----------------------------------------------------
    # Plan
    # -----------------------------------------------------

    image_plan = build_image_prompt(
        message
    )

    # -----------------------------------------------------
    # Overrides
    # -----------------------------------------------------

    requested_aspect_ratio = (
        options.get(
            "aspect_ratio"
        )
    )

    requested_width = (
        options.get(
            "width"
        )
    )

    requested_height = (
        options.get(
            "height"
        )
    )

    requested_seed = (
        options.get(
            "seed"
        )
    )

    aspect_ratio = (
        requested_aspect_ratio
        or image_plan.get(
            "aspect_ratio"
        )
    )

    width = (
        requested_width
        if requested_width is not None
        else image_plan.get(
            "width"
        )
    )

    height = (
        requested_height
        if requested_height is not None
        else image_plan.get(
            "height"
        )
    )

    # -----------------------------------------------------
    # Log
    # -----------------------------------------------------

    app.logger.info(
        "IMAGE PROMPT PLANNED | "
        "request_id=%s | kind=%s | engine=%s | "
        "style=%s | layout=%s | text=%s | "
        "aspect=%s | size=%sx%s",
        getattr(
            g,
            "request_id",
            None,
        ),
        image_plan.get(
            "kind"
        ),
        image_plan.get(
            "engine"
        ),
        image_plan.get(
            "style"
        ),
        image_plan.get(
            "layout"
        ),
        image_plan.get(
            "has_text"
        ),
        aspect_ratio,
        width,
        height,
    )

    # =====================================================
    # STRUCTURED SVG
    # =====================================================

    if image_plan.get(
        "engine"
    ) == "svg":

        svg = generate_svg(
            image_plan,
            text=image_plan.get(
                "text"
            ),
        )

        filename, filepath = (
            _save_svg_asset(
                svg
            )
        )

        asset_type = "svg"

    # =====================================================
    # RASTER IMAGE
    # =====================================================

    else:

        image = generate_hf_image(
            prompt=image_plan[
                "prompt"
            ],
            negative_prompt=image_plan.get(
                "negative_prompt"
            ),
            has_text=bool(
                image_plan.get(
                    "has_text"
                )
            ),
            aspect_ratio=aspect_ratio,
            width=width,
            height=height,
            seed=requested_seed,
        )

        if image is None:

            raise RuntimeError(
                "Hugging Face returned no image."
            )

        filename, filepath = (
            _save_raster_asset(
                image
            )
        )

        asset_type = "png"

    # -----------------------------------------------------
    # Public URL
    # -----------------------------------------------------

    image_url = (
        request.host_url.rstrip("/")
        + "/ai/images/"
        + filename
    )

    app.logger.info(
        "IMAGE GENERATED SUCCESSFULLY | "
        "request_id=%s | file=%s | "
        "asset_type=%s | kind=%s | aspect=%s",
        getattr(
            g,
            "request_id",
            None,
        ),
        filename,
        asset_type,
        image_plan.get(
            "kind"
        ),
        aspect_ratio,
    )

    return {
        "filename": filename,
        "filepath": filepath,
        "image_url": image_url,
        "asset_type": asset_type,
        "image_plan": image_plan,
        "aspect_ratio": aspect_ratio,
        "width": width,
        "height": height,
        "seed": requested_seed,
    }


# =========================================================
# IMAGE RESPONSE HELPER
# =========================================================

def generate_image_response(
    message: str,
    *,
    image_options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Generate a Canva-style image asset and return the
    canonical RevelaAI JSON response.
    """

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

    return jsonify({
        "status": "success",
        "service": "revelaai",
        "build_id": REVELAAI_BUILD_ID,

        "capabilities": {
            "text": {
                "enabled": True,
                "provider": "huggingface",
                "model": os.getenv(
                    "HF_MODEL",
                    "openai/gpt-oss-120b:cheapest",
                ),
            },

            "image_generation": {
                "enabled": bool(
                    hf_configured()
                ),
                "provider": "huggingface",
                "routing": {
                    "primary": "ai_client",
                    "text_aware": True,
                    "fallback": True,
                    "provider_aware": True,
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

            "online_research": {
                "enabled": True,
                "available": online_available,
                "provider": "services.scraper",
            },

            "pdf": {
                "enabled": True,
                "available": pdf_available,
                "processor": "PyMuPDF",
            },

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
                "tts_enabled": REVELAAI_ENABLE_HF_TTS,
            },

            "ecosystem": {
                "enabled": True,
                "provider": "RevelaCode Backend",
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

            # -------------------------------------------------
            # MULTIPART REQUEST
            # -------------------------------------------------

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

            # -------------------------------------------------
            # JSON REQUEST
            # -------------------------------------------------

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
        # INTENT
        # -------------------------------------------------

        intent = classify_intent(
            message
        )

        image_request = (
            is_image_generation_request(
                message
            )
        )

        if image_request:

            intent = (
                "image_generation"
            )

        app.logger.info(
            "IMAGE ROUTING | "
            "request_id=%s | detected=%s | intent=%s | "
            "build=%s | message=%s",
            getattr(
                g,
                "request_id",
                None,
            ),
            image_request,
            intent,
            REVELAAI_BUILD_ID,
            message[:200],
        )

        lowered = (
            message.lower()
        )

        # -------------------------------------------------
        # CONVERSATION CONTINUITY
        # -------------------------------------------------
        #
        # Intent is the CURRENT request.
        # Intent is NOT the conversation identity.
        # -------------------------------------------------

        session[
            "topic"
        ] = intent

        # -------------------------------------------------
        # IMAGE GENERATION
        # -------------------------------------------------

        if intent == "image_generation":

            image_result = (
                generate_image_response(
                    message,
                    image_options=image_options,
                )
            )

            # -------------------------------------------------
            # SAVE IMAGE CONVERSATION
            # -------------------------------------------------

            session[
                "messages"
            ].append({
                "role": "user",
                "content": message,
            })

            if image_result.get(
                "ok",
                False,
            ):

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
        # CENTRAL REVELAAI PIPELINE
        # -------------------------------------------------

        ai_result = process_message(
            message=message,
            context=previous_context,
            intent=intent,
            session_id=session_id,
            user_id=user_id,
        )

        assistant_text = (
            ai_result.get(
                "response",
                "",
            )
            or ""
        ).strip()

        if not assistant_text:

            raise RuntimeError(
                "RevelaAI returned an empty response."
            )

        # -------------------------------------------------
        # SAVE ASSISTANT RESPONSE
        # -------------------------------------------------

        session[
            "messages"
        ].append({
            "role": "assistant",
            "content": assistant_text,
        })

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

        online_data = (
            orchestrator_data.get(
                "online",
                {},
            )
            if isinstance(
                orchestrator_data,
                dict,
            )
            else {}
        )

        sources = (
            online_data.get(
                "sources",
                [],
            )
            if isinstance(
                online_data,
                dict,
            )
            else []
        )

        meta = {
            "ai_model": ai_result.get(
                "model"
            ),

            "provider": ai_result.get(
                "provider",
                "huggingface",
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

            "domain": ai_result.get(
                "domain",
                "general",
            ),

            "domains": ai_result.get(
                "domains",
                [],
            ),

            "emotion": ai_result.get(
                "emotion",
                "unknown",
            ),

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
                if isinstance(
                    orchestrator_data,
                    dict,
                )
                else {}
            ),

            "agriculture": (
                orchestrator_data.get(
                    "agriculture",
                    {},
                )
                if isinstance(
                    orchestrator_data,
                    dict,
                )
                else {}
            ),

            "multimodal": (
                attachment_metadata
                or (
                    orchestrator_data.get(
                        "multimodal",
                        {},
                    )
                    if isinstance(
                        orchestrator_data,
                        dict,
                    )
                    else {}
                )
            ),

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
                "message": "Unsupported generated image format.",
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

    # -----------------------------------------------------
    # CONVERSATION MEMORY
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # INTENT
    # -----------------------------------------------------

    intent = classify_intent(
        message
    )

    image_request = (
        is_image_generation_request(
            message
        )
    )

    if image_request:

        intent = (
            "image_generation"
        )

    app.logger.info(
        "STREAM ROUTING | "
        "request_id=%s | image=%s | intent=%s | build=%s",
        getattr(
            g,
            "request_id",
            None,
        ),
        image_request,
        intent,
        REVELAAI_BUILD_ID,
    )

    session[
        "topic"
    ] = intent

    # -----------------------------------------------------
    # IMAGE STREAMING
    # -----------------------------------------------------

    if intent == "image_generation":

        @stream_with_context
        def generate_image_stream():

            try:

                asset = generate_image_asset(
                    message,
                    image_options=image_options,
                )

                # -------------------------------------------------
                # SAVE IMAGE CONVERSATION
                # -------------------------------------------------

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

    # -----------------------------------------------------
    # NORMAL STREAMING
    # -----------------------------------------------------

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

            response_text = (
                ai_result.get(
                    "response",
                    "",
                )
                or "No response generated."
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
                "data: RevelaAI could not complete the request.\n\n"
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
# VOICE
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
                "message": "No audio file was provided.",
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
                "message": "Uploaded audio is empty.",
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
    # NORMAL REVELAAI PIPELINE
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

    # -----------------------------------------------------
    # VOICE CONVERSATION MEMORY
    # -----------------------------------------------------

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

    intent = classify_intent(
        heard
    )

    # Image requests through voice must also route to the
    # image planner and visual engine.

    if is_image_generation_request(
        heard
    ):

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

    if intent == "image_generation":

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
                    image_result["response"],
                    image_result["status_code"],
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

            session[
                "messages"
            ].append({
                "role": "user",
                "content": heard,
            })

            session[
                "messages"
            ].append({
                "role": "assistant",
                "content": (
                    "Image generated successfully."
                ),
            })

            save_session(
                session_id,
                session,
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
                    "code": "VOICE_IMAGE_GENERATION_FAILED",
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
    # AI
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
    # TEXT TO SPEECH
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
        )
        .strip()
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
                "message": "Invalid audio filename.",
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

    return jsonify({
        "status": "ok",
        "service": "revelaai",

        "environment": ENVIRONMENT,

        "build": {
            "id": REVELAAI_BUILD_ID,
            "image_routing": "ai-client-managed",
            "image_engine": REVELAAI_IMAGE_ENGINE_VERSION,
            "conversation_memory": "client-context-plus-session",
        },

        "providers": {
            "text": {
                "provider": "huggingface",
                "configured": hf_configured(),
                "model": os.getenv(
                    "HF_MODEL",
                    "openai/gpt-oss-120b:cheapest",
                ),
            },

            "image": {
                "provider": "huggingface",
                "configured": hf_configured(),
                "primary_model": configured_image_model(),
                "routing": {
                    "owner": "ai_client",
                    "text_aware": True,
                    "fallback": True,
                    "provider_aware": True,
                },
                "structured_svg": True,
            },

            "voice": {
                "provider": "huggingface",
                "configured": hf_configured(),
                "asr_model": os.getenv(
                    "HF_ASR_MODEL",
                    "openai/whisper-large-v3",
                ),
                "tts_model": os.getenv(
                    "HF_TTS_MODEL",
                    "hexgrad/Kokoro-82M",
                ),
                "tts_enabled": REVELAAI_ENABLE_HF_TTS,
            },
        },

        "online_research": {
            "available": online_available,
        },

        "pdf": {
            "available": pdf_available,
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

    checks: dict[str, bool] = {}

    checks[
        "huggingface"
    ] = hf_configured()

    checks[
        "image_model"
    ] = bool(
        configured_image_model()
    )

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

    ready_status = all(
        checks.values()
    )

    return jsonify({
        "status": (
            "ready"
            if ready_status
            else "degraded"
        ),
        "service": "revelaai",
        "build_id": REVELAAI_BUILD_ID,
        "checks": checks,
    }), (
        200
        if ready_status
        else 503
    )


# =========================================================
# BLUEPRINT REGISTRATION
# =========================================================

# Keep the existing application architecture intact.
# These blueprints expose the project's established routes.

try:

    app.register_blueprint(
        chat_bp
    )

except Exception as exc:

    app.logger.warning(
        "chat_bp registration failed | error=%s",
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
        memory_bp
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


# =========================================================
# DEVELOPMENT ENTRYPOINT ONLY
# =========================================================

if __name__ == "__main__":

    # This block is for local development only.
    # Render production uses Gunicorn.

    app.run(
        host="0.0.0.0",
        port=PORT,
        debug=(
            ENVIRONMENT
            == "development"
        ),
    )
