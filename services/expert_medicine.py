# services/expert_medicine.py
from ai.orchestrator import Orchestrator
from ai.json_utils import enforce_base_schema

DISCLAIMER = "This is not medical advice."
orchestrator = Orchestrator()

def analyze_medical_query(query: str, context: list | None = None) -> dict:
    """
    High-level medical reasoning assistant using Orchestrator.
    """
    response = orchestrator.process_prompt(query, context or [])

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
