"""
RevelaAI v2.0 local global brain.
Rule-based hub selection and response scaffolding; no model/provider/API calls.
This module is deliberately honest about the limits of deterministic reasoning.
"""
from __future__ import annotations

import re
from typing import Any

HUBS: dict[str, dict[str, Any]] = {
    "mkulima": {
        "label": "Mkulima",
        "description": "Agriculture, crops, soil, livestock, water, pests and farm markets.",
        "keywords": re.compile(r"\b(farm|farmer|farming|crop|maize|corn|beans|soil|irrigat|harvest|livestock|poultry|dairy|pest|fertili[sz]er|shamba|mkulima|rainfall|seedlings?)\b", re.I),
        "method": "Diagnose the crop or livestock, growth stage, local conditions, visible symptoms, available inputs, cost and risk before recommending an intervention.",
    },
    "biashara": {
        "label": "Biashara",
        "description": "Business strategy, pricing, sales, negotiation, operations and cash flow.",
        "keywords": re.compile(r"\b(business|biashara|sales|revenue|profit|margin|customer|market(ing)?|price|pricing|negotia|contract|cash flow|stock|inventory|startup|tender|invoice|costs?)\b", re.I),
        "method": "Quantify the customer, problem, offer, acquisition channel, unit economics, cash timing, alternatives and walk-away threshold.",
    },
    "elimu": {
        "label": "Elimu",
        "description": "Teaching, learning, curriculum, study support and school operations.",
        "keywords": re.compile(r"\b(teach|teacher|student|school|classroom|learn|learning|lesson|exam|curriculum|cbc|elimu|timetable|assessment|homework|education|explain like|study plan)\b", re.I),
        "method": "Start with the learner's level, state the objective, explain the concept, demonstrate a worked example, check understanding and adapt the next step.",
    },
    "mahubiri": {
        "label": "Mahubiri",
        "description": "Sermons, Bible study, theology, Scripture and pastoral reflection.",
        "keywords": re.compile(r"\b(bible|biblical|scripture|verse|jesus|christ|god|sermon|preach|preaching|theolog|mahubiri|prayer|pray|sabbath|prophecy|prophetic|kjv|niv|psalm|gospel|church|faith)\b", re.I),
        "method": "Read the passage in context, identify genre and historical setting, compare related passages, distinguish text from interpretation, then draw a responsible practical application.",
    },
    "general": {
        "label": "General",
        "description": "Cross-domain reasoning, coding, engineering, creativity and everyday problem-solving.",
        "keywords": re.compile(r"$^"),
        "method": "Define the goal, constraints, evidence, available options, trade-offs and the smallest useful test.",
    },
}

EMOTION_TERMS = {
    "distressed": ("overwhelmed", "hopeless", "lonely", "scared", "can't cope", "cannot cope", "exhausted", "stressed", "nimechoka", "ninaumia"),
    "frustrated": ("angry", "furious", "frustrated", "unfair", "annoyed", "fed up", "nimekasirika"),
    "joyful": ("happy", "excited", "grateful", "amazing", "proud", "nimefurahi", "asante sana"),
    "uncertain": ("confused", "not sure", "worried", "stuck", "uncertain", "sina uhakika"),
}


def detect_emotion(text: str) -> str:
    """A small transparent text heuristic, not a claim to read inner feelings."""
    value = str(text or "").lower()
    found = [(sum(term in value for term in terms), name) for name, terms in EMOTION_TERMS.items()]
    count, label = max(found, default=(0, "neutral"))
    return label if count else "neutral"


def route_hub(message: str, preferred_hub: str = "auto") -> tuple[str, str]:
    """Resolve explicit hub first; otherwise select the strongest keyword match."""
    requested = str(preferred_hub or "auto").strip().lower().replace("-", "").replace("_", "")
    aliases = {"farm": "mkulima", "agriculture": "mkulima", "business": "biashara",
               "education": "elimu", "teacher": "elimu", "theology": "mahubiri",
               "sermon": "mahubiri", "faith": "mahubiri", "auto": "auto"}
    requested = aliases.get(requested, requested)
    if requested in HUBS and requested != "general":
        return requested, "explicit hub selected"
    if requested == "general":
        return "general", "General hub explicitly selected"
    scores = {key: len(config["keywords"].findall(str(message or ""))) for key, config in HUBS.items()}
    scores["general"] = 0
    winner = max(scores, key=scores.get)
    if scores[winner] > 0:
        return winner, "keyword routing matched " + HUBS[winner]["label"]
    return "general", "no specialist keyword match; using General"


def _empathy_opening(emotion: str) -> str:
    return {
        "distressed": "That sounds like a lot to carry. We can break it into manageable steps without pretending the problem is simple.",
        "frustrated": "I hear the frustration. Let's separate what is known, what is blocked, and what can change next.",
        "joyful": "That's encouraging. Let's turn that momentum into a clear next step.",
        "uncertain": "It's reasonable to want clarity. Let's make the assumptions visible and test them one at a time.",
        "neutral": "Let's work through this clearly and practically.",
    }.get(emotion, "Let's work through this clearly and practically.")


def respond_local(message: str, preferred_hub: str = "auto", context: list | None = None) -> dict[str, Any]:
    """Return deterministic guidance with a transparent method and useful next action."""
    text = str(message or "").strip()[:8000]
    hub, route_reason = route_hub(text, preferred_hub)
    label = HUBS[hub]["label"]
    emotion = detect_emotion(text)
    lowered = text.lower()
    if not text:
        reply = "Tell me what you are trying to achieve, what you have already tried, and any constraints I should respect."
        intent = "clarification"
    elif re.search(r"\b(hi|hello|hey|habari|jambo|mambo|good morning|good evening)\b", lowered):
        reply = {
            "mkulima": "Habari! Mimi ni RevelaAI - Mkulima Hub. Niambie unalima nini ili nikusaidie kwa hatua zilizo wazi.",
            "biashara": "Habari! Mimi ni RevelaAI - Biashara Hub. Tuanze na biashara, mteja, gharama na faida unayolenga.",
            "elimu": "Karibu! Mimi ni RevelaAI - Elimu Hub. Ni somo gani au ujuzi gani ungependa kuelewa?",
            "mahubiri": "Karibu! Mimi ni RevelaAI - Mahubiri Hub. Tuchunguze Biblia, muktadha na matumizi ya kila siku kwa heshima.",
            "general": "Hi! I'm RevelaAI, built by RevelaCode in Mombasa, Kenya. What would you like to work on today?",
        }.get(hub, "Hi! I'm RevelaAI, built by RevelaCode in Mombasa, Kenya. What would you like to work on today?")
        intent = "greeting"
    elif re.search(r"\b(latest|today|right now|current price|current news|weather today|live result)\b", lowered):
        reply = "This local rule engine has no live data feed, so I shouldn't invent current facts. Share a trusted source or the figures you have and I'll help analyze them; otherwise check an up-to-date primary source before acting."
        intent = "current_information"
    elif hub == "mkulima":
        reply = ("Mkulima approach\n1. Identify the crop/livestock and growth stage.\n"
                 "2. Record the county/area, recent weather, soil or water conditions and exact symptoms.\n"
                 "3. Check low-cost causes first (water stress, spacing, soil condition and pests); do not apply chemicals until the problem is identified and the label/local guidance is verified.\n"
                 "4. Compare input cost, expected yield impact and market price before spending.\n\n"
                 "Next step: tell me the crop, location, growth stage, symptoms and when they began. " + HUBS[hub]["method"])
        intent = "farm_advice"
    elif hub == "biashara":
        reply = ("Biashara strategy\n1. Define the paying customer and the urgent problem.\n"
                 "2. Calculate contribution per sale = selling price − variable cost.\n"
                 "3. Track fixed costs, cash collection time, stock risk and repeat purchases.\n"
                 "4. Negotiate around measurable value; state your target, minimum acceptable terms and best alternative before making concessions.\n\n"
                 "Next step: share price, unit cost, fixed costs and expected sales (currency included) for a transparent calculation. " + HUBS[hub]["method"])
        intent = "business_strategy"
    elif hub == "elimu":
        reply = ("Elimu teaching framework\n1. State the learning outcome in one sentence.\n"
                 "2. Explain the core idea in plain language.\n"
                 "3. Walk through one worked example.\n"
                 "4. Give a short practice question and check the learner's reasoning.\n"
                 "5. Correct the misconception and revisit only what is unclear.\n\n"
                 "Next step: tell me the subject, topic, class/learner level and time available. " + HUBS[hub]["method"])
        intent = "education"
    elif hub == "mahubiri":
        reply = ("Mahubiri / Scripture study\n1. Start with the exact Bible passage and read the surrounding context.\n"
                 "2. Note the genre, speaker, audience and historical setting.\n"
                 "3. Compare parallel passages and distinguish explicit text from interpretation.\n"
                 "4. Build a clear main idea, supporting points, practical application and honest conclusion.\n"
                 "5. Represent alternative interpretations fairly; keyword matches alone do not establish doctrine or prophetic fulfilment.\n\n"
                 "Next step: share the passage, congregation/lesson context and desired sermon length. " + HUBS[hub]["method"])
        intent = "scripture_study"
    else:
        if re.search(r"\b(code|debug|python|javascript|react|api|function|error|build|program|circuit|electric|device|engineering)\b", lowered):
            reply = ("General engineering workflow\n1. Define the intended behaviour and inputs/outputs.\n"
                     "2. Reproduce the issue with the smallest example.\n"
                     "3. Inspect logs and isolate one variable at a time.\n"
                     "4. Make the smallest reversible change and test success + failure paths.\n"
                     "5. Keep secrets out of source control and document assumptions.\n\n"
                     "Share the relevant code, exact error and expected behaviour for a targeted diagnosis.")
            intent = "engineering"
        elif re.search(r"\b(decide|decision|should i|which option|choose|strategy|plan)\b", lowered):
            reply = ("Decision frame\n1. Define the outcome and deadline.\n"
                     "2. List viable options, constraints and evidence.\n"
                     "3. Compare upside, downside, reversibility and worst credible case.\n"
                     "4. Choose a small test with a measurable success threshold.\n"
                     "5. Set a review date so the decision can be corrected when evidence changes.\n\n"
                     "I will challenge weak assumptions rather than agree automatically. Share the options and constraints for a concrete comparison.")
            intent = "decision_support"
        else:
            reply = ("Tell me what you want to achieve, the key facts or source material, and any constraints that matter. "
                     "I will help organize the information, compare reasonable options, and identify a useful next step.\n\n"
                     "A reliable starting point is to define the goal, gather evidence, compare options, test a small step, and review the result.")
            intent = "general_guidance"
    reply = _empathy_opening(emotion) + "\n\n" + reply
    return {
        "reply": reply,
        "hub": hub,
        "hubLabel": label,
        "routeReason": route_reason,
        "intent": intent,
        "emotionEstimate": emotion,
        "confidence": "heuristic",
        "engine": "revelaai-local-global-brain-v2",
        "networkUsed": False,
        "capabilities": {"hubRouting": True, "localRules": True, "externalModels": False},
    }


def describe_vision(analysis: dict | None, prompt: str = "") -> dict[str, Any]:
    """Turn local visual measurements into a cautious chat-ready description."""
    data = analysis if isinstance(analysis, dict) else {}
    objects = data.get("objects") if isinstance(data.get("objects"), list) else []
    object_names = [str(x.get("class", "")).strip() for x in objects if isinstance(x, dict) and x.get("class")]
    text = str(data.get("text") or "").strip()[:500]
    brightness = data.get("brightness", data.get("averageBrightness"))
    contrast = data.get("contrast")
    edge = data.get("edgeActivity")
    if not data:
        description = ("I couldn't access usable visual measurements for this image. The chat is still available. "
                       "Try selecting the image again or use a clearer screenshot; no image was sent to a remote model.")
        fallback = True
    else:
        details = []
        if object_names:
            details.append("Local detector labels: " + ", ".join(object_names[:10]) + ".")
        else:
            details.append("No object labels are available from the local detector; pixel statistics cannot identify objects by themselves.")
        if brightness is not None:
            details.append(f"Average brightness/luminance: {brightness}/255.")
        if contrast is not None:
            details.append(f"Measured contrast range: {contrast}.")
        if edge is not None:
            details.append(f"Edge activity: {edge}.")
        if text:
            details.append("Locally detected text: " + text)
        details.append("These are device-side measurements, not a guarantee of scene understanding.")
        description = " ".join(details)
        fallback = not bool(object_names or text)
    return {
        "reply": description,
        "prompt": str(prompt or "")[:500],
        "fallback": fallback,
        "engine": "local-vision-summary",
        "networkUsed": False,
    }


# User-taught knowledge integration for the existing Living Brain.
def assess_knowledge_gap(message: str, user_id: str | None = None, country: str = "KE", language: str = "") -> dict[str, Any]:
    from ai.unknown_learning import assess_unknown
    return assess_unknown(message, user_id=user_id, country=country, language=language)


def save_user_taught_knowledge(topic: str, user_id: str, steps: list[str], **kwargs: Any) -> dict[str, Any]:
    from ai.unknown_learning import save_teaching
    return save_teaching(topic, user_id, steps, **kwargs)


def retrieve_reviewed_knowledge(message: str, root=None) -> list[dict[str, Any]]:
    from ai.unknown_learning import known_matches
    return known_matches(message, root=root)
