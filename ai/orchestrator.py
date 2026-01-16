# ai/orchestrator.py
"""
Neutral orchestrator.
Delegates all reasoning to the core AI engine.
No hard-coded responses. No stubs.
"""

from ai.emotion import detect_emotion


class Orchestrator:
    def __init__(self):
        pass

    def process_prompt(
        self,
        message: str,
        context: list,
        intent: str = "general",
        session_id: str | None = None
    ) -> dict:
        """
        Orchestrator is now metadata-only.
        Reasoning happens in services.ai_service.
        """

        emotion = detect_emotion(message)

        return {
            "domain": intent or "general",
            "emotion": emotion
            # ❗ NO response text here
        }
