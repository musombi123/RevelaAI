def detect_emotion(text: str) -> str:
    t = (text or "").lower()

    if "sad" in t or "depressed" in t or "hurt" in t:
        return "sad"
    if "angry" in t or "mad" in t or "annoyed" in t:
        return "angry"
    if "happy" in t or "excited" in t or "great" in t:
        return "happy"
    if "confused" in t or "lost" in t or "help" in t:
        return "confused"

    return "neutral"
