# services/ai_service.py
from ai.orchestrator import Orchestrator
from ai.emotion import detect_emotion

orchestrator = Orchestrator()

def process_message(message: str, session_messages: list, intent: str = "general", session_id: str = None):
    """
    Advanced AI processing pipeline:
    - Detect emotion
    - Route intelligently based on intent
    - Expert module handling (law/medicine)
    - General AI fallback
    """
    emotion = detect_emotion(message)
    result = orchestrator.process_prompt(message, session_messages, intent=intent, session_id=session_id)

    # Attach confidence & disclaimers
    if result["domain"] == "law":
        result.update({"confidence": "medium", "disclaimer": "Not a lawyer. Informational use only."})
    elif result["domain"] == "medicine":
        result.update({"confidence": "medium", "disclaimer": "Not a medical professional. Consult a doctor."})
    else:
        result.update({"confidence": "high"})

    return result
