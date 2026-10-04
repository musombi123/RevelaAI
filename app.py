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
"""

from __future__ import annotations

import importlib
import inspect
import logging
import os
import tempfile
import time
import uuid
from collections import OrderedDict
from pathlib import Path
from threading import Lock
from typing import Any
from ai.image_prompt import build_image_prompt

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

BASE_DIR = Path(
    __file__
).resolve().parent


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
        str(25 * 1024 * 1024),
    )
)


MAX_HISTORY = int(
    os.getenv(
        "MAX_HISTORY",
        "10",
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
        str(60 * 60),
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
        str(10 * 1024 * 1024),
    )
)


IMAGE_RETENTION_SECONDS = int(
    os.getenv(
        "IMAGE_RETENTION_SECONDS",
        str(60 * 60),
    )
)


AUDIO_RETENTION_SECONDS = int(
    os.getenv(
        "AUDIO_RETENTION_SECONDS",
        str(60 * 60),
    )
)


# =========================================================
# BUILD / RELEASE IDENTITY
# =========================================================

REVELAAI_BUILD_ID = (
    os.getenv(
        "REVELAAI_BUILD_ID",
        "image-routing-v2",
    ).strip()
    or "image-routing-v2"
)


# =========================================================
# FEATURE FLAGS
# =========================================================

REVELAAI_ENABLE_HF_TTS = (
    os.getenv(
        "REVELAAI_ENABLE_HF_TTS",
        "false",
    ).strip().lower()
    in {
        "1",
        "true",
        "yes",
        "on",
    }
)


# =========================================================
# IMAGE CONFIGURATION
# =========================================================

HF_IMAGE_MODEL_NAME = (
    os.getenv(
        "HF_IMAGE_MODEL",
        "black-forest-labs/FLUX.1-schnell",
    ).strip()
    or "black-forest-labs/FLUX.1-schnell"
)


HF_IMAGE_WIDTH = int(
    os.getenv(
        "HF_IMAGE_DEFAULT_WIDTH",
        "1024",
    )
)


HF_IMAGE_HEIGHT = int(
    os.getenv(
        "HF_IMAGE_DEFAULT_HEIGHT",
        "1024",
    )
)


HF_IMAGE_STEPS = int(
    os.getenv(
        "HF_IMAGE_DEFAULT_STEPS",
        "4",
    )
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


CORS_ORIGINS = parse_cors_origins()


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
def add_response_headers(response):
    """
    Add production response headers.
    """

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
def handle_request_too_large(error):

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
def handle_not_found(error):

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
def handle_method_not_allowed(error):

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
def handle_unexpected_error(error):
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

    for session_id, session in SESSION_MEMORY.items():

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

        session_id = header_id[
            :128
        ]

    else:

        cookie_id = (
            request.cookies.get(
                "revelaai_session"
            )
            or ""
        ).strip()

        if cookie_id:

            session_id = cookie_id[
                :128
            ]

        else:

            session_id = uuid.uuid4().hex

    g.revelaai_session_id = session_id

    return session_id


def get_session(
    session_id: str,
) -> dict[str, Any]:
    """
    Retrieve or initialize bounded session state.
    """

    with SESSION_LOCK:

        _prune_session_memory()

        existing = SESSION_MEMORY.get(
            session_id
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
# SESSION COOKIE
# =========================================================

@app.after_request
def set_session_cookie(response):
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

    for directory, retention in directories:

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

            for name, obj in inspect.getmembers(
                module,
                inspect.isclass,
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
                    or "application/vnd.openxmlformats-officedocument."
                       "wordprocessingml.document"
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
}


def is_image_generation_request(
    message: str,
) -> bool:
    """
    Determine whether the user's request explicitly asks
    for image generation.

    This function intentionally runs before the general
    intent router so GPT-OSS cannot accidentally treat an
    image-generation request as a normal text question.
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

    for phrase in IMAGE_INTENT_PHRASES:

        if phrase in lowered:
            return True

    return False


# =========================================================
# IMAGE RESPONSE HELPER
# =========================================================

def generate_image_response(
    message: str,
) -> dict[str, Any]:
    """
    Generate an image and return the canonical RevelaAI
    image response.

    The response format is intentionally stable for the
    frontend:

        mode=image

        data={
            type=image,
            urls=[...]
        }
    """

    app.logger.info(
        "IMAGE GENERATION BRANCH | "
        "request_id=%s | model=%s | build=%s",
        getattr(
            g,
            "request_id",
            None,
        ),
        HF_IMAGE_MODEL_NAME,
        REVELAAI_BUILD_ID,
    )

    try:

        image_plan = build_image_prompt(message)

        app.logger.info(
            "IMAGE PROMPT PLANNED | "
            "request_id=%s | domain=%s | style=%s",
            getattr(
                g,
                "request_id",
                None,
            ),
            image_plan.get("domain"),
            image_plan.get("style"),
        )

        image = generate_hf_image(
            prompt=image_plan["prompt"],
            negative_prompt=image_plan.get(
                "negative_prompt"
            ),
            model=HF_IMAGE_MODEL_NAME,
            width=HF_IMAGE_WIDTH,
            height=HF_IMAGE_HEIGHT,
            num_inference_steps=HF_IMAGE_STEPS,
        )

    except Exception as exc:

        app.logger.exception(
            "Image generation failed | "
            "request_id=%s | model=%s | error=%s",
            getattr(
                g,
                "request_id",
                None,
            ),
            HF_IMAGE_MODEL_NAME,
            exc,
        )

        return {
            "ok": False,
            "response": jsonify(
                error_response(
                    "IMAGE_GENERATION_FAILED",
                    (
                        "Hugging Face image generation "
                        "is temporarily unavailable."
                    ),
                )
            ),
            "status_code": 502,
        }

    if image is None:

        app.logger.error(
            "Image provider returned None | request_id=%s",
            getattr(
                g,
                "request_id",
                None,
            ),
        )

        return {
            "ok": False,
            "response": jsonify(
                error_response(
                    "IMAGE_GENERATION_EMPTY",
                    "Hugging Face returned no image.",
                )
            ),
            "status_code": 502,
        }

    filename = (
        "revelaai_"
        f"{uuid.uuid4().hex}.png"
    )

    filepath = os.path.join(
        IMAGE_DIR,
        filename,
    )

    try:

        image.save(
            filepath,
            format="PNG",
        )

    except Exception as exc:

        app.logger.exception(
            "Generated image could not be saved | "
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
                    "IMAGE_SAVE_FAILED",
                    "Generated image could not be stored.",
                )
            ),
            "status_code": 500,
        }

    image_url = (
        request.host_url.rstrip("/")
        + "/ai/images/"
        + filename
    )

    app.logger.info(
        "IMAGE GENERATED SUCCESSFULLY | "
        "request_id=%s | file=%s | url=%s",
        getattr(
            g,
            "request_id",
            None,
        ),
        filename,
        image_url,
    )

    response = enforce_base_schema(
        query=message,
        mode="image",
        data={
            "type": "image",
            "urls": [
                image_url
            ],
        },
        sources=[],
        meta={
            "provider": "huggingface",
            "model": HF_IMAGE_MODEL_NAME,
            "build_id": REVELAAI_BUILD_ID,
            "intent": "image_generation",
            "multimodal": {
                "type": "image",
            },
        },
    )

    return {
        "ok": True,
        "response": jsonify(
            response
        ),
        "status_code": 200,
        "filename": filename,
        "filepath": filepath,
        "image_url": image_url,
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

    for name, feature in FEATURES.items():

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
                    and HF_IMAGE_MODEL_NAME
                ),
                "provider": "huggingface",
                "model": HF_IMAGE_MODEL_NAME,
                "routing": "explicit",
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

    session_id = get_session_id()

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

        uploaded = (
            request.files.get(
                "file"
            )
            or request.files.get(
                "attachment"
            )
        )

        if uploaded:

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
                    "Message or file required.",
                )
            ), 400

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

            intent = "image_generation"

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

        lowered = message.lower()

        # -------------------------------------------------
        # TOPIC RESET
        # -------------------------------------------------

        if session.get(
            "topic"
        ) != intent:

            session[
                "messages"
            ] = []

            session[
                "topic"
            ] = intent

        # -------------------------------------------------
        # IMAGE GENERATION
        # -------------------------------------------------

        # IMPORTANT:
        # Image requests return immediately.
        # They NEVER enter process_message().
        # This prevents GPT-OSS from hallucinating image
        # markdown instead of invoking FLUX.

        if intent == "image_generation":

            image_result = (
                generate_image_response(
                    message
                )
            )

            return (
                image_result["response"],
                image_result["status_code"],
            )

        # -------------------------------------------------
        # PREVIOUS CONVERSATION
        # -------------------------------------------------

        previous_context = [
            {
                "role": item.get(
                    "role",
                    "user",
                ),
                "content": item.get(
                    "content",
                    "",
                ),
            }
            for item in list(
                session.get(
                    "messages",
                    [],
                )
            )
            if isinstance(
                item,
                dict,
            )
        ]

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
                {}
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

            "memory": "bounded-session",

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

    response = send_file(
        filepath,
        mimetype="image/png",
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

    session_id = get_session_id()

    user_id = (
        resolve_revelacode_user_id()
    )

    session = get_session(
        session_id
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

        intent = "image_generation"

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

    # -----------------------------------------------------
    # IMAGE STREAMING
    # -----------------------------------------------------

    if intent == "image_generation":

        image_host_url = (
            request.host_url.rstrip("/")
        )

        @stream_with_context
        def generate_image_stream():

            try:

                app.logger.info(
                    "STREAM IMAGE GENERATION BRANCH | "
                    "request_id=%s | model=%s",
                    getattr(
                        g,
                        "request_id",
                        None,
                    ),
                    HF_IMAGE_MODEL_NAME,
                )

                image = generate_hf_image(
                    prompt=message,
                    model=HF_IMAGE_MODEL_NAME,
                    width=HF_IMAGE_WIDTH,
                    height=HF_IMAGE_HEIGHT,
                    num_inference_steps=HF_IMAGE_STEPS,
                )

                if image is None:
                    raise RuntimeError(
                        "Hugging Face returned no image."
                    )

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

                image_url = (
                    image_host_url
                    + "/ai/images/"
                    + filename
                )

                image_payload = {
                    "success": True,
                    "mode": "image",
                    "query": message,
                    "data": {
                        "type": "image",
                        "urls": [
                            image_url
                        ],
                    },
                    "sources": [],
                    "meta": {
                        "intent": "image_generation",
                        "provider": "huggingface",
                        "model": HF_IMAGE_MODEL_NAME,
                        "build_id": REVELAAI_BUILD_ID,
                        "multimodal": {
                            "type": "image",
                        },
                    },
                }

                import json

                yield (
                    "event: image\n"
                    "data: "
                    f"{json.dumps(image_payload)}\n\n"
                )

                yield (
                    "event: done\n"
                    "data: [DONE]\n\n"
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

                yield (
                    "event: error\n"
                    "data: Image generation failed.\n\n"
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

    previous_context = [
        {
            "role": item.get(
                "role",
                "user",
            ),
            "content": item.get(
                "content",
                "",
            ),
        }
        for item in list(
            session.get(
                "messages",
                [],
            )
        )
        if isinstance(
            item,
            dict,
        )
    ]

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

            import json

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

    audio_bytes = uploaded.read()

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

    session_id = get_session_id()

    user_id = (
        resolve_revelacode_user_id()
    )

    session = get_session(
        session_id
    )

    previous_context = [
        {
            "role": item.get(
                "role",
                "user",
            ),
            "content": item.get(
                "content",
                "",
            ),
        }
        for item in list(
            session.get(
                "messages",
                [],
            )
        )
        if isinstance(
            item,
            dict,
        )
    ]

    intent = classify_intent(
        heard
    )

    # Image requests through voice must also route to FLUX.

    if is_image_generation_request(
        heard
    ):

        intent = "image_generation"

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

            # Use the generated image URL as the spoken
            # response metadata. TTS remains optional.

            image_url = (
                image_result.get(
                    "image_url"
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
                    "provider": "huggingface",
                    "model": HF_IMAGE_MODEL_NAME,
                    "build_id": REVELAAI_BUILD_ID,
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

    # HF TTS is disabled by default because provider credits
    # may be exhausted. This prevents every voice request
    # from making a guaranteed-failing TTS call.

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
                "build_id": REVELAAI_BUILD_ID,
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
            "image_routing": "explicit",
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
                "model": HF_IMAGE_MODEL_NAME,
                "routing": "explicit",
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
        HF_IMAGE_MODEL_NAME
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
