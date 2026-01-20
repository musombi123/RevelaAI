from flask import Blueprint, request, jsonify
import requests
import os

whatsapp_bp = Blueprint("whatsapp_webhook", __name__)

# =========================
# CONFIG (ENV VARIABLES)
# =========================
VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "revelacode_secure")
ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN")
PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")

GRAPH_API_URL = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"


# =========================
# WEBHOOK VERIFICATION
# =========================
@whatsapp_bp.route("/webhook/whatsapp", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200

    return "Verification failed", 403


# =========================
# RECEIVE WHATSAPP MESSAGES
# =========================
@whatsapp_bp.route("/webhook/whatsapp", methods=["POST"])
def receive_message():
    data = request.get_json()

    try:
        entry = data["entry"][0]
        changes = entry["changes"][0]
        value = changes["value"]
        messages = value.get("messages")

        if not messages:
            return jsonify(status="no message"), 200

        message = messages[0]
        from_number = message["from"]
        text = message["text"]["body"]

        # ---- CALL YOUR DECODE LOGIC HERE ----
        decoded_response = decode_scripture(text)

        send_whatsapp_message(from_number, decoded_response)

        return jsonify(status="processed"), 200

    except Exception as e:
        print("Webhook error:", e)
        return jsonify(error="processing failed"), 500


# =========================
# SEND MESSAGE BACK
# =========================
def send_whatsapp_message(to, message):
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": message}
    }

    response = requests.post(GRAPH_API_URL, headers=headers, json=payload)
    return response.json()


# =========================
# PLACEHOLDER DECODE LOGIC
# =========================
def decode_scripture(text):
    """
    Replace this with your real RevelaCode decode engine.
    """
    return f"📖 Revela AI decoded:\n{text}"
