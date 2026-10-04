"""
RevelaAI Image Prompt Planner

Transforms user-facing image requests into structured,
visual-first prompts suitable for image-generation models.

The image model should not be expected to understand the
entire RevelaCode product architecture from a short sentence.

This module preserves the user's intent while adding the
visual context required to produce relevant images.
"""

from __future__ import annotations

import re
from typing import Any


# =========================================================
# REVELACODE VISUAL KNOWLEDGE
# =========================================================

REVELACODE_ECOSYSTEM_CONTEXT = """
RevelaCode is an integrated African technology platform.

Its ecosystem includes:

- RevelaAI: the intelligence layer
- Theology Hub: Bible, scripture, study and faith resources
- Biashara: business management, commerce and marketplace
- Shamba: agriculture, farming intelligence and produce markets
- Elimu: education, schools, teachers, students and learning
- Community: communication and interaction across the ecosystem

The architecture is based on:

- one integrated platform
- one account identity
- connected ecosystem hubs
- shared digital infrastructure
- AI-powered intelligence
- communication across users and hubs

The ecosystem is designed for users such as:

- believers
- students
- teachers
- schools
- farmers
- businesses
- communities

The product should be presented as a scalable African technology
ecosystem rather than as an unrelated generic software product.
"""


# =========================================================
# STYLE DETECTION
# =========================================================

def _contains_any(
    text: str,
    phrases: tuple[str, ...],
) -> bool:
    lowered = text.lower()

    return any(
        phrase in lowered
        for phrase in phrases
    )


def _detect_visual_style(
    request: str,
) -> str:

    lowered = request.lower()

    if _contains_any(
        lowered,
        (
            "investor",
            "investors",
            "investment",
            "pitch",
            "funding",
            "fund",
            "startup",
            "venture",
            "presentation",
            "pitch deck",
        ),
    ):
        return (
            "premium investor pitch-deck aesthetic, "
            "enterprise technology presentation, "
            "high-end strategic visualization"
        )

    if _contains_any(
        lowered,
        (
            "diagram",
            "architecture",
            "system",
            "ecosystem",
            "network",
            "flow",
        ),
    ):
        return (
            "clean architectural ecosystem visualization, "
            "professional technology diagram, "
            "clear visual hierarchy"
        )

    if _contains_any(
        lowered,
        (
            "logo",
            "branding",
            "brand",
            "identity",
        ),
    ):
        return (
            "premium corporate branding visualization, "
            "minimal high-end technology aesthetic"
        )

    if _contains_any(
        lowered,
        (
            "realistic",
            "photo",
            "photograph",
            "photorealistic",
        ),
    ):
        return (
            "photorealistic cinematic commercial photography"
        )

    return (
        "premium modern technology visualization, "
        "polished professional presentation aesthetic"
    )


# =========================================================
# VISUAL FORMAT
# =========================================================

def _detect_format(
    request: str,
) -> str:

    lowered = request.lower()

    if _contains_any(
        lowered,
        (
            "investor",
            "pitch",
            "presentation",
            "pitch deck",
            "business presentation",
        ),
    ):
        return (
            "wide 16:9 composition suitable for an investor "
            "presentation slide"
        )

    if _contains_any(
        lowered,
        (
            "poster",
            "flyer",
            "wallpaper",
        ),
    ):
        return (
            "strong vertical poster composition with balanced "
            "visual hierarchy"
        )

    return (
        "balanced composition with strong focal hierarchy"
    )


# =========================================================
# ECOSYSTEM REQUEST
# =========================================================

def _is_revelacode_ecosystem_request(
    request: str,
) -> bool:

    lowered = request.lower()

    ecosystem_terms = (
        "revelacode",
        "jumuiya",
        "ecosystem",
        "biashara",
        "shamba",
        "elimu",
        "theology hub",
        "community hub",
        "revelaai",
    )

    return any(
        term in lowered
        for term in ecosystem_terms
    )


# =========================================================
# INVESTOR REQUEST
# =========================================================

def _is_investor_request(
    request: str,
) -> bool:

    return _contains_any(
        request,
        (
            "investor",
            "investors",
            "investment",
            "funding",
            "pitch",
            "pitch deck",
            "venture capital",
            "vc",
        ),
    )


# =========================================================
# MAIN PLANNER
# =========================================================

def build_image_prompt(
    user_request: str,
) -> dict[str, Any]:
    """
    Convert a short user image request into a structured
    image-generation prompt.

    Returns:
        {
            "prompt": "...",
            "negative_prompt": "...",
            "style": "...",
            "format": "...",
            "domain": "..."
        }
    """

    request = (
        str(
            user_request or ""
        )
        .strip()
    )

    if not request:
        raise ValueError(
            "Image request cannot be empty."
        )

    style = _detect_visual_style(
        request
    )

    visual_format = _detect_format(
        request
    )

    ecosystem_request = (
        _is_revelacode_ecosystem_request(
            request
        )
    )

    investor_request = (
        _is_investor_request(
            request
        )
    )

    # -----------------------------------------------------
    # RevelaCode ecosystem visual
    # -----------------------------------------------------

    if ecosystem_request:

        investor_layer = ""

        if investor_request:

            investor_layer = """
The visual must communicate investor-relevant qualities:

- scalability
- connected markets
- strong technology infrastructure
- economic opportunity
- social impact
- multiple customer/user segments
- long-term platform potential

It should feel like a serious technology-company ecosystem
being presented to investors, not a generic corporate meeting.
"""

        prompt = f"""
Create a high-end visual representation of the RevelaCode
technology ecosystem.

{REVELACODE_ECOSYSTEM_CONTEXT}

USER'S ORIGINAL REQUEST:
{request}

VISUAL DIRECTION:
Present RevelaCode as one unified technology platform.

Place the RevelaCode platform at the center as the primary
digital ecosystem core.

Visually connect these ecosystem areas around the core:

1. RevelaAI — intelligence and AI capabilities
2. Theology Hub — scripture, faith and Bible study
3. Biashara — businesses, commerce, marketplace and trade
4. Shamba — farmers, agriculture and farming intelligence
5. Elimu — schools, teachers, students and education
6. Community — communication and interaction across users

Show the hubs as interconnected components of one platform,
not as separate unrelated companies.

Use subtle visual connections, data flows, modern digital
infrastructure and human-centered technology imagery.

Represent multiple African user groups naturally:
business owners, farmers, teachers, students, believers and
community members.

The overall concept must communicate:

- one ecosystem
- one connected platform
- AI-powered intelligence
- African innovation
- scalability
- practical real-world impact
- economic opportunity
- interconnected communities and markets

{investor_layer}

STYLE:
{style}

FORMAT:
{visual_format}

COMPOSITION:
Strong central focal point, elegant radial or network
ecosystem structure, clear hierarchy, spacious layout,
balanced professional composition.

ENVIRONMENT:
Modern African technology context with subtle Kenya-inspired
visual cues. Avoid stereotypes.

QUALITY:
Premium enterprise technology artwork, cinematic lighting,
sophisticated 3D/isometric elements mixed with realistic
human context, polished commercial presentation quality.

IMPORTANT:
Do not invent unrelated products or industries.
Do not turn this into a generic finance illustration.
Do not create a random office meeting.
Do not depict an unrelated futuristic city as the main subject.
The subject is specifically the RevelaCode ecosystem.
"""

        negative_prompt = """
generic business stock photo,
generic investors,
office meeting,
random businessmen,
random corporate conference,
generic finance chart,
generic bank,
unrelated futuristic city,
unrelated blockchain imagery,
cryptocurrency,
random mobile app,
generic SaaS dashboard,
unrelated technology products,
unrelated brands,
warped interface,
nonsense text,
excessive text,
large blocks of unreadable text,
cluttered composition,
low-detail artwork,
cartoonish corporate clipart
"""

        return {
            "prompt": re.sub(
                r"\n{3,}",
                "\n\n",
                prompt,
            ).strip(),
            "negative_prompt": re.sub(
                r"\n{3,}",
                "\n\n",
                negative_prompt,
            ).strip(),
            "style": style,
            "format": visual_format,
            "domain": "revelacode_ecosystem",
        }

    # -----------------------------------------------------
    # Generic image request
    # -----------------------------------------------------

    prompt = f"""
Create a visually accurate image based on the user's request.

USER REQUEST:
{request}

STYLE:
{style}

FORMAT:
{visual_format}

Interpret the request as a visual brief.

Preserve the user's main subject, objects, setting, purpose,
mood and desired style.

Use strong composition, realistic spatial relationships,
professional lighting and clear subject hierarchy.

Do not introduce unrelated subjects or concepts.

Avoid unnecessary readable text unless the user explicitly
requests typography or a text-based design.
"""

    negative_prompt = """
unrelated subjects,
generic business scene,
random people,
random buildings,
unrelated technology,
nonsense text,
excessive text,
distorted objects,
cluttered composition,
low-detail artwork,
poor anatomy,
generic stock photography
"""

    return {
        "prompt": re.sub(
            r"\n{3,}",
            "\n\n",
            prompt,
        ).strip(),
        "negative_prompt": re.sub(
            r"\n{3,}",
            "\n\n",
            negative_prompt,
        ).strip(),
        "style": style,
        "format": visual_format,
        "domain": "general",
    }

