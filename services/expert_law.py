# services/expert_law.py
from ai.orchestrator import run_reasoning_pipeline
from ai.json_utils import enforce_base_schema

def analyze_legal_question(question: str, context: dict = None) -> dict:
    """
    Provide legal guidance or summaries based on the input question.
    Not a substitute for a licensed lawyer.
    """
    prompt = f"""
    You are a legal assistant AI. Answer clearly and professionally:
    Question: {question}
    Context: {context or 'No additional context.'}
    Provide accurate and concise explanations.
    """
    
    # Run reasoning pipeline from orchestrator
    answer = run_reasoning_pipeline(prompt)
    
    return enforce_base_schema(
        query=question,
        mode="legal_analysis",
        data={"content": answer},
        sources=[],  # Add references if available
        meta={"expert_module": "law"}
    )
