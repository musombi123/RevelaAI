# services/expert_medicine.py
from ai.orchestrator import Orchestrator
from ai.json_utils import enforce_base_schema

DISCLAIMER = "This is not medical advice."

orchestrator = Orchestrator()

def analyze_medical_query(query: str, context: dict | None = None) -> dict:
    """
    General medical reasoning using the Orchestrator.
    """
    prompt = f"""
    You are an AI medical consultant.
    User Question:
    {query}

    Context:
    {context or "None"}

    Provide clear, general medical information.
    """
    response = orchestrator.process_prompt(prompt, session_messages=[])

    return enforce_base_schema(
        query=query,
        mode="medicine",
        data={
            "answer": response,
            "disclaimer": DISCLAIMER
        },
        sources=[],
        meta={
            "domain": "medicine",
            "confidence": "informational",
            "human_required": True
        }
    )
