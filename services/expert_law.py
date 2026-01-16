# services/expert_law.py
from ai.orchestrator import Orchestrator
from ai.json_utils import enforce_base_schema

DISCLAIMER = "This is not legal advice."
orchestrator = Orchestrator()

def analyze_legal_query(query: str, context: list | None = None) -> dict:
    """
    High-level legal reasoning assistant using Orchestrator.
    """
    response = orchestrator.process_prompt(query, context or [])

    return enforce_base_schema(
        query=query,
        mode="law",
        data={
            "answer": response,
            "disclaimer": DISCLAIMER
        },
        sources=[],
        meta={
            "domain": "law",
            "confidence": "medium",
            "human_required": True
        }
    )
