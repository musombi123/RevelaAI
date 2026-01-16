# services/ai_service.py
from ai.orchestrator import Orchestrator
from ai.emotion import detect_emotion

# Use your current Orchestrator (basic, no injected handlers)
orchestrator = Orchestrator()

def process_message(message: str, session_messages: list, intent: str = "general"):
    """
    Basic AI processing pipeline:
    - Emotion detection
    - General prompt processing
    """
    emotion = detect_emotion(message)

    # Only general AI is used
    response = orchestrator.process_prompt(message, session_messages)

    return {
        "response": response,
        "emotion_detected": emotion,
        "confidence": "high",
        "domain": "general"
    }
