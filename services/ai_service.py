# services/ai_service.py
from ai.orchestrator import Orchestrator
from ai.emotion import detect_emotion

orchestrator = Orchestrator()

def process_message(message: str, session_messages: list):
    """
    Phase One AI processing pipeline:
    - Emotion detection
    - Prompt orchestration
    - Multi-step reasoning (placeholder)
    """
    emotion = detect_emotion(message)
    response = orchestrator.process_prompt(message, session_messages)
    return {"response": response, "emotion_detected": emotion, "confidence": "high"}
