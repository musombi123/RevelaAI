# services/ai_service.py
from ai.orchestrator import Orchestrator
from ai.emotion import detect_emotion

# NEW domain handlers (drop-in, no breakage)
from ai.law import handle_legal_query
from ai.medicine import handle_medical_query

orchestrator = Orchestrator()

def process_message(message: str, session_messages: list, intent: str = "general"):
    """
    Phase One AI processing pipeline (EXTENDED):
    - Emotion detection
    - Intent-aware routing
    - Domain-safe handling (Law / Medicine)
    - Prompt orchestration fallback
    """

    emotion = detect_emotion(message)

    # -----------------------
    # ⚖️ Legal Intelligence
    # -----------------------
    if intent == "law":
        response = handle_legal_query(message)
        return {
            "response": response,
            "emotion_detected": emotion,
            "confidence": "medium",
            "domain": "law",
            "disclaimer": "Not a lawyer. Informational use only."
        }

    # -----------------------
    # 🩺 Medical Intelligence
    # -----------------------
    if intent == "medicine":
        response = handle_medical_query(message)
        return {
            "response": response,
            "emotion_detected": emotion,
            "confidence": "medium",
            "domain": "medicine",
            "disclaimer": "Not a medical professional. Consult a doctor."
        }

    # -----------------------
    # 🧠 General AI (DEFAULT)
    # -----------------------
    response = orchestrator.process_prompt(message, session_messages)

    return {
        "response": response,
        "emotion_detected": emotion,
        "confidence": "high",
        "domain": "general"
    }
