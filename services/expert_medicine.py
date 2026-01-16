# services/expert_medicine.py

from ai.json_utils import enforce_base_schema

DISCLAIMER = "This is not medical advice."

def analyze_medical_query(query: str, context: list | None = None) -> dict:
    """
    Basic medical reasoning assistant (no Orchestrator dependency).
    """

    # Simple placeholder logic (safe + extensible)
    answer = f"Medical analysis result for: {query}"

    return enforce_base_schema(
        query=query,
        mode="medicine",
        data={
            "answer": answer,
            "disclaimer": DISCLAIMER
        },
        sources=[],
        meta={
            "domain": "medicine",
            "confidence": "informational",
            "human_required": True
        }
    )
