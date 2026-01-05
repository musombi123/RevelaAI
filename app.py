import os
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from groq import Groq

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
# Groq Client (SAFE)
# -------------------------------
def get_groq_client():
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not set")
    return Groq(api_key=api_key)

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
# LLM Call
# -------------------------------
def get_ai_reply(user_message: str) -> str:
    client = get_groq_client()  # ✅ FIX: create client here

    completion = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    user_message
                    + "\n\nIMPORTANT: If a structured response is required, "
                      "respond ONLY with valid JSON."
                )
            }
        ],
        temperature=0.4,
        max_tokens=700
    )

    return completion.choices[0].message.content.strip()

# -------------------------------
# API Endpoint
# -------------------------------
@app.route("/ai", methods=["POST"])
def ai_assistant():
    payload = request.get_json(silent=True) or {}
    message = payload.get("message", "").strip()

    if not message:
        return jsonify(error_response(
            "EMPTY_MESSAGE",
            "Please provide a message."
        )), 400

    # Detect domain / intent
    mode = classify_intent(message)

    # Get raw model output
    raw_reply = get_ai_reply(message)

    # Modes that REQUIRE structured JSON
    structured_modes = [
        "prophecy_analysis",
        "verse_exegesis",
        "scripture_lookup",
        "theological_comparison"
    ]

    if mode in structured_modes:
        data = extract_json(raw_reply)

        if not data:
            return jsonify(error_response(
                "INVALID_AI_RESPONSE",
                "The AI response could not be parsed as valid JSON."
            )), 500
    else:
        data = {
            "content": raw_reply
        }

    # Enforce RevelaAI base response schema
    response = enforce_base_schema(
        query=message,
        mode=mode,
        data=data,
        sources=[],
        meta={
            "ai_model": "llama-3.1-8b-instant",
            "reasoning_style": "neutral_scholarly",
            "limitations": [
                "Interpretations vary by tradition",
                "Some conclusions are historically or theologically debated"
            ]
        }
    )

    return jsonify(response)

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
