import os
import io
import requests
from flask import Flask, request, jsonify, send_file, Response
from flask_cors import CORS
from dotenv import load_dotenv

from ai.ai_client import get_groq_client
from ai.system_prompt import SYSTEM_PROMPT
from ai.intent_router import classify_intent
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
# 🧠 SESSION MEMORY (Topic-Aware)
# -------------------------------
SESSION_MEMORY = {}
MAX_HISTORY = 10

def get_session_id():
    return request.headers.get("X-Session-ID", request.remote_addr)

# -------------------------------
# LLM Call (STANDARD)
# -------------------------------
def get_ai_reply_with_memory(session_messages):
    client = get_groq_client()

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(session_messages)

    completion = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=messages,
        temperature=0.4,
        max_tokens=700
    )

    return completion.choices[0].message.content.strip()

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
# API Endpoint
# -------------------------------
@app.route("/ai", methods=["POST"])
def ai_assistant():
    session_id = get_session_id()

    session = SESSION_MEMORY.get(session_id, {
        "topic": None,
        "messages": []
    })

    message = ""

    # -------------------------------
    # FILE UPLOAD
    # -------------------------------
    if "file" in request.files:
        uploaded_file = request.files["file"]
        try:
            content = uploaded_file.read().decode("utf-8", errors="ignore")
            message = f"Analyze and work with the following document:\n\n{content}"
        except Exception:
            return jsonify(error_response(
                "FILE_READ_ERROR",
                "Unable to read uploaded file."
            )), 400
    else:
        payload = request.get_json(silent=True) or {}
        message = payload.get("message", "").strip()

    if not message:
        return jsonify(error_response(
            "EMPTY_MESSAGE",
            "Please provide a message or upload a document."
        )), 400

    # -------------------------------
    # Intent & Topic Control
    # -------------------------------
    current_topic = classify_intent(message)

    if session["topic"] != current_topic:
        session["messages"] = []
        session["topic"] = current_topic

    # -------------------------------
    # 🎨 IMAGE / DESIGN (REPLICATE)
    # -------------------------------
    if current_topic in ["image_generation", "graphic_design"]:
        token = os.environ.get("REPLICATE_API_TOKEN")
        if not token:
            return jsonify(error_response(
                "REPLICATE_NOT_CONFIGURED",
                "Replicate API key missing."
            )), 500

        headers = {
            "Authorization": f"Token {token}",
            "Content-Type": "application/json"
        }

        payload = {
            # ✅ VALID Replicate SDXL model version
            "version": "ac732df83cea7fff18b8472768c88ad041fa750ff7682a21b0ed9b3af2f5c8c4",
            "input": {
                "prompt": message,
                "width": 1024,
                "height": 1024,
                "num_outputs": 1
            }
        }

        try:
            r = requests.post(
                "https://api.replicate.com/v1/predictions",
                headers=headers,
                json=payload,
                timeout=30
            )
            r.raise_for_status()
            prediction = r.json()
        except Exception as e:
            return jsonify(error_response(
                "IMAGE_GENERATION_FAILED",
                str(e)
            )), 500

        SESSION_MEMORY[session_id] = session

        return jsonify(enforce_base_schema(
            query=message,
            mode=current_topic,
            data={
                "type": "image",
                "prediction_id": prediction["id"],
                "status": prediction["status"],
                "poll_url": prediction["urls"]["get"]
            },
            sources=[],
            meta={"provider": "replicate"}
        ))

    # -------------------------------
    # TEXT RESPONSE (WITH MEMORY)
    # -------------------------------
    session["messages"].append({"role": "user", "content": message})
    session["messages"] = session["messages"][-MAX_HISTORY:]

    raw_reply = get_ai_reply_with_memory(session["messages"])

    session["messages"].append({"role": "assistant", "content": raw_reply})
    session["messages"] = session["messages"][-MAX_HISTORY:]

    SESSION_MEMORY[session_id] = session

    wants_json = any(p in message.lower() for p in [
        "respond in json", "return json", "output json", "give me json"
    ])

    data = extract_json(raw_reply) if wants_json else {"content": raw_reply}

    return jsonify(enforce_base_schema(
        query=message,
        mode=current_topic,
        data=data,
        sources=[],
        meta={
            "ai_model": "llama-3.1-8b-instant",
            "memory": "topic-aware"
        }
    ))

# -------------------------------
# STREAMING ENDPOINT
# -------------------------------
@app.route("/ai/stream", methods=["POST"])
def ai_stream():
    payload = request.get_json(silent=True) or {}
    message = payload.get("message", "").strip()

    if not message:
        return jsonify(error_response(
            "EMPTY_MESSAGE",
            "Message required."
        )), 400

    session_id = get_session_id()
    session = SESSION_MEMORY.get(session_id, {
        "topic": None,
        "messages": []
    })

    session["messages"].append({"role": "user", "content": message})
    session["messages"] = session["messages"][-MAX_HISTORY:]
    SESSION_MEMORY[session_id] = session

    def generate():
        for chunk in get_ai_reply_streamed(session["messages"]):
            yield f"data: {chunk}\n\n"

    return Response(generate(), mimetype="text/event-stream")

# -------------------------------
# Health
# -------------------------------
@app.route("/health")
def health():
    return {"status": "ok"}

# -------------------------------
# Run Server (Local / Fallback)
# -------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
