def greeting_response(query: str):
    q = query.lower().strip()

    # Simple greetings
    greetings = [
        "hello", "hi", "hey", "hey there",
        "hello revelaai", "hi revelaai",
        "good morning", "good afternoon", "good evening"
    ]

    if any(greet in q for greet in greetings):
        return {
            "mode": "greeting",
            "message": "Hey 🙂 What’s on your mind today?"
        }

    # Identity questions
    identity_questions = [
        "who are you",
        "what are you",
        "what is revelaai",
        "tell me about yourself"
    ]

    if any(phrase in q for phrase in identity_questions):
        return {
            "mode": "identity",
            "message": (
                "I’m RevelaAI — a conversational assistant designed to help people explore ideas "
                "around philosophy, theology, science, and meaning. I try to stay neutral, thoughtful, "
                "and human-like rather than preachy or rigid."
            )
        }

    return None
