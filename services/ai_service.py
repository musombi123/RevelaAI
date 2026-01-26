# services/ai_service.py

from ai.ai_client import get_groq_client
from ai.system_prompt import SYSTEM_PROMPT
from ai.orchestrator import Orchestrator  # <-- import the orchestrator

# Instantiate once (can be global)
orchestrator = Orchestrator()


# ---------------------------------------
# ✅ ADD THIS HERE (BEFORE process_message)
def build_source_prompt(query: str, sources: list[dict]) -> str:
    prompt = f"""Using ONLY these sources, answer the question.

Query: {query}

Sources:
"""
    for i, s in enumerate(sources, start=1):
        title = s.get("title", "Untitled")
        url = s.get("url", "")
        snippet = s.get("snippet", "") or s.get("full_text", "")
        prompt += f"\n{i}) {title} - {url}\n{snippet}\n"

    prompt += """
Rules:
- Use citations like [1], [2] after each claim.
- If sources don’t contain enough info, say: "Not enough info from sources."
- Do NOT add outside knowledge.
"""
    return prompt


# ---------------------------------------
# ✅ KEEP ONLY ONE process_message
# ---------------------------------------
def process_message(
    message: str,
    context: list,
    intent: str = "general",
    session_id: str | None = None
) -> dict:
    """
    Core human-like AI reasoning engine.
    Answers any question, reasons freely, Real human style.
    """

    client = get_groq_client()

    # Build conversation (ChatGPT-compatible)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if context:
        messages.extend(context[-10:])
    messages.append({"role": "user", "content": message})

    # 🧠 Orchestrator metadata
    orchestrator_data = orchestrator.process_prompt(
        message=message,
        context=context,
        intent=intent,
        session_id=session_id
    )

    completion = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=messages,
        temperature=0.7,
        max_tokens=800
    )

    reply = completion.choices[0].message.content.strip()

    return {
        "response": reply,
        "confidence": "high",
        "intent": intent,
        "orchestrator": orchestrator_data
    }
