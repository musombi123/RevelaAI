import os
import io
from flask import Flask, request, jsonify, send_file, Response
from flask_cors import CORS
from dotenv import load_dotenv

# ✅ IMPORT FIX (ai_client is inside ai/)
from ai.ai_client import get_groq_client

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
# AI Core Imports
# -------------------------------
from ai.system_prompt import SYSTEM_PROMPT
from ai.intent_router import classify_intent
from ai.json_utils import (
    extract_json,
    enforce_base_schema,
    error_response
)

# -------------------------------
# LLM Call (STANDARD)
# -------------------------------
def get_ai_reply(user_message: str) -> str:
    client = get_groq_client()

    completion = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message}
        ],
        temperature=0.4,
        max_tokens=700
    )

    return completion.choices[0].message.content.strip()

# -------------------------------
# LLM Call (STREAMING)  ✅ ADDED
# -------------------------------
def get_ai_reply_streamed(user_message: str):
    client = get_groq_client()

    stream = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message}
        ],
        temperature=0.4,
        max_tokens=700,
        stream=True
    )

    for chunk in stream:
        delta = chunk.choices[0].delta
        if delta and delta.content:
            yield delta.content

# -------------------------------
# API Endpoint (STANDARD)
# -------------------------------
@app.route("/ai", methods=["POST"])
def ai_assistant():
    message = ""

    # ✅ FILE UPLOAD SUPPORT
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

    # Detect intent (metadata only)
    mode = classify_intent(message)

    raw_reply = get_ai_reply(message)

    # 🔒 JSON ONLY IF EXPLICITLY REQUESTED
    wants_json = any(
        phrase in message.lower()
        for phrase in [
            "respond in json",
            "return json",
            "output json",
            "give me json"
        ]
    )

    if wants_json:
        parsed = extract_json(raw_reply)
        data = parsed if parsed else {"content": raw_reply}
    else:
        data = {"content": raw_reply}

    # 📄 DOWNLOADABLE TEXT DOCUMENT
    wants_download = any(
        phrase in message.lower()
        for phrase in [
            "download",
            "export",
            "save as file",
            "give me a document"
        ]
    )

    if wants_download:
        buffer = io.BytesIO(raw_reply.encode("utf-8"))
        buffer.seek(0)

        return send_file(
            buffer,
            as_attachment=True,
            download_name="revelaai_document.txt",
            mimetype="text/plain"
        )

    response = enforce_base_schema(
        query=message,
        mode=mode,
        data=data,
        sources=[],
        meta={
            "ai_model": "llama-3.1-8b-instant",
            "reasoning_style": "neutral_scholarly",
            "limitations": [
                "Image generation is conceptual and descriptive",
                "External tools required for rendering visuals",
                "Interpretations vary by tradition"
            ]
        }
    )

    return jsonify(response)

# -------------------------------
# API Endpoint (STREAMING) ✅ ADDED
# -------------------------------
@app.route("/ai/stream", methods=["POST"])
def ai_stream():
    payload = request.get_json(silent=True) or {}
    message = payload.get("message", "").strip()

    if not message:
        return jsonify(error_response(
            "EMPTY_MESSAGE",
            "Message required for streaming."
        )), 400

    def generate():
        for chunk in get_ai_reply_streamed(message):
            yield f"data: {chunk}\n\n"

    return Response(generate(), mimetype="text/event-stream")

# -------------------------------
# Health Check
# -------------------------------
@app.route("/health")
def health():
    return {"status": "ok"}

# -------------------------------
# Run Server
# -------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
