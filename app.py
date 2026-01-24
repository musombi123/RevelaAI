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
from voice.voice_assistant import run_voice_assistant
from voice.voice_output import text_to_speech_file
# -------------------------------
# Core Utilities
# -------------------------------
from ai.system_prompt import SYSTEM_PROMPT
from ai.json_utils import extract_json, enforce_base_schema, error_response

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
# WhatsApp Webhook
# -------------------------------
from whatsapp_webhook import whatsapp_bp
app.register_blueprint(whatsapp_bp)

# -------------------------------
# 🧠 SESSION MEMORY
# -------------------------------
SESSION_MEMORY = {}
MAX_HISTORY = 10

def get_session_id():
    return request.headers.get("X-Session-ID", request.remote_addr)

# -------------------------------
# LLM Call (STREAMING)
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
# AI Chat / Image Endpoint
# -------------------------------
@app.route("/ai", methods=["POST"])
def ai_assistant():
    try:
        session_id = get_session_id()
        session = SESSION_MEMORY.get(session_id, {"topic": None, "messages": []})

        # -------------------------------
        # Input Handling
        # -------------------------------
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
            return jsonify(
                error_response("EMPTY_MESSAGE", "Message or file required.")
            ), 400

        # -------------------------------
        # Intent Detection
        # -------------------------------
        intent = classify_intent(message)

        if any(k in message.lower() for k in ["image", "draw", "generate", "picture"]):
            intent = "image_generation"

        if session["topic"] != intent:
            session["messages"] = []
            session["topic"] = intent

        # -------------------------------
        # 🎨 IMAGE GENERATION
        # -------------------------------
        if intent == "image_generation":
            token = os.getenv("REPLICATE_API_TOKEN")
            if not token:
                return jsonify(
                    error_response("REPLICATE_NOT_CONFIGURED", "Missing API key.")
                ), 500

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

        # -------------------------------
        # 🧠 CHAT MEMORY
        # -------------------------------
        session["messages"].append({"role": "user", "content": message})
        session["messages"] = session["messages"][-MAX_HISTORY:]

        # -------------------------------
        # EXPERT COOPERATION (NON-BLOCKING)
        # -------------------------------
        expert_payload = None

        if "law" in intent or "legal" in message.lower():
            expert_payload = analyze_legal_query(message)
        elif "medical" in intent or "medicine" in message.lower():
            expert_payload = analyze_medical_query(message)

        # -------------------------------
        # CORE AI PROCESSING
        # -------------------------------
        ai_result = process_message(
            message=message,
            context=session["messages"],
            intent=intent,
            session_id=session_id
        )

        assistant_text = ai_result.get("response")
        if not assistant_text:
            raise RuntimeError("AI returned empty response")

        session["messages"].append({
            "role": "assistant",
            "content": assistant_text
        })

        session["messages"] = session["messages"][-MAX_HISTORY:]
        SESSION_MEMORY[session_id] = session

        wants_json = any(k in message.lower() for k in [
            "respond in json", "return json", "output json"
        ])

        data = extract_json(assistant_text) if wants_json else {
            "content": assistant_text
        }

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
        return jsonify(
            error_response("SERVER_ERROR", str(e))
        ), 500

# -------------------------------
# STREAMING ENDPOINT
# -------------------------------
@app.route("/ai/stream", methods=["POST"])
def ai_stream():
    payload = request.get_json(silent=True) or {}
    message = payload.get("message", "").strip()

    if not message:
        return jsonify(
            error_response("EMPTY_MESSAGE", "Message required.")
        ), 400

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
# VOICE ASSISTANT ENDPOINT
# -------------------------------
@app.route("/voice", methods=["POST"])
def voice():
    payload = request.get_json(silent=True) or {}
    user_text = payload.get("text", "")

    heard, response = run_voice_assistant(user_text)

    return jsonify({
        "heard": heard,
        "response": response
    })


    # -------------------------------
    # AI PROCESSING
    # -------------------------------
    ai_result = process_message(
        message=heard,
        context=[],
        intent=classify_intent(heard),
        session_id=get_session_id()
    )

    response_text = ai_result.get("response", "")

    # -------------------------------
    # TEXT → SPEECH
    # -------------------------------
    audio_path = text_to_speech_file(response_text)

    return jsonify({
        "heard": heard,
        "response": response_text,
        "audio_url": f"/voice/audio/{os.path.basename(audio_path)}"
    })

# Serve generated audio files
@app.route("/voice/audio/<filename>")
def serve_audio(filename):
    path = os.path.join(tempfile.gettempdir(), filename)
    if not os.path.exists(path):
        return {"error": "Audio not found"}, 404
    return send_file(path, mimetype="audio/wav")

# -------------------------------
# Health
# -------------------------------
@app.route("/health")
def health():
    return {"status": "ok"}

# -------------------------------
# Run
# -------------------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
