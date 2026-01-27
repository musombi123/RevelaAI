import os
import time
import requests
import tempfile

from flask import Flask, request, jsonify, Response, send_file
from flask_cors import CORS
from dotenv import load_dotenv

# -------------------------------
# AI & Services
# -------------------------------
from ai.ai_client import get_groq_client, create_replicate_prediction
from ai.intent_router import classify_intent
from services.ai_service import process_message
from services.expert_law import analyze_legal_query
from services.expert_medicine import analyze_medical_query
from utils.docx_utils import extract_text_from_docx
from routes.research import research_bp
from voice.voice_output import text_to_speech_file
from voice.transcribe import transcribe_audio_file

# -------------------------------
# Core Utilities
# -------------------------------
from ai.system_prompt import SYSTEM_PROMPT
from ai.json_utils import extract_json, enforce_base_schema, error_response

# -------------------------------
# Routes (Flask Blueprints)
# -------------------------------
from routes.users_routes import users_bp
from routes.chat_routes import chat_bp
from routes.memory_routes import memory_bp
from routes.research_routes import research_bp
from routes.explain_routes import explain_bp

# WhatsApp Webhook Blueprint
from whatsapp_webhook import whatsapp_bp

# -------------------------------
# Database Setup (MongoDB)
# -------------------------------
from db.mongo import users_col, memory_col, messages_col
users_col.insert_one({"name": "Musombi William"})

# -------------------------------
# Environment & App Setup
# -------------------------------
load_dotenv()
app = Flask(__name__)

CORS(
    app,
    resources={r"/*": {
        "origins": [
            "http://localhost:5173",
            "https://revelacode-frontend.onrender.com"
        ]
    }},
    supports_credentials=True
)

# -------------------------------
# Register Blueprints
# -------------------------------
app.register_blueprint(users_bp, url_prefix="/api/users")
app.register_blueprint(chat_bp, url_prefix="/api/chat")
app.register_blueprint(memory_bp, url_prefix="/api/memory")
app.register_blueprint(research_bp, url_prefix="/api/research")
app.register_blueprint(explain_bp, url_prefix="/api/explain")
app.register_blueprint(whatsapp_bp)

# -------------------------------
# 🧠 SESSION MEMORY
# -------------------------------
SESSION_MEMORY = {}
MAX_HISTORY = 10

def get_session_id():
    return request.headers.get("X-Session-ID", request.remote_addr)

# -------------------------------
# Dynamic Feature Loading
# -------------------------------
import importlib
import inspect

FEATURES_DIR = "features"

def load_features():
    features = {}
    for file in os.listdir(FEATURES_DIR):
        if not file.endswith(".py"):
            continue
        if file in ("loader.py", "__init__.py"):
            continue

        module_name = f"{FEATURES_DIR}.{file[:-3]}"
        module = importlib.import_module(module_name)

        for name, obj in inspect.getmembers(module, inspect.isclass):
            if obj.__module__ == module_name:
                features[name.lower()] = obj()

    return features

# Load all generated features
FEATURES = load_features()

# -------------------------------
# Dynamic Features Chat Endpoint
# -------------------------------
@app.route("/chat", methods=["POST"])
def chat():
    user_input = request.json.get("message", "")
    responses = {}

    for name, feature in FEATURES.items():
        try:
            result = feature.run(user_input)
            responses[name] = result
        except Exception as e:
            responses[name] = {"error": str(e)}

    return jsonify({
        "input": user_input,
        "features_used": list(FEATURES.keys()),
        "responses": responses
    })

# -------------------------------
# LLM Call (Streaming)
# -------------------------------
def get_ai_reply_streamed(session_messages):
    client = get_groq_client()
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(session_messages)

    stream = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=messages,
        temperature=0.4,
        max_tokens=700,
        stream=True
    )

    for chunk in stream:
        delta = chunk.choices[0].delta
        if delta and delta.content:
            yield delta.content

# -------------------------------
# Replicate Polling
# -------------------------------
def poll_replicate(prediction_id, token, timeout=60):
    headers = {"Authorization": f"Token {token}"}
    url = f"https://api.replicate.com/v1/predictions/{prediction_id}"
    start = time.time()

    while True:
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        prediction = r.json()

        if prediction["status"] in ("succeeded", "failed"):
            return prediction

        if time.time() - start > timeout:
            raise TimeoutError("Image generation timed out")

        time.sleep(2)

# -------------------------------
# Root
# -------------------------------
@app.route("/", methods=["GET"])
def root():
    return jsonify({
        "status": "success",
        "app": os.getenv("APP_NAME", "RevelaAI Flask Backend"),
        "message": "Backend is live 🚀"
    })

# -------------------------------
# AI Chat / Image Endpoint (Frontend uses this)
# -------------------------------
@app.route("/ai", methods=["POST"])
def ai_assistant():
    # Entire original logic here (unchanged)
    # Handles message/file input, LLM processing, expert modules, AI response, etc.
    try:
        session_id = get_session_id()
        session = SESSION_MEMORY.get(session_id, {"topic": None, "messages": []})

        # Input handling
        message = ""
        if "file" in request.files:
            uploaded = request.files["file"]
            data = uploaded.read()
            if uploaded.filename.endswith(".docx"):
                content = extract_text_from_docx(data)
            else:
                content = data.decode("utf-8", errors="ignore")
            message = f"Analyze the following document:\n\n{content}"
        else:
            payload = request.get_json(silent=True) or {}
            message = payload.get("message", "").strip()

        if not message:
            return jsonify(error_response("EMPTY_MESSAGE", "Message or file required.")), 400

        # Intent detection
        intent = classify_intent(message)
        if any(k in message.lower() for k in ["image", "draw", "generate", "picture"]):
            intent = "image_generation"

        if session["topic"] != intent:
            session["messages"] = []
            session["topic"] = intent

        # Image generation
        if intent == "image_generation":
            token = os.getenv("REPLICATE_API_TOKEN")
            if not token:
                return jsonify(error_response("REPLICATE_NOT_CONFIGURED", "Missing API key.")), 500

            prediction = create_replicate_prediction(
                version="musombi123/revelacodepro:9c8f1a2b3d4e",
                input_data={"prompt": message, "width": 1024, "height": 1024}
            )
            final = poll_replicate(prediction["id"], token)
            urls = final.get("output", [])
            return jsonify(enforce_base_schema(
                query=message,
                mode="image",
                data={"type": "image", "urls": urls},
                sources=[],
                meta={"provider": "replicate"}
            ))

        # Chat memory
        session["messages"].append({"role": "user", "content": message})
        session["messages"] = session["messages"][-MAX_HISTORY:]

        # Expert cooperation
        expert_payload = None
        if "law" in intent or "legal" in message.lower():
            expert_payload = analyze_legal_query(message)
        elif "medical" in intent or "medicine" in message.lower():
            expert_payload = analyze_medical_query(message)

        # Core AI processing
        ai_result = process_message(
            message=message,
            context=session["messages"],
            intent=intent,
            session_id=session_id
        )

        assistant_text = ai_result.get("response")
        if not assistant_text:
            raise RuntimeError("AI returned empty response")

        session["messages"].append({"role": "assistant", "content": assistant_text})
        session["messages"] = session["messages"][-MAX_HISTORY:]
        SESSION_MEMORY[session_id] = session

        wants_json = any(k in message.lower() for k in [
            "respond in json", "return json", "output json"
        ])

        data = extract_json(assistant_text) if wants_json else {"content": assistant_text}

        if expert_payload:
            data["expert_module"] = expert_payload

        return jsonify(enforce_base_schema(
            query=message,
            mode=intent,
            data=data,
            sources=[],
            meta={
                "ai_model": "llama-3.1-8b-instant",
                "memory": "topic-aware",
                "confidence": ai_result.get("confidence", "medium")
            }
        ))

    except Exception as e:
        app.logger.exception("AI request failed")
        return jsonify(error_response("SERVER_ERROR", str(e))), 500

# -------------------------------
# Streaming Endpoint
# -------------------------------
@app.route("/ai/stream", methods=["POST"])
def ai_stream():
    payload = request.get_json(silent=True) or {}
    message = payload.get("message", "").strip()

    if not message:
        return jsonify(error_response("EMPTY_MESSAGE", "Message required.")), 400

    session_id = get_session_id()
    session = SESSION_MEMORY.get(session_id, {"topic": None, "messages": []})

    session["messages"].append({"role": "user", "content": message})
    session["messages"] = session["messages"][-MAX_HISTORY:]
    SESSION_MEMORY[session_id] = session

    def generate():
        for chunk in get_ai_reply_streamed(session["messages"]):
            yield f"data: {chunk}\n\n"

    return Response(generate(), mimetype="text/event-stream")

# -------------------------------
# Voice Endpoints
# -------------------------------
@app.route("/voice", methods=["POST"])
def voice():
    if "audio" not in request.files:
        return jsonify({"error": "No audio provided"}), 400

    audio = request.files["audio"]
    audio_path = os.path.join(tempfile.gettempdir(), audio.filename)
    audio.save(audio_path)

    heard = transcribe_audio_file(audio_path)

    ai_result = process_message(
        message=heard,
        context=[],
        intent=classify_intent(heard),
        session_id=get_session_id()
    )

    response_text = ai_result.get("response", "")
    out_audio_path = text_to_speech_file(response_text)

    return jsonify({
        "heard": heard,
        "response": response_text,
        "audio_url": f"/voice/audio/{os.path.basename(out_audio_path)}"
    })

@app.route("/voice/audio/<filename>")
def serve_audio(filename):
    path = os.path.join(tempfile.gettempdir(), filename)
    if not os.path.exists(path):
        return jsonify({"error": "Audio not found"}), 404
    return send_file(path, mimetype="audio/wav")

# -------------------------------
# Health
# -------------------------------
@app.route("/health")
def health():
    return {"status": "ok"}

@app.route("/test-db")
def test_db():
    users_col.insert_one({"test": "db connected"})
    return {"status": "ok", "message": "MongoDB connected 🚀"}

# -------------------------------
# Run
# -------------------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
