import os
import time
import requests
from flask import Flask, request, jsonify, Response
from flask_cors import CORS
from dotenv import load_dotenv

# -------------------------------
# Newly added imports for services and AI modules
# -------------------------------
from ai.ai_client import get_groq_client, create_replicate_prediction
from ai.intent_router import classify_intent
from services.ai_service import process_message
from services.memory_service import remember_item, forget_item
from services.expert_law import analyze_legal_query
from services.expert_medicine import analyze_medical_query
from ai.docx_utils import extract_text_from_docx

# -------------------------------
# Existing imports
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
# Poll Replicate Prediction
# -------------------------------
def poll_replicate(prediction_id, token, timeout=60):
    headers = {"Authorization": f"Token {token}"}
    url = f"https://api.replicate.com/v1/predictions/{prediction_id}"
    start = time.time()
    while True:
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        prediction = r.json()
        if prediction["status"] in ["succeeded", "failed"]:
            return prediction
        if time.time() - start > timeout:
            raise TimeoutError("Image generation timed out")
        time.sleep(2)

# -------------------------------
# Helper: Fetch online info
# -------------------------------
def fetch_online_data(query: str) -> str:
    try:
        resp = requests.get(f"https://api.duckduckgo.com/?q={query}&format=json", timeout=5)
        resp.raise_for_status()
        results = resp.json().get("AbstractText", "")
        return results or "No online data found for your query."
    except Exception:
        return "Failed to fetch online data."

# -------------------------------
# API Endpoint
# -------------------------------
@app.route("/ai", methods=["POST"])
def ai_assistant():
    session_id = get_session_id()
    session = SESSION_MEMORY.get(session_id, {"topic": None, "messages": []})

    message = ""
    if "file" in request.files:
        uploaded_file = request.files["file"]
        try:
            file_bytes = uploaded_file.read()
            if uploaded_file.filename.endswith(".docx"):
                content = extract_text_from_docx(file_bytes)
            else:
                content = file_bytes.decode("utf-8", errors="ignore")
            message = f"Analyze and work with the following document:\n\n{content}"
        except Exception:
            return jsonify(error_response("FILE_READ_ERROR", "Unable to read uploaded file.")), 400
    else:
        payload = request.get_json(silent=True) or {}
        message = payload.get("message", "").strip()

    if not message:
        return jsonify(error_response("EMPTY_MESSAGE", "Please provide a message or upload a document.")), 400

    # -------------------------------
    # Intent & Topic Control
    # -------------------------------
    current_topic = classify_intent(message)
    if any(word in message.lower() for word in ["image", "draw", "generate", "picture", "illustrate"]):
        current_topic = "image_generation"

    if session["topic"] != current_topic:
        session["messages"] = []
        session["topic"] = current_topic

    # -------------------------------
    # 🎨 IMAGE / DESIGN (REPLICATE)
    # -------------------------------
    if current_topic == "image_generation":
        token = os.environ.get("REPLICATE_API_TOKEN")
        if not token:
            return jsonify(error_response("REPLICATE_NOT_CONFIGURED", "Replicate API key missing.")), 500

        try:
            prediction = create_replicate_prediction(
                version="revlacodepro/musombiwilliamworks",
                input_data={"prompt": message, "width": 1024, "height": 1024, "num_outputs": 3}
            )
            final_prediction = poll_replicate(prediction["id"], token)
            output_urls = [item["image"] for item in final_prediction.get("output", [])]
        except Exception as e:
            return jsonify(error_response("IMAGE_GENERATION_FAILED", str(e))), 500

        SESSION_MEMORY[session_id] = session

        return jsonify(enforce_base_schema(
            query=message,
            mode=current_topic,
            data={"type": "image", "urls": output_urls},
            sources=[],
            meta={"provider": "replicate"}
        ))

    # -------------------------------
    # TEXT RESPONSE (WITH MEMORY + EXPERT MODULES)
    # -------------------------------
    session["messages"].append({"role": "user", "content": message})
    session["messages"] = session["messages"][-MAX_HISTORY:]

    # Expert Law / Medicine Handling
    expert_response = None
    if "law" in current_topic or "legal" in message.lower():
        expert_response = analyze_legal_query(message)
    elif "medical" in current_topic or "medicine" in message.lower():
        expert_response = analyze_medical_query(message)

    # Online fetch if requested
    if "search online" in message.lower() or "look up" in message.lower():
        online_data = fetch_online_data(message)
        message += f"\n\n[Online info]: {online_data}"

    # Core AI processing
    raw_reply_data = process_message(message, session["messages"])
    session["messages"].append({"role": "assistant", "content": raw_reply_data["response"]})
    session["messages"] = session["messages"][-MAX_HISTORY:]
    SESSION_MEMORY[session_id] = session

    wants_json = any(p in message.lower() for p in ["respond in json", "return json", "output json", "give me json"])
    data = extract_json(raw_reply_data["response"]) if wants_json else {"content": raw_reply_data["response"]}
    if expert_response:
        data["expert_module"] = expert_response

    return jsonify(enforce_base_schema(
        query=message,
        mode=current_topic,
        data=data,
        sources=[],
        meta={
            "ai_model": "llama-3.1-8b-instant",
            "memory": "topic-aware",
            "confidence": raw_reply_data.get("confidence", "medium")
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
# Health
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
