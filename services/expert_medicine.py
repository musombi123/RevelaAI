# services/expert_medicine.py
from ai.orchestrator import run_reasoning_pipeline
from ai.json_utils import enforce_base_schema

def analyze_medical_question(question: str, context: dict = None) -> dict:
    """
    Provide medical guidance or summaries based on input.
    Not a substitute for professional medical advice.
    """
    prompt = f"""
    You are a medical assistant AI. Provide clear and safe guidance:
    Question: {question}
    Context: {context or 'No additional context.'}
    Only provide general information; recommend consulting a professional for personal advice.
    """
    
    # Run reasoning pipeline from orchestrator
    answer = run_reasoning_pipeline(prompt)
    
    return enforce_base_schema(
        query=question,
        mode="medical_analysis",
        data={"content": answer},
        sources=[],  # Add references if available
        meta={"expert_module": "medicine"}
    )
