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
from voice.transcribe import transcribe_audio_file  # <- ensure this exists

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
# Routes for Dynamic Features
# -------------------------------
@app.route("/features/chat", methods=["POST"])
def features_chat():
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
# Your Existing AI, Voice, and Expert Endpoints
# (Keep all your existing logic here, unchanged)
# -------------------------------
# ... ai_assistant(), ai_stream(), voice(), serve_audio(), health(), test_db() ...
# (You keep all of them exactly as in your original file)

# -------------------------------
# Run
# -------------------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
