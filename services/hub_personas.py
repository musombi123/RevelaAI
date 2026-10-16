"""Deterministic, free five-hub persona engine for RevelaAI.

No external model, provider key, or network request is used here.
The engine deliberately distinguishes measured camera facts from interpretation.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from collections import OrderedDict
from pathlib import Path
from threading import RLock
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MEMORY_FILE = ROOT / "data" / "hub_memory.json"
HUBS = {
    "mkulima": {"label": "Mkulima Hub", "aliases": ("farm", "farming", "agriculture", "shamba", "mkulima", "crop", "soil")},
    "biashara": {"label": "Biashara Hub", "aliases": ("business", "sales", "negotiation", "ceo", "biashara", "market", "profit")},
    "elimu": {"label": "Elimu / Teacher Hub", "aliases": ("education", "teacher", "student", "school", "elimu", "homework", "programming", "code", "learn")},
    "mahubiri": {"label": "Mahubiri / Theology Hub", "aliases": ("scripture", "bible", "theology", "sermon", "mahubiri", "prophecy", "prayer", "jesus", "verse")},
    "general": {"label": "General Mentor", "aliases": ("general", "mentor", "life", "advice", "help")},
}
LOCK = RLock()
CACHE: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()
CACHE_TTL = 90
CACHE_LIMIT = 256
MAX_MEMORY_ITEMS = 24
MAX_TEXT = 8000

HUB_GUIDANCE = {
    "mkulima": "Mkulima style: practical, grounded farming guidance; use both English and Kiswahili naturally when useful. Consider crop, growth stage, soil, rainfall, pests, irrigation, and local conditions. Never invent weather or guarantee yield.",
    "biashara": "Biashara style: decisive, respectful commercial mentor. Make assumptions explicit; consider customer, pricing, costs, margin, cash flow, negotiation leverage, and next measurable action. It is okay to disagree respectfully when the evidence suggests a better option.",
    "elimu": "Elimu style: excellent teacher. Explain the core concept in ordered steps, give one worked example, flag a common misconception, then ask one short check-for-understanding question. For programming, include a small precise example where useful.",
    "mahubiri": "Mahubiri style: warm pastoral and theological mentor. Distinguish Bible text, interpretation, and application; ask for a passage when needed; do not fabricate verses, prophecy fulfilment, or divine revelation. Prayer requests may receive a respectful prayer.",
    "general": "General mentor style: warm, candid, thoughtful, and cross-disciplinary. Connect hubs when relevant, explain uncertainty, use respectful disagreement when justified, and end with a practical next step. Do not claim supernatural powers or human feelings.",
}

def normalize_hub(value: Any, message: str = "") -> str:
    hub = re.sub(r"[^a-z]", "", str(value or "").lower())
    aliases = {
        "mkulima": "mkulima", "farming": "mkulima", "agriculture": "mkulima", "shamba": "mkulima", "farm": "mkulima",
        "biashara": "biashara", "business": "biashara", "sales": "biashara", "negotiation": "biashara",
        "elimu": "elimu", "teacher": "elimu", "education": "elimu", "programming": "elimu", "coding": "elimu",
        "mahubiri": "mahubiri", "theology": "mahubiri", "scripture": "mahubiri", "bible": "mahubiri", "sermon": "mahubiri", "prophecy": "mahubiri",
        "general": "general", "mentor": "general",
    }
    if hub in aliases:
        return aliases[hub]
    msg = str(message or "").lower()
    patterns = [
        ("mkulima", r"\b(farm|farming|agriculture|shamba|mkulima|crop|soil|irrigat|pest|mazao|udongo)\b"),
        ("biashara", r"\b(business|sales|negotiat|ceo|biashara|profit|margin|customer|market|revenue)\b"),
        ("mahubiri", r"\b(bible|scripture|theology|sermon|mahubiri|prophecy|prayer|jesus|psalm|verse)\b"),
        ("elimu", r"\b(education|teacher|student|school|elimu|homework|programming|code|learn|explain)\b"),
    ]
    for key, pattern in patterns:
        if re.search(pattern, msg):
            return key
    return "general"

def _load_memory() -> dict[str, Any]:
    try:
        raw = json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}

def _save_memory(memory: dict[str, Any]) -> None:
    MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp = MEMORY_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps(memory, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(MEMORY_FILE)

def _safe_key(user_id: str) -> str:
    # Do not put raw account identifiers into the JSON file.
    return hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:24]

def remember(user_id: str, hub: str, message: str, reply: str) -> None:
    if not user_id:
        return
    entry = {"at": int(time.time()), "user": message[:1200], "assistant": reply[:1600]}
    with LOCK:
        data = _load_memory()
        user_key = _safe_key(user_id)
        user_hubs = data.setdefault(user_key, {})
        items = user_hubs.setdefault(hub, [])
        if items and items[-1].get("user") == entry["user"]:
            items[-1] = entry
        else:
            items.append(entry)
        user_hubs[hub] = items[-MAX_MEMORY_ITEMS:]
        # Keep the local file bounded across sessions.
        if len(data) > 400:
            for key in list(data)[:len(data) - 400]:
                data.pop(key, None)
        _save_memory(data)

def recent_memory(user_id: str, hub: str) -> list[dict[str, Any]]:
    if not user_id:
        return []
    with LOCK:
        items = _load_memory().get(_safe_key(user_id), {}).get(hub, [])
        return items[-3:] if isinstance(items, list) else []

def _vision_summary(vision: Any, description: Any) -> str:
    text = str(description or "").strip()[:MAX_TEXT]
    if isinstance(vision, dict):
        objects = vision.get("objects") or vision.get("objectNames") or []
        if isinstance(objects, list):
            labels = []
            for item in objects[:20]:
                if isinstance(item, dict):
                    name = str(item.get("class") or item.get("label") or "").strip()[:60]
                    score = item.get("score")
                    if name:
                        confidence = f" ({round(float(score) * 100)}% confidence)" if isinstance(score, (int, float)) and 0 <= float(score) <= 1 else ""
                        labels.append(name + confidence)
                elif isinstance(item, str):
                    labels.append(item[:60])
            if labels:
                text = (text + " " if text else "") + "Detected labels: " + ", ".join(labels) + "."
        brightness = vision.get("brightness", vision.get("averageBrightness"))
        if isinstance(brightness, (int, float)):
            light = "dark" if brightness < 50 else "bright" if brightness > 200 else "moderately lit"
            text = (text + " " if text else "") + f"Measured brightness: {max(0, min(255, round(brightness)))}/255 ({light})."
        ocr = str(vision.get("text") or "").strip()[:500]
        if ocr:
            text = (text + " " if text else "") + "OCR text: " + ocr
        contours = vision.get("contourCount")
        if isinstance(contours, (int, float)):
            text = (text + " " if text else "") + f"Contour regions measured: {max(0, min(100000, int(contours)))}."
    return text[:MAX_TEXT]

def _respond(hub: str, message: str, vision_text: str, memory: list[dict[str, Any]]) -> str:
    msg = message.strip()
    low = msg.lower()
    guidance = HUB_GUIDANCE[hub]
    context = f"\n\nCamera scan supplied by the device: {vision_text}" if vision_text else ""
    if memory and not vision_text and re.search(r"\b(continue|what next|remember|as we discussed|previous topic|endelea|tuliendelea)\b", low):
        previous = str(memory[-1].get("user") or "").strip()
        if previous and previous.lower() != low:
            label = HUBS[hub]["label"]
            return f"Let’s continue from our recent {label} thread: you were working on “{previous[:180]}”. What has changed since then? {guidance}"
    if vision_text:
        object_terms = re.findall(r"(?:Detected labels:|objects?:)\s*([^.!?\n]+)", vision_text, flags=re.I)
        labels = object_terms[0].strip() if object_terms else ""
        dark = bool(re.search(r"brightness\s*[:=]?\s*(?:[0-4]?\d)(?:/255)?|\bdark\b", vision_text, re.I))
        ocr_match = re.search(r"(?:OCR text|text detected)\s*[:=]?\s*[“\"']?(.{1,350}?)[”\"']?(?:\.|$)", vision_text, re.I)
        ocr = ocr_match.group(1).strip(" \"'“”") if ocr_match else ""
        if hub == "mkulima":
            opening = "Nimeangalia vipimo vya kamera. " if re.search(r"\b(swahili|kiswahili|sw)\b", low) else "From the camera measurements, "
            reply = opening + (f"the local detector reports {labels}. " if labels else "I don't have reliable object labels in this scan yet. ")
            reply += "The scene appears dark, so move to better light before judging leaf colour or crop condition. " if dark else "Lighting measurements alone cannot diagnose crop health; show a clear close-up of the leaf, stem, or soil for a more useful check. "
            if ocr: reply += f"The text reader returned: “{ocr}”. "
            return reply + "Tell me the crop, its growth stage, and your county so I can tailor the next steps."
        if hub == "biashara":
            reply = "Camera scan received. " + (f"The local detector reports {labels}. " if labels else "No verified object labels were returned, so I won't guess what product is shown. ")
            if ocr: reply += f"Readable text: “{ocr}”. "
            reply += "For a product or shelf decision, confirm the item, price, unit cost, and customer segment; image brightness and contours are not sales evidence."
            return reply
        if hub == "elimu":
            reply = "Let's read the scan carefully. " + (f"The local detector labels: {labels}. " if labels else "The scanner measured image properties but did not provide verified object names. ")
            if ocr: reply += f"OCR text: “{ocr}”. "
            return reply + "The brightness and contour values describe pixels, not the meaning of the whole scene. What would you like to identify or learn from it?"
        if hub == "mahubiri":
            reply = "I can help examine the camera result thoughtfully. " + (f"The local detector labels: {labels}. " if labels else "I don't have verified object labels from this scan. ")
            if ocr: reply += f"The text reader returned: “{ocr}”. If this is a Bible page, please confirm the book, chapter, and verse before relying on OCR. "
            return reply + "I will distinguish what the scan actually reads from any theological interpretation."
        reply = "I can work from the scan's measurements, without pretending to see more than the tools detected. " + (f"Reported labels: {labels}. " if labels else "No semantic object labels were supplied. ")
        if ocr: reply += f"Text reading: “{ocr}”. "
        reply += "Brightness and contour counts are clues about the image, not proof of an object's identity."
        if dark: reply += " It is dark; add light or try the supported torch."
        if msg: reply += f"\n\nYour question: {msg[:600]}"
        return reply
    if re.search(r"\b(i disagree|argue|counterargument|debate|challenge)\b", low):
        return "Let's test the claim rather than defend a side automatically. I may disagree when the evidence or logic points elsewhere: state the claim, the strongest evidence for it, and the assumption you think is most secure. I'll examine counterexamples and tell you where my reasoning may be weak."
    if re.search(r"\b(pray|prayer|pray with me|dua)\b", low):
        return "Of course. May you find wisdom for the next decision, courage for what is difficult, compassion for the people involved, and peace while you work through what you cannot control. Amen. If you want, tell me the situation and I can shape a more specific prayer."
    if hub == "mkulima":
        sw = bool(re.search(r"\b(shamba|mazao|udongo|mvua|mkulima|kiswahili|kwa kiswahili)\b", low))
        opening = "Tufanye hili kwa vitendo." if sw else "Let's approach this as a practical farm decision."
        if re.search(r"\b(pest|disease|yellow leaves|wilt|mnyauko|wadudu|majani ya njano)\b", low):
            return opening + " Start by checking the crop and growth stage, which leaves are affected, soil moisture, recent rain/irrigation, and whether symptoms spread plant-to-plant. Avoid applying pesticides until the likely cause and label instructions are checked. Which crop and county are you in?"
        if re.search(r"\b(soil|udongo|fertili[sz]er|compost|manure|ph|nutrient)\b", low):
            return opening + " Check soil texture, drainage, pH, organic matter, and the crop's nutrient needs before choosing an amendment. A soil test is more reliable than guessing from colour alone. Tell me the crop, soil type, irrigation, and location."
        return opening + " I can help plan crop choice, planting, soil, pests, irrigation, and market timing. Share the crop, growth stage, county, water access, and your main constraint. I'll separate general guidance from location-specific facts that need verification."
    if hub == "biashara":
        if re.search(r"\b(margin|profit|sales|price|pricing|negotia|customer|cash flow|revenue)\b", low):
            return "Let's make the decision measurable. First establish selling price, unit cost, variable expenses, fixed costs, and the customer's alternative. Protect your walk-away point, trade concessions conditionally, and record the agreement. If you share the numbers, I can calculate the margin and propose a negotiation plan."
        return "Let's think like an operator, not just an optimist. Identify the customer, painful problem, offer, acquisition channel, unit economics, and next measurable experiment. I may challenge a plan if the cash flow or evidence does not support it. What outcome and deadline matter most?"
    if hub == "elimu":
        if re.search(r"\b(code|program|python|javascript|react|error|debug|algorithm)\b", low):
            return "Let's debug it systematically: reproduce the problem, read the exact error, isolate the smallest failing case, inspect inputs and state, then test one change at a time. Share the code and full error and I'll walk through the cause and a fix."
        return "I'll teach this in layers: (1) the central idea, (2) why it works, (3) a worked example, and (4) a common mistake to avoid. Tell me the topic and your current level so I can pitch the explanation correctly."
    if hub == "mahubiri":
        if re.search(r"\b(prophecy|daniel|revelation|666|beast|end times|eschatolog)\b", low):
            return "Let's begin with the biblical passage, its literary and historical context, and how related passages use the same symbol. Then we can compare interpretations and historical claims separately. I won't label a current event as prophetic fulfilment without evidence. Which passage should we examine first?"
        if re.search(r"\b(sermon|mahubiri|preach|homiletic)\b", low):
            return "A strong sermon can follow this structure: (1) read the passage in context, (2) identify its main claim, (3) explain the historical setting, (4) connect it to the wider biblical witness, (5) apply it compassionately, and (6) end with a clear invitation. Which text and audience are you preparing for?"
        return "Let's study the text carefully: read the whole paragraph, identify speaker and audience, compare parallel passages, then separate observation, interpretation, and application. Share the verse or topic and I'll help build a contextual study rather than inventing a quotation."
    # General mentor
    if re.search(r"\b(hello|hi|hey|habari|niaje)\b", low):
        return "Hey! I'm here with you. What are we working through today—your farm, a business decision, a learning challenge, a Bible question, or something else?"
    if re.search(r"\b(what do you see|describe this|camera|image|photo|scan)\b", low):
        return "I can answer from the measurements supplied by your device. If you attach a camera scan, I'll report its detected labels, brightness, contours, and any OCR text without guessing beyond the evidence."
    return "I'm with you. Let's make the next step clear and useful. Tell me the outcome you're aiming for, what you've tried, and the biggest constraint. I'll connect farming, business, learning, theology, or general problem-solving when it genuinely helps—and I'll be candid when I disagree."
    
def respond(message: str, hub: str = "general", user_id: str = "", vision: Any = None, vision_description: str = "") -> dict[str, Any]:
    message = str(message or "").strip()[:MAX_TEXT]
    hub = normalize_hub(hub, message)
    vision_text = _vision_summary(vision, vision_description)
    user_id = str(user_id or "anonymous")[:256]
    cache_key = hashlib.sha256(json.dumps([_safe_key(user_id), hub, message.lower(), vision_text], ensure_ascii=False).encode("utf-8")).hexdigest()
    now = time.time()
    with LOCK:
        cached = CACHE.get(cache_key)
        if cached and now - cached[0] < CACHE_TTL:
            CACHE.move_to_end(cache_key)
            reply = cached[1]["reply"]
            remember(user_id, hub, message, reply)
            return {**cached[1], "cached": True}
    memory = recent_memory(user_id, hub)
    reply = _respond(hub, message, vision_text, memory)
    result = {"ok": True, "hub": hub, "hubLabel": HUBS[hub]["label"], "reply": reply, "engine": "regex-cache-local-json", "paidModel": False, "visionUsed": bool(vision_text), "visionDescription": vision_text, "cached": False}
    with LOCK:
        CACHE[cache_key] = (now, result)
        CACHE.move_to_end(cache_key)
        while len(CACHE) > CACHE_LIMIT:
            CACHE.popitem(last=False)
    remember(user_id, hub, message, reply)
    return result
