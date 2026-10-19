"""Native FastAPI WhatsApp webhook verification and message handling."""
from __future__ import annotations

import logging
import os
from typing import Any

import requests
from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse
from starlette.concurrency import run_in_threadpool

router = APIRouter(tags=["WhatsApp"])
logger = logging.getLogger("revelaai.fastapi.whatsapp")

VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "revelacode_secure")
ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN")
PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
GRAPH_API_URL = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"


@router.get("/webhook/whatsapp")
async def verify_webhook(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return PlainTextResponse(challenge or "", status_code=200)
    return PlainTextResponse("Verification failed", status_code=403)


def decode_scripture(text: str) -> str:
    """Temporary decoder response; replace with the approved scripture service."""
    return f"📖 Revela AI decoded:\n{text}"


def send_whatsapp_message(to: str, message: str) -> dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": message},
    }
    response = requests.post(GRAPH_API_URL, headers=headers, json=payload, timeout=(3.05, 20))
    response.raise_for_status()
    body = response.json()
    return body if isinstance(body, dict) else {}


def _process_message(data: Any):
    try:
        entry = data["entry"][0]
        changes = entry["changes"][0]
        value = changes["value"]
        messages = value.get("messages")
        if not messages:
            from fastapi.responses import JSONResponse
            return JSONResponse({"status": "no message"}, status_code=200)
        message = messages[0]
        from_number = message["from"]
        text = message["text"]["body"]
        decoded_response = decode_scripture(text)
        send_whatsapp_message(from_number, decoded_response)
        from fastapi.responses import JSONResponse
        return JSONResponse({"status": "processed"}, status_code=200)
    except Exception as exc:
        logger.warning("WhatsApp webhook processing failed | error_type=%s", type(exc).__name__)
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "processing failed"}, status_code=500)


@router.post("/webhook/whatsapp")
async def receive_message(request: Request):
    try:
        data = await request.json()
    except Exception:
        return PlainTextResponse('{"error":"processing failed"}', status_code=500, media_type="application/json")
    return await run_in_threadpool(_process_message, data)
