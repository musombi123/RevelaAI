# ai/system_state.py

from typing import Dict, Any

class SystemState:
    """
    Tracks the AI's capabilities, active features, and session-aware memory flags.
    """

    def __init__(self):
        # Core features installed
        self.features: Dict[str, bool] = {
            "emotion_detection": True,
            "law_intelligence": True,
            "medical_intelligence": True,
            "memory_tracking": True,
            "online_fetching": True,
            "image_generation": True,
        }
        # Session-level awareness
        self.sessions: Dict[str, Dict[str, Any]] = {}
        # System meta info
        self.meta: Dict[str, Any] = {
            "version": "1.2.0",
            "last_update": "2026-01-16",
            "developer": "Musombi William",
        }

    def set_session_topic(self, session_id: str, topic: str):
        if session_id not in self.sessions:
            self.sessions[session_id] = {"topic": topic, "history": []}
        else:
            self.sessions[session_id]["topic"] = topic

    def append_session_message(self, session_id: str, role: str, content: str):
        if session_id not in self.sessions:
            self.sessions[session_id] = {"topic": None, "history": []}
        self.sessions[session_id]["history"].append({"role": role, "content": content})

    def get_session_history(self, session_id: str):
        return self.sessions.get(session_id, {}).get("history", [])

    def is_feature_active(self, feature_name: str) -> bool:
        return self.features.get(feature_name, False)

    def activate_feature(self, feature_name: str):
        self.features[feature_name] = True

    def deactivate_feature(self, feature_name: str):
        self.features[feature_name] = False
