import re

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
    # Mentioning an image, logo, poster or drawing is not a request to
    # generate one. Require an explicit creation action tied to a visual
    # artefact, or a clear first-person request for that artefact.
    image_action = re.search(
        r"\b(?:generate|create|draw|illustrate|design|make|produce)\b"
        r".{0,48}\b(?:image|picture|photo|artwork|illustration|logo|poster|"
        r"banner|flyer|graphic|thumbnail|infographic|diagram|cover|"
        r"business card|instagram post|instagram story|whatsapp status|"
        r"invitation|certificate)\b",
        msg,
        re.IGNORECASE,
    )
    image_request = re.search(
        r"\b(?:i need|i want|please make|please create|can you make|"
        r"could you make|can you create|could you create)\b"
        r".{0,32}\b(?:image|picture|photo|artwork|logo|poster|banner|"
        r"flyer|graphic|thumbnail|infographic|diagram|cover|invitation|"
        r"certificate)\b",
        msg,
        re.IGNORECASE,
    )
    if image_action or image_request:
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
    # ⚖️ Law / Legal reasoning (NEW)
    # -----------------------
    law_keywords = [
        "law", "legal", "court", "judge", "lawsuit",
        "contract law", "criminal", "civil",
        "rights", "constitution", "liability",
        "case law", "legal advice", "sue", "appeal"
    ]
    if any(k in msg for k in law_keywords):
        return "law"

    # -----------------------
    # 🩺 Medicine / Health (NEW)
    # -----------------------
    medicine_keywords = [
        "medicine", "medical", "health", "symptoms",
        "disease", "illness", "diagnosis", "treatment",
        "doctor", "hospital", "mental health",
        "pain", "infection", "therapy"
    ]
    if any(k in msg for k in medicine_keywords):
        return "medicine"

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



# A design revision is a short, explicit command at the start of a turn.
# Do not scan arbitrary long-form prose for generic verbs such as "use",
# "make", or "add": system prompts and technical discussions routinely
# contain those words and must remain ordinary text requests.
_IMAGE_REVISION_COMMAND_RE = re.compile(
    r"^\s*(?:(?:please|can you|could you|would you|i want you to|"
    r"i would like you to|i'd like you to)\s+)*"
    r"(?:change|switch|replace|make|increase|decrease|bigger|smaller|"
    r"translate|recolour|recolor|move|remove|add|edit|revise)\b",
    re.IGNORECASE,
)
_IMAGE_REVISION_USE_RE = re.compile(
    r"^\s*(?:(?:please|can you|could you|would you)\s+)?"
    r"use\s+(?:(?:a|an|the|this|that|new)\s+)?"
    r"(?:background|colour|color|palette|font|typeface|image|photo|"
    r"texture|gradient|icon|illustration|layout)\b",
    re.IGNORECASE,
)


def is_image_revision_request(
    message: str,
    *,
    has_previous_design: bool = False,
) -> bool:
    """Return True only for a clearly stated edit command in a design session.

    The previous implementation searched the entire message for words like
    "use". That caused long system prompts and technical instructions to be
    mistaken for edits to the previous image.
    """
    if not has_previous_design:
        return False

    text = str(message or "").strip()
    if not text:
        return False

    # Restrict matching to the opening command, not quoted instructions or
    # examples appearing later in a long message.
    opening = text.splitlines()[0].strip()
    return bool(
        _IMAGE_REVISION_COMMAND_RE.match(opening)
        or _IMAGE_REVISION_USE_RE.match(opening)
    )
