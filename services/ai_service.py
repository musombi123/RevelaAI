from ai.ai_client import ask_mvi
from ai.system_prompt import SYSTEM_PROMPT
from ai.orchestrator import Orchestrator

# Instantiate once
orchestrator = Orchestrator()


# --------------------------------------------------
# Build source prompt
# --------------------------------------------------

def build_source_prompt(query: str, sources: list[dict]) -> str:
    prompt = f"""Using ONLY these sources, answer the question.

Query:
{query}

Sources:
"""

    for i, s in enumerate(sources, start=1):
        title = s.get("title", "Untitled")
        url = s.get("url", "")
        snippet = s.get("snippet", "") or s.get("full_text", "")

        prompt += f"""

{i}) {title}
{url}

{snippet}
"""

    prompt += """

Rules:
- Use citations like [1], [2].
- If the sources are insufficient, say:
  "Not enough information from sources."
- Do not invent facts.
"""

    return prompt


# --------------------------------------------------
# Main AI Pipeline
# --------------------------------------------------

def process_message(
    message: str,
    context: list = None,
    intent: str = "general",
    session_id: str | None = None,
) -> dict:

    context = context or []

    # Run orchestrator
    orchestrator_data = orchestrator.process_prompt(
        message=message,
        context=context,
        intent=intent,
        session_id=session_id,
    )

    # Ask MVI-AI
    result = ask_mvi(
        text=message,
        system_prompt=SYSTEM_PROMPT,
        session_id=session_id,
    )

    if not result.get("success", False):
        return {
            "response": result.get(
                "response",
                result.get("error", "Failed to contact MVI-AI."),
            ),
            "confidence": "low",
            "intent": intent,
            "emotion": "unknown",
            "orchestrator": orchestrator_data,
        }

    return {
        "response": result.get("response", ""),
        "confidence": "high",
        "intent": result.get("intent", intent),
        "emotion": result.get("emotion", "unknown"),
        "session_id": result.get("session_id", session_id),
        "orchestrator": orchestrator_data,
    }