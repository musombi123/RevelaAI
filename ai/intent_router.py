def classify_intent(message: str) -> str:
    msg = message.lower().strip()

    # -----------------------
    # Greeting / onboarding
    # -----------------------
    if msg in ["hi", "hello", "hey", "greetings", "hello revelaai"]:
        return "greeting"

    # -----------------------
    # Document creation (copy-paste ready)
    # -----------------------
    document_keywords = [
        "write a document", "create a document", "proposal",
        "report", "essay", "letter", "policy", "terms",
        "agreement", "contract", "copy paste", "format this",
        "make this professional"
    ]
    if any(k in msg for k in document_keywords):
        return "document_generation"

    # -----------------------
    # Image generation / visuals
    # -----------------------
    image_keywords = [
        "generate image", "create image", "draw", "illustrate",
        "visualize", "image prompt", "ai image", "picture of",
        "design an image"
    ]
    if any(k in msg for k in image_keywords):
        return "image_generation"

    # -----------------------
    # 🎬 Video / Reel / Social Media Content
    # -----------------------
    video_keywords = [
        "reel", "short video", "tiktok", "instagram reel",
        "youtube short", "video idea", "video script",
        "storyboard", "scene breakdown", "visual sequence",
        "social media content", "thumbnail idea"
    ]
    if any(k in msg for k in video_keywords):
        return "video_content"

    # -----------------------
    # Graphic design & branding
    # -----------------------
    design_keywords = [
        "graphic design", "logo", "branding", "poster",
        "flyer", "ui design", "ux design", "layout",
        "color palette", "typography", "brand identity",
        "mockup", "wireframe"
    ]
    if any(k in msg for k in design_keywords):
        return "graphic_design"

    # -----------------------
    # Upload / file-based intent (future-ready)
    # -----------------------
    upload_keywords = [
        "analyze this file", "review this document",
        "analyze this image", "uploaded file",
        "uploaded image", "pdf", "screenshot"
    ]
    if any(k in msg for k in upload_keywords):
        return "file_analysis"

    # -----------------------
    # Programming / technical
    # -----------------------
    programming_keywords = [
        "code", "program", "debug", "fix this",
        "python", "javascript", "react", "api",
        "backend", "frontend", "database",
        "sql", "mongodb", "deployment"
    ]
    if any(k in msg for k in programming_keywords):
        return "programming"

    # -----------------------
    # Prophecy / eschatology
    # -----------------------
    prophecy_keywords = [
        "prophecy", "fulfilled", "end times",
        "mark of the beast", "antichrist",
        "messiah", "revelation", "signs"
    ]
    if any(k in msg for k in prophecy_keywords):
        return "prophecy_analysis"

    # -----------------------
    # Scripture / religious texts
    # -----------------------
    scripture_keywords = [
        "verse", "chapter", "scripture", "bible",
        "quran", "torah", "gita", "hadith",
        "psalm", "gospel"
    ]
    if any(k in msg for k in scripture_keywords):
        return "verse_exegesis"

    # -----------------------
    # Philosophy
    # -----------------------
    philosophy_keywords = [
        "meaning", "existence", "ethics",
        "free will", "truth", "consciousness",
        "purpose", "morality"
    ]
    if any(k in msg for k in philosophy_keywords):
        return "philosophy"

    # -----------------------
    # Science
    # -----------------------
    science_keywords = [
        "science", "physics", "biology",
        "evolution", "cosmology",
        "big bang", "neuroscience"
    ]
    if any(k in msg for k in science_keywords):
        return "science"

    # -----------------------
    # Politics / economics
    # -----------------------
    politics_keywords = [
        "politics", "government", "power",
        "empire", "economy", "capitalism",
        "socialism", "leader", "policy"
    ]
    if any(k in msg for k in politics_keywords):
        return "politics"

    # -----------------------
    # Default
    # -----------------------
    return "general"
