def classify_intent(message: str) -> str:
    msg = message.lower()

    # Greeting
    if msg.strip() in ["hi", "hello", "hey", "greetings", "hello revelaai"]:
        return "greeting"

    # Prophecy
    prophecy_keywords = [
        "prophecy", "fulfilled", "end times", "mark of the beast",
        "antichrist", "messiah", "signs", "revelation"
    ]
    if any(k in msg for k in prophecy_keywords):
        return "prophecy_analysis"

    # Scripture / verse analysis
    scripture_keywords = [
        "verse", "chapter", "scripture", "bible", "quran",
        "gita", "torah", "hadith", "revelation", "psalm"
    ]
    if any(k in msg for k in scripture_keywords):
        return "verse_exegesis"

    # Philosophy
    philosophy_keywords = [
        "meaning", "existence", "ethics", "free will",
        "truth", "consciousness", "purpose"
    ]
    if any(k in msg for k in philosophy_keywords):
        return "philosophy"

    # Science
    science_keywords = [
        "science", "physics", "biology", "evolution",
        "cosmology", "big bang", "neuroscience"
    ]
    if any(k in msg for k in science_keywords):
        return "science"

    # Politics / economics
    politics_keywords = [
        "politics", "government", "power", "empire",
        "economy", "capitalism", "socialism", "leader"
    ]
    if any(k in msg for k in politics_keywords):
        return "politics"

    return "general"
