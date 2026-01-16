# ai/medicine.py
"""
RevelaAI – Medical Intelligence Module
General medical explanations with safety boundaries.
"""

DISCLAIMER = (
    "This response is for general informational purposes only and does not "
    "constitute medical advice. Always consult a licensed healthcare professional."
)

def analyze_medical_query(query: str) -> dict:
    return {
        "domain": "medicine",
        "overview": f"General medical context related to: {query}",
        "important_notes": [
            "Symptoms vary between individuals",
            "Underlying conditions affect outcomes",
            "Online information cannot replace diagnosis"
        ],
        "recommendation": "Seek evaluation from a qualified healthcare professional",
        "confidence": "informational",
        "human_required": True,
        "disclaimer": DISCLAIMER
    }
