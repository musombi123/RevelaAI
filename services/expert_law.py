# services/expert_law.py
from ai.orchestrator import Orchestrator
from ai.json_utils import enforce_base_schema

DISCLAIMER = "This is not legal advice."

orchestrator = Orchestrator()

def analyze_legal_query(query: str, context: dict | None = None) -> dict:
    """
    High-level legal reasoning using the Orchestrator.
    """
    prompt = f"""
    You are an AI legal analyst.
    User Question:
    {query}

    Context:
    {context or "None"}

    Be precise, structured, and neutral.
    Avoid giving definitive legal judgments.
    """
    response = orchestrator.process_prompt(prompt, session_messages=[])
    
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
