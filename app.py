# app.py

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

from dotenv import load_dotenv

# =========================================================
# ENVIRONMENT
# =========================================================

load_dotenv()


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

    Anonymous clients should preferably send X-Session-ID.
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
    "create image",
    "make an image",
    "draw",
    "generate a picture",
    "create a picture",
    "image generation",
    "create an image",
    "make me an image",
    "generate an illustration",
}


def is_image_generation_request(
    message: str,
) -> bool:

    lowered = (
        str(
            message or ""
        )
        .strip()
        .lower()
    )

    return any(
        phrase in lowered
        for phrase in IMAGE_INTENT_PHRASES
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
                    and os.getenv(
                        "HF_IMAGE_MODEL",
                        "",
                    )
                ),
                "provider": "huggingface",
                "model": os.getenv(
                    "HF_IMAGE_MODEL",
                    "black-forest-labs/FLUX.1-schnell",
                ),
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

        if is_image_generation_request(
            message
        ):

            intent = "image_generation"

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

        if intent == "image_generation":

            try:

                image = generate_hf_image(
                    prompt=message,
                    model=os.getenv(
                        "HF_IMAGE_MODEL",
                        "black-forest-labs/FLUX.1-schnell",
                    ),
                    width=int(
                        os.getenv(
                            "HF_IMAGE_DEFAULT_WIDTH",
                            "1024",
                        )
                    ),
                    height=int(
                        os.getenv(
                            "HF_IMAGE_DEFAULT_HEIGHT",
                            "1024",
                        )
                    ),
                    num_inference_steps=int(
                        os.getenv(
                            "HF_IMAGE_DEFAULT_STEPS",
                            "4",
                        )
                    ),
                )

            except Exception:

                app.logger.exception(
                    "Image generation failed | request_id=%s",
                    getattr(
                        g,
                        "request_id",
                        None,
                    ),
                )

                return jsonify(
                    error_response(
                        "IMAGE_GENERATION_FAILED",
                        (
                            "Hugging Face image generation "
                            "is temporarily unavailable."
                        ),
                    )
                ), 502

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

            except Exception:

                app.logger.exception(
                    "Generated image could not be saved."
                )

                return jsonify(
                    error_response(
                        "IMAGE_SAVE_FAILED",
                        "Generated image could not be stored.",
                    )
                ), 500

            image_url = (
                request.host_url.rstrip("/")
                + "/ai/images/"
                + filename
            )

            return jsonify(
                enforce_base_schema(
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
                        "model": os.getenv(
                            "HF_IMAGE_MODEL",
                            "black-forest-labs/FLUX.1-schnell",
                        ),
                        "multimodal": {
                            "type": "image",
                        },
                    },
                )
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
            "AI request failed | request_id=%s",
            getattr(
                g,
                "request_id",
                None,
            ),
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

    intent = classify_intent(
        message
    )

    def generate():

        try:

            ai_result = process_message(
                message=message,
                context=previous_context,
                intent=intent,
                session_id=session_id,
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

            yield (
                "event: metadata\n"
                f"data: {{\"intent\":\"{intent}\"}}\n\n"
            )

            yield (
                "event: done\n"
                "data: [DONE]\n\n"
            )

        except Exception as exc:

            app.logger.exception(
                "AI stream failed | request_id=%s",
                getattr(
                    g,
                    "request_id",
                    None,
                ),
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
        }), 400

    audio_bytes = uploaded.read()

    if not audio_bytes:

        return jsonify({
            "status": "error",
            "error": {
                "code": "EMPTY_AUDIO",
                "message": "Uploaded audio is empty.",
            },
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

    except Exception:

        app.logger.exception(
            "Voice transcription failed | request_id=%s",
            getattr(
                g,
                "request_id",
                None,
            ),
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
        }), 400

    # -----------------------------------------------------
    # NORMAL REVELAAI PIPELINE
    # -----------------------------------------------------

    session_id = get_session_id()

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
        )

    except Exception:

        app.logger.exception(
            "Voice AI processing failed | request_id=%s",
            getattr(
                g,
                "request_id",
                None,
            ),
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

    try:

        audio_output = (
            generate_hf_speech(
                response_text
            )
        )

    except Exception:

        app.logger.exception(
            "Voice synthesis failed | request_id=%s",
            getattr(
                g,
                "request_id",
                None,
            ),
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
                },
            },
        })

    mime_type = (
        os.getenv(
            "HF_TTS_MIME_TYPE",
            "audio/flac",
        ).strip()
        or "audio/flac"
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

    except Exception:

        app.logger.exception(
            "Voice audio could not be saved."
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
                "model": os.getenv(
                    "HF_IMAGE_MODEL",
                    "black-forest-labs/FLUX.1-schnell",
                ),
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
        os.getenv(
            "HF_IMAGE_MODEL",
            "",
        ).strip()
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
        "checks": checks,
    }), (
        200
        if ready_status
        else 503
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