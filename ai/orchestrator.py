# ai/orchestrator.py
"""
Central orchestration for RevelaAI.
Handles multi-domain routing, memory integration, reasoning, and fallback.
"""

from ai.emotion import detect_emotion

class Orchestrator:
    def __init__(self):
        # Can extend later: memory, plugins, system state
        pass

    def process_prompt(self, message: str, context: list, intent: str = "general", session_id: str = None):
        """
        Core AI routing:
        - law → expert_law
        - medicine → expert_medicine
        - fallback → general echo / reasoning
        """
        emotion = detect_emotion(message)
        response_data = {"domain": "general", "response": f"Processed: {message}", "emotion": emotion}

        try:
            if intent == "law":
                from services.expert_law import analyze_legal_query
                response_data["response"] = analyze_legal_query(message)["summary"]
                response_data["domain"] = "law"

            elif intent == "medicine":
                from services.expert_medicine import analyze_medical_query
                response_data["response"] = analyze_medical_query(message)["overview"]
                response_data["domain"] = "medicine"

        except Exception as e:
            # Fallback to general AI
            response_data["response"] += f" [Fallback triggered due to: {e}]"

        return response_data
