# main.py

from __future__ import annotations

import asyncio
import base64
import httpx
import importlib
import inspect
import os
import tempfile
import uuid

from flask import (
    Flask,
    request,
    jsonify,
    send_file,
    Response,
)

from flask_cors import CORS
from dotenv import load_dotenv

# =========================================================
# AI
# =========================================================

from ai.ai_client import (
    generate_hf_image,
)

from ai.intent_router import (
    classify_intent,
)

from services.ai_service import (
    process_message,
)

from ai.json_utils import (
    extract_json,
    enforce_base_schema,
    error_response,
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
# VOICE
# =========================================================

from voice.voice_output import (
    text_to_speech_file,
)

from voice.transcribe import (
    transcribe_audio_file,
)

# =========================================================
# DOCUMENTS
# =========================================================

from utils.docx_utils import (
    extract_text_from_docx,
)

# =========================================================
# DATABASE
# =========================================================

from db.mongo import (
    users_col,
)

# =========================================================
# ROUTES
# =========================================================

from routes.users_routes import (
    users_bp,
)

from routes.chat_routes import (
    chat_bp,
)

from routes.memory_routes import (
    memory_bp,
)

from routes.research_routes import (
    research_bp,
)

from routes.explain_routes import (
    explain_bp,
)

from whatsapp_webhook import (
    whatsapp_bp,
)


# =========================================================
# ENVIRONMENT
# =========================================================

load_dotenv()


# =========================================================
# APP
# =========================================================

app = Flask(
    __name__
)


# =========================================================
# CORS
# =========================================================

CORS(
    app,
    resources={
        r"/*": {
            "origins": [
                "http://localhost:5173",
                "https://revelacode-frontend.onrender.com",
                "https://localhost",
            ]
        }
    },
    supports_credentials=True,
    allow_headers=[
        "Content-Type",
        "Authorization",
        "X-Session-ID",
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
# SELF KEEP-ALIVE
# =========================================================

SELF_URL = (
    os.getenv(
        "REVELAAI_SELF_URL",
        "https://revelaai.onrender.com/health",
    )
    .strip()
)

PING_INTERVAL = 5 * 60


async def keep_alive():
    """
    Optional keep-alive loop.

    Disabled unless REVELAAI_KEEP_ALIVE=true.
    """

    async with httpx.AsyncClient(
        timeout=10.0
    ) as client:

        while True:

            try:

                response = await client.get(
                    SELF_URL
                )

                if response.status_code == 200:

                    print(
                        "[KEEP-ALIVE] Ping successful"
                    )

                else:

                    print(
                        "[KEEP-ALIVE] Ping failed: "
                        f"{response.status_code}"
                    )

            except Exception as exc:

                print(
                    "[KEEP-ALIVE] Ping error:",
                    exc,
                )

            await asyncio.sleep(
                PING_INTERVAL
            )


def start_keep_alive():
    """
    Start the optional keep-alive task.

    This remains disabled by default.
    """

    enabled = (
        os.getenv(
            "REVELAAI_KEEP_ALIVE",
            "false",
        )
        .strip()
        .lower()
        == "true"
    )

    if not enabled:
        return

    try:

        loop = asyncio.get_event_loop()

        loop.create_task(
            keep_alive()
        )

    except Exception as exc:

        app.logger.warning(
            "Keep-alive could not start: %s",
            exc,
        )


# =========================================================
# BLUEPRINTS
# =========================================================

app.register_blueprint(
    users_bp,
    url_prefix="/api/users",
)

app.register_blueprint(
    chat_bp,
    url_prefix="/api/chat",
)

app.register_blueprint(
    memory_bp,
    url_prefix="/api/memory",
)

app.register_blueprint(
    research_bp,
    url_prefix="/api/research",
)

app.register_blueprint(
    explain_bp,
    url_prefix="/api/explain",
)

app.register_blueprint(
    whatsapp_bp
)


# =========================================================
# SESSION MEMORY
# =========================================================

SESSION_MEMORY = {}

MAX_HISTORY = int(
    os.getenv(
        "MAX_HISTORY",
        "10",
    )
)


def get_session_id():
    """
    Preserve explicit client session identity when supplied.

    Falls back to remote address for anonymous/local usage.
    """

    return (
        request.headers.get(
            "X-Session-ID"
        )
        or request.remote_addr
        or "anonymous"
    )


# =========================================================
# GENERATED IMAGE STORAGE
# =========================================================

IMAGE_DIR = os.path.join(
    tempfile.gettempdir(),
    "revelaai_images",
)

os.makedirs(
    IMAGE_DIR,
    exist_ok=True,
)


# =========================================================
# DYNAMIC FEATURE LOADING
# =========================================================

FEATURES_DIR = "features"


def load_features():
    """
    Dynamically load generated feature classes.
    """

    features = {}

    if not os.path.isdir(
        FEATURES_DIR
    ):

        return features

    for file_name in os.listdir(
        FEATURES_DIR
    ):

        if not file_name.endswith(
            ".py"
        ):

            continue

        if file_name in {
            "loader.py",
            "__init__.py",
        }:

            continue

        module_name = (
            f"{FEATURES_DIR}.{file_name[:-3]}"
        )

        try:

            module = importlib.import_module(
                module_name
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
                "Feature loading failed for %s: %s",
                file_name,
                exc,
            )

    return features


FEATURES = load_features()


# =========================================================
# DYNAMIC FEATURES CHAT
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

            result = feature.run(
                user_input
            )

            responses[
                name
            ] = result

        except Exception as exc:

            responses[
                name
            ] = {
                "error": str(
                    exc
                )
            }

    return jsonify({
        "input": user_input,
        "features_used": list(
            FEATURES.keys()
        ),
        "responses": responses,
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
        "app": os.getenv(
            "APP_NAME",
            "RevelaAI Flask Backend",
        ),
        "message": "RevelaAI is live 🚀",
    })


# =========================================================
# MAIN AI / IMAGE ENDPOINT
# =========================================================

@app.route(
    "/ai",
    methods=["POST"],
)
def ai_assistant():

    try:

        session_id = get_session_id()

        session = SESSION_MEMORY.get(
            session_id,
            {
                "topic": None,
                "messages": [],
            },
        )

        # -------------------------------------------------
        # INPUT
        # -------------------------------------------------

        message = ""

        if "file" in request.files:

            uploaded = request.files[
                "file"
            ]

            data = uploaded.read()

            filename = (
                uploaded.filename
                or ""
            )

            if filename.lower().endswith(
                ".docx"
            ):

                content = (
                    extract_text_from_docx(
                        data
                    )
                )

            else:

                content = data.decode(
                    "utf-8",
                    errors="ignore",
                )

            message = (
                "Analyze the following document:\n\n"
                f"{content}"
            )

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

        lowered = message.lower()

        if any(
            keyword in lowered
            for keyword in [
                "generate image",
                "create image",
                "make an image",
                "draw",
                "generate a picture",
                "create a picture",
                "image generation",
            ]
        ):

            intent = "image_generation"

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
                    width=1024,
                    height=1024,
                )

            except Exception as exc:

                app.logger.exception(
                    "Hugging Face image generation failed"
                )

                return jsonify(
                    error_response(
                        "IMAGE_GENERATION_FAILED",
                        str(exc),
                    )
                ), 502

            filename = (
                f"revelaai_"
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
                    },
                )
            )

        # -------------------------------------------------
        # PREVIOUS CONVERSATION
        # -------------------------------------------------

        previous_context = list(
            session.get(
                "messages",
                [],
            )
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

        session[
            "messages"
        ] = session[
            "messages"
        ][-MAX_HISTORY:]

        SESSION_MEMORY[
            session_id
        ] = session

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

        return jsonify(
            enforce_base_schema(
                query=message,
                mode=intent,
                data=data,
                sources=(
                    ai_result.get(
                        "orchestrator",
                        {}
                    )
                    .get(
                        "online",
                        {}
                    )
                    .get(
                        "sources",
                        []
                    )
                ),
                meta={
                    "ai_model": ai_result.get(
                        "model"
                    ),
                    "provider": ai_result.get(
                        "provider",
                        "huggingface",
                    ),
                    "memory": "topic-aware",
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
                },
            )
        )

    except Exception as exc:

        app.logger.exception(
            "AI request failed"
        )

        return jsonify(
            error_response(
                "SERVER_ERROR",
                str(exc),
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

    safe_filename = os.path.basename(
        filename
    )

    filepath = os.path.join(
        IMAGE_DIR,
        safe_filename,
    )

    if not os.path.isfile(
        filepath
    ):

        return jsonify({
            "status": "error",
            "message": "Image not found.",
        }), 404

    return send_file(
        filepath,
        mimetype="image/png",
    )


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

    session = SESSION_MEMORY.get(
        session_id,
        {
            "topic": None,
            "messages": [],
        },
    )

    previous_context = list(
        session.get(
            "messages",
            [],
        )
    )

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

    SESSION_MEMORY[
        session_id
    ] = session

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

            session[
                "messages"
            ] = session[
                "messages"
            ][-MAX_HISTORY:]

            SESSION_MEMORY[
                session_id
            ] = session

            yield (
                f"data: {response_text}\n\n"
            )

            yield (
                "event: done\n"
                "data: [DONE]\n\n"
            )

        except Exception as exc:

            yield (
                "event: error\n"
                f"data: {str(exc)}\n\n"
            )

    return Response(
        generate(),
        mimetype="text/event-stream",
    )


# =========================================================
# VOICE
# =========================================================

@app.route(
    "/voice",
    methods=["POST"],
)
def voice():

    if "audio" not in request.files:

        return jsonify({
            "error": "No audio provided"
        }), 400

    audio = request.files[
        "audio"
    ]

    safe_name = (
        f"revelaai_audio_"
        f"{uuid.uuid4().hex}.wav"
    )

    audio_path = os.path.join(
        tempfile.gettempdir(),
        safe_name,
    )

    audio.save(
        audio_path
    )

    heard = (
        transcribe_audio_file(
            audio_path
        )
    )

    ai_result = process_message(
        message=heard,
        context=[],
        intent=classify_intent(
            heard
        ),
        session_id=get_session_id(),
    )

    response_text = (
        ai_result.get(
            "response",
            "",
        )
        or ""
    )

    out_audio_path = (
        text_to_speech_file(
            response_text
        )
    )

    return jsonify({
        "heard": heard,
        "response": response_text,
        "audio_url": (
            "/voice/audio/"
            + os.path.basename(
                out_audio_path
            )
        ),
    })


@app.route(
    "/voice/audio/<filename>"
)
def serve_audio(
    filename
):

    safe_filename = (
        os.path.basename(
            filename
        )
    )

    path = os.path.join(
        tempfile.gettempdir(),
        safe_filename,
    )

    if not os.path.exists(
        path
    ):

        return jsonify({
            "error": "Audio not found"
        }), 404

    return send_file(
        path,
        mimetype="audio/wav",
    )


# =========================================================
# HEALTH
# =========================================================

@app.route(
    "/health",
    methods=["GET"],
)
def health():

    return jsonify({
        "status": "ok",
        "service": "revelaai",
        "text_provider": "huggingface",
        "text_model": os.getenv(
            "HF_MODEL",
            "openai/gpt-oss-120b:cheapest",
        ),
        "image_provider": "huggingface",
        "image_model": os.getenv(
            "HF_IMAGE_MODEL",
            "black-forest-labs/FLUX.1-schnell",
        ),
    })


# =========================================================
# DATABASE TEST
# =========================================================

@app.route(
    "/test-db",
    methods=["GET"],
)
def test_db():

    users_col.insert_one({
        "test": "db connected",
    })

    return jsonify({
        "status": "ok",
        "message": "MongoDB connected 🚀",
    })


# =========================================================
# STARTUP
# =========================================================

start_keep_alive()


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    port = int(
        os.getenv(
            "PORT",
            "5000",
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
    )