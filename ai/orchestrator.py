# ai/orchestrator.py

from ai.system_state import SystemState
from ai.emotion import detect_emotion
from services.expert_law import analyze_legal_query
from services.expert_medicine import analyze_medical_query


class Orchestrator:
    def __init__(self, system_state: SystemState = None):
        self.system_state = system_state or SystemState()

    def process_prompt(self, message: str, context: list, intent: str = "general", session_id: str = None):

        emotion = detect_emotion(message)

        # ⚖️ Law Domain
        if intent == "law" and self.system_state.is_feature_active("law_intelligence"):
            response = analyze_legal_query(message)
            response.update({"emotion_detected": emotion, "domain": "law"})
            return response

        # 🩺 Medical Domain
        if intent == "medicine" and self.system_state.is_feature_active("medical_intelligence"):
            response = analyze_medical_query(message)
            response.update({"emotion_detected": emotion, "domain": "medicine"})
            return response

        # 🧠 General AI
        memory_context = context[-5:] if context else []
        memory_summary = " | ".join([m["content"] for m in memory_context]) if memory_context else ""

        if session_id:
            self.system_state.append_session_message(session_id, "user", message)

        processed = f"Processed (general AI): {message}"
        if memory_summary:
            processed += f" | Memory context: {memory_summary}"

        return {
            "response": processed,
            "emotion_detected": emotion,
            "domain": "general",
            "features_active": list(self.system_state.features.keys())
        }
