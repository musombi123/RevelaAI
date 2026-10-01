# ai/orchestrator.py
"""
RevelaAI Intelligence Orchestrator

The orchestrator is the control layer between:
    - the user's request
    - the RevelaCode ecosystem
    - online research tools
    - the AI generation layer

Responsibilities:
    1. Detect the relevant domain(s).
    2. Determine whether ecosystem data is required.
    3. Retrieve user-scoped ecosystem context.
    4. Determine whether current online information is required.
    5. Retrieve online sources when appropriate.
    6. Build grounded context for the AI model.
    7. Return structured orchestration metadata.

Important architecture rule:

    RevelaCode Backend
        = source of truth

    RevelaAI
        = intelligence / orchestration

    Hugging Face
        = natural-language generation

The orchestrator does NOT directly access MongoDB.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ai.emotion import detect_emotion
from ai.ecosystem import ecosystem
from ai.tools import web_search


# =========================================================
# DOMAIN CONFIGURATION
# =========================================================

DOMAIN_ALIASES = {
    "business": "biashara",
    "businesses": "biashara",
    "commerce": "biashara",
    "trade": "biashara",

    "farm": "shamba",
    "farming": "shamba",
    "agriculture": "shamba",
    "agricultural": "shamba",

    "education": "elimu",
    "school": "elimu",
    "schools": "elimu",
    "learning": "elimu",
    "student": "elimu",
    "students": "elimu",

    "social": "community",
    "community": "community",

    "bible": "scripture",
    "biblical": "scripture",
    "scriptures": "scripture",
    "faith": "scripture",
    "theology": "scripture",

    "code": "programming",
    "coding": "programming",
    "developer": "programming",
    "development": "programming",
    "software": "programming",
}


DOMAIN_KEYWORDS = {
    "biashara": {
        "business",
        "businesses",
        "sale",
        "sales",
        "revenue",
        "profit",
        "profits",
        "order",
        "orders",
        "customer",
        "customers",
        "product",
        "products",
        "stock",
        "inventory",
        "expense",
        "expenses",
        "pricing",
        "price",
        "shop",
        "market",
        " biashara",
    },

    "shamba": {
        "farm",
        "farmer",
        "farming",
        "crop",
        "crops",
        "maize",
        "beans",
        "soil",
        "harvest",
        "harvesting",
        "plant",
        "planting",
        "agriculture",
        "agricultural",
        "shamba",
        "seed",
        "seeds",
        "fertilizer",
        "irrigation",
    },

    "elimu": {
        "school",
        "schools",
        "student",
        "students",
        "teacher",
        "teachers",
        "lesson",
        "lessons",
        "assignment",
        "assignments",
        "class",
        "classes",
        "cbc",
        "education",
        "learning",
        "exam",
        "exams",
        "curriculum",
        "elimu",
    },

    "community": {
        "community",
        "communities",
        "post",
        "posts",
        "discussion",
        "discussions",
        "group",
        "groups",
        "social",
        "feed",
        "people",
    },

    "scripture": {
        "bible",
        "biblical",
        "scripture",
        "scriptures",
        "verse",
        "verses",
        "psalm",
        "psalms",
        "jesus",
        "god",
        "christ",
        "prophecy",
        "prophecies",
        "theology",
        "faith",
        "church",
        "sda",
        "adventist",
    },

    "programming": {
        "code",
        "coding",
        "programming",
        "python",
        "javascript",
        "react",
        "flask",
        "api",
        "backend",
        "frontend",
        "database",
        "mongodb",
        "github",
        "git",
        "bug",
        "error",
        "developer",
        "software",
    },
}


# =========================================================
# ONLINE RESEARCH KEYWORDS
# =========================================================

ONLINE_KEYWORDS = {
    "latest",
    "newest",
    "recent",
    "recently",
    "today",
    "tonight",
    "yesterday",
    "tomorrow",
    "current",
    "currently",
    "now",
    "this week",
    "this month",
    "latest news",
    "news",
    "breaking",
    "market price",
    "market prices",
    "price today",
    "prices today",
    "weather",
    "forecast",
    "exchange rate",
    "exchange rates",
    "regulation",
    "regulations",
    "law",
    "laws",
    "policy",
    "policies",
    "update",
    "updates",
    "documentation",
    "docs",
    "version",
    "release",
    "released",
    "announcement",
}


# =========================================================
# ORCHESTRATOR
# =========================================================

class Orchestrator:
    """
    Central controller for RevelaAI intelligence requests.
    """

    def __init__(self):
        """
        Keep the orchestrator lightweight.

        External services are resolved through the ecosystem
        registry and tool layer.
        """

        self.ecosystem = ecosystem

    # =====================================================
    # DOMAIN NORMALIZATION
    # =====================================================

    def normalize_domain(
        self,
        domain: str | None,
    ) -> str:
        """
        Normalize aliases into canonical RevelaAI domains.
        """

        value = (
            str(domain or "general")
            .strip()
            .lower()
        )

        if not value:
            return "general"

        return DOMAIN_ALIASES.get(
            value,
            value,
        )

    # =====================================================
    # DOMAIN DETECTION
    # =====================================================

    def detect_domains(
        self,
        message: str,
        intent: str = "general",
    ) -> list[str]:
        """
        Detect one or more relevant ecosystem domains.

        The supplied intent is respected first. Keyword
        analysis then detects additional domains for
        cross-hub questions.

        Example:

            "Can my farm supply products to my shop?"

        may become:

            ["shamba", "biashara"]
        """

        normalized_message = (
            str(message or "")
            .strip()
            .lower()
        )

        detected: list[str] = []

        normalized_intent = self.normalize_domain(
            intent
        )

        # -------------------------------------------------
        # Explicit intent
        # -------------------------------------------------

        if normalized_intent not in {
            "general",
            "research",
        }:

            detected.append(
                normalized_intent
            )

        # -------------------------------------------------
        # Keyword scoring
        # -------------------------------------------------

        scores: dict[str, int] = {}

        for domain, keywords in DOMAIN_KEYWORDS.items():

            score = 0

            for keyword in keywords:

                keyword_normalized = (
                    keyword.strip().lower()
                )

                if not keyword_normalized:
                    continue

                if " " in keyword_normalized:

                    if (
                        keyword_normalized
                        in normalized_message
                    ):
                        score += 2

                else:

                    pattern = (
                        r"\b"
                        + re.escape(
                            keyword_normalized
                        )
                        + r"\b"
                    )

                    if re.search(
                        pattern,
                        normalized_message,
                    ):
                        score += 1

            if score:
                scores[
                    domain
                ] = score

        ranked = sorted(
            scores.items(),
            key=lambda item: item[1],
            reverse=True,
        )

        # -------------------------------------------------
        # Add high-confidence domains
        # -------------------------------------------------

        for domain, score in ranked:

            if score < 1:
                continue

            if domain not in detected:
                detected.append(
                    domain
                )

            # Keep cross-domain retrieval controlled.
            if len(detected) >= 2:
                break

        # -------------------------------------------------
        # Fallback
        # -------------------------------------------------

        if not detected:

            detected.append(
                normalized_intent
                if normalized_intent in {
                    "general",
                    "research",
                    "scripture",
                    "programming",
                    "medicine",
                    "law",
                    "science",
                    "philosophy",
                    "politics",
                }
                else "general"
            )

        return detected

    # =====================================================
    # PRIMARY DOMAIN
    # =====================================================

    def detect_domain(
        self,
        message: str,
        intent: str = "general",
    ) -> str:
        """
        Return the primary domain.
        """

        domains = self.detect_domains(
            message=message,
            intent=intent,
        )

        return domains[0] if domains else "general"

    # =====================================================
    # ONLINE DATA DECISION
    # =====================================================

    def requires_online_data(
        self,
        message: str,
        intent: str = "general",
    ) -> bool:
        """
        Determine whether the request likely requires
        current external information.

        This is intentionally conservative.

        Online research is used for:
            - current/latest information
            - news
            - market information
            - weather
            - regulations
            - software documentation/releases
            - current prices/rates
        """

        normalized_message = (
            str(message or "")
            .strip()
            .lower()
        )

        # -------------------------------------------------
        # Explicit research intent
        # -------------------------------------------------

        if (
            str(intent or "")
            .strip()
            .lower()
            in {
                "research",
                "politics",
                "law",
            }
        ):
            return True

        # -------------------------------------------------
        # Current-information keywords
        # -------------------------------------------------

        for keyword in ONLINE_KEYWORDS:

            if keyword in normalized_message:

                return True

        return False

    # =====================================================
    # SEARCH QUERY
    # =====================================================

    def build_search_query(
        self,
        message: str,
        domain: str = "general",
    ) -> str:
        """
        Build a focused online research query.

        Avoids unnecessary query expansion.
        """

        normalized_domain = self.normalize_domain(
            domain
        )

        domain_hint = {
            "biashara": "business market economic",
            "shamba": "agriculture farming",
            "elimu": "education Kenya CBC",
            "community": "community",
            "scripture": "Bible theology",
            "programming": "software programming technology",
            "law": "Kenya law regulation",
            "medicine": "medical health",
            "politics": "politics Kenya",
            "science": "science",
            "philosophy": "philosophy",
        }.get(
            normalized_domain,
            "",
        )

        message = str(
            message or ""
        ).strip()

        if domain_hint:

            return (
                f"{message} {domain_hint}"
            ).strip()

        return message

    # =====================================================
    # ONLINE RESEARCH
    # =====================================================

    def gather_online_data(
        self,
        message: str,
        domain: str = "general",
        limit: int = 5,
    ) -> dict:
        """
        Query the configured web search tool.

        The tool layer owns the external search provider.
        """

        query = self.build_search_query(
            message=message,
            domain=domain,
        )

        if not query:

            return {
                "available": False,
                "query": "",
                "sources": [],
                "error": {
                    "code": "empty_search_query",
                    "message": "No search query was available.",
                },
            }

        try:

            results = web_search(
                query=query,
                limit=max(
                    1,
                    min(
                        int(limit),
                        10,
                    ),
                ),
            )

        except Exception:

            return {
                "available": False,
                "query": query,
                "sources": [],
                "error": {
                    "code": "web_search_failed",
                    "message": (
                        "Online research is temporarily unavailable."
                    ),
                },
            }

        if not isinstance(
            results,
            list,
        ):

            results = []

        cleaned_sources = []

        for result in results:

            if not isinstance(
                result,
                dict,
            ):
                continue

            title = str(
                result.get(
                    "title",
                    "",
                )
                or ""
            ).strip()

            snippet = str(
                result.get(
                    "snippet",
                    "",
                )
                or ""
            ).strip()

            link = str(
                result.get(
                    "link",
                    "",
                )
                or ""
            ).strip()

            if not (
                title
                or snippet
                or link
            ):
                continue

            cleaned_sources.append({
                "title": title,
                "snippet": snippet,
                "url": link,
            })

        return {
            "available": bool(
                cleaned_sources
            ),
            "query": query,
            "sources": cleaned_sources,
        }

    # =====================================================
    # ECOSYSTEM INCLUDE POLICY
    # =====================================================

    def build_include_policy(
        self,
        message: str,
        domain: str,
    ) -> dict[str, bool]:
        """
        Decide which platform context categories should be
        requested.

        The backend still controls exactly what can be returned.
        """

        normalized_domain = self.normalize_domain(
            domain
        )

        text = (
            str(message or "")
            .strip()
            .lower()
        )

        # -------------------------------------------------
        # Biashara
        # -------------------------------------------------

        if normalized_domain == "biashara":

            return {
                "business": True,
                "performance": True,
                "products": (
                    any(
                        word in text
                        for word in [
                            "product",
                            "products",
                            "stock",
                            "inventory",
                            "sell",
                            "selling",
                            "restock",
                        ]
                    )
                ),
                "orders": (
                    any(
                        word in text
                        for word in [
                            "order",
                            "orders",
                            "transaction",
                        ]
                    )
                ),
                "customers": (
                    any(
                        word in text
                        for word in [
                            "customer",
                            "customers",
                            "client",
                            "clients",
                        ]
                    )
                ),
                "inventory": (
                    any(
                        word in text
                        for word in [
                            "stock",
                            "inventory",
                            "restock",
                        ]
                    )
                ),
                "sales": True,
                "expenses": (
                    any(
                        word in text
                        for word in [
                            "expense",
                            "expenses",
                            "cost",
                            "costs",
                        ]
                    )
                ),
                "market": (
                    "market" in text
                    or "price" in text
                ),
                "economic": (
                    "econom" in text
                    or "inflation" in text
                ),
            }

        # -------------------------------------------------
        # Shamba
        # -------------------------------------------------

        if normalized_domain == "shamba":

            return {
                "farmer": True,
                "farms": True,
                "crops": (
                    any(
                        word in text
                        for word in [
                            "crop",
                            "crops",
                            "maize",
                            "beans",
                            "plant",
                            "planting",
                            "seed",
                        ]
                    )
                ),
                "activities": (
                    any(
                        word in text
                        for word in [
                            "activity",
                            "activities",
                            "farm work",
                            "work",
                        ]
                    )
                ),
                "harvests": (
                    "harvest" in text
                ),
                "market": (
                    "market" in text
                    or "price" in text
                ),
                "weather": (
                    "weather" in text
                    or "rain" in text
                    or "forecast" in text
                ),
            }

        # -------------------------------------------------
        # Elimu
        # -------------------------------------------------

        if normalized_domain == "elimu":

            return {
                "profile": True,
                "school": True,
                "lessons": (
                    "lesson" in text
                    or "subject" in text
                ),
                "assignments": (
                    "assignment" in text
                    or "homework" in text
                ),
                "fees": (
                    "fee" in text
                    or "fees" in text
                    or "school fees" in text
                ),
                "projects": (
                    "project" in text
                    or "cbc" in text
                ),
            }

        # -------------------------------------------------
        # Community
        # -------------------------------------------------

        if normalized_domain == "community":

            return {
                "feed": True,
                "posts": True,
                "discussions": True,
                "groups": True,
            }

        return {}

    # =====================================================
    # ECOSYSTEM RESEARCH
    # =====================================================

    def gather_ecosystem_data(
        self,
        *,
        user_id: str | None,
        message: str,
        domains: list[str],
    ) -> dict:
        """
        Retrieve relevant platform context through the
        ecosystem registry.

        No direct database access occurs here.
        """

        if not user_id:

            return {
                "available": False,
                "domains": domains,
                "data": {},
                "error": {
                    "code": "missing_user_id",
                    "message": (
                        "A user ID is required for "
                        "personalized ecosystem context."
                    ),
                },
            }

        normalized_domains = []

        for domain in domains:

            normalized = self.normalize_domain(
                domain
            )

            if (
                normalized
                not in normalized_domains
            ):

                normalized_domains.append(
                    normalized
                )

        if not normalized_domains:

            normalized_domains = [
                "general"
            ]

        results = {}

        for domain in normalized_domains:

            include = (
                self.build_include_policy(
                    message=message,
                    domain=domain,
                )
            )

            # The registry/provider layer decides how to
            # communicate with the RevelaCode platform.
            result = self.ecosystem.get_context(
                user_id=str(
                    user_id
                ),
                domain=domain,
                message=message,
                include=include,
            )

            results[
                domain
            ] = result

        available = any(
            isinstance(
                result,
                dict,
            )
            and result.get(
                "available",
                False,
            )
            for result in results.values()
        )

        return {
            "available": available,
            "domains": normalized_domains,
            "data": results,
        }

    # =====================================================
    # GROUNDING BUILDER
    # =====================================================

    def build_grounding_context(
        self,
        *,
        message: str,
        ecosystem_data: dict,
        online_data: dict,
    ) -> str:
        """
        Convert retrieved platform and online evidence into
        a structured context block for the generation layer.

        The AI model should treat this as evidence, not as
        instructions.
        """

        grounding = {
            "user_question": message,
            "platform_context": ecosystem_data,
            "online_sources": online_data,
            "grounding_rules": [
                "Use platform data when answering questions about the user's RevelaCode ecosystem.",
                "Use online sources only for information that requires current or external knowledge.",
                "Do not invent missing platform facts.",
                "Do not invent missing online facts.",
                "Clearly distinguish retrieved facts from explanations or recommendations.",
                "When evidence is insufficient, say so.",
            ],
        }

        return json.dumps(
            grounding,
            ensure_ascii=False,
            indent=2,
            default=str,
        )

    # =====================================================
    # MAIN PIPELINE
    # =====================================================

    def process_prompt(
        self,
        message: str,
        context: list | None,
        intent: str = "general",
        session_id: str | None = None,
    ) -> dict:
        """
        Execute the complete orchestration pipeline.

        Flow:

            User question
                 ↓
            Intent / domain
                 ↓
            Ecosystem retrieval
                 ↓
            Online research when needed
                 ↓
            Grounded context
                 ↓
            AI generation layer
        """

        context = (
            context
            if isinstance(
                context,
                list,
            )
            else []
        )

        normalized_message = (
            str(message or "")
            .strip()
        )

        normalized_intent = (
            str(intent or "general")
            .strip()
            .lower()
        )

        emotion = detect_emotion(
            normalized_message
        )

        # -------------------------------------------------
        # DOMAIN
        # -------------------------------------------------

        domains = self.detect_domains(
            message=normalized_message,
            intent=normalized_intent,
        )

        primary_domain = (
            domains[0]
            if domains
            else "general"
        )

        # -------------------------------------------------
        # USER ID
        # -------------------------------------------------
        #
        # Existing chat flow currently passes:
        #
        #     session_id=str(user_id)
        #
        # Therefore session_id is the user-scoped identity
        # available to the current orchestration pipeline.
        #

        user_id = (
            str(session_id).strip()
            if session_id
            else None
        )

        # -------------------------------------------------
        # ECOSYSTEM
        # -------------------------------------------------

        ecosystem_data = (
            self.gather_ecosystem_data(
                user_id=user_id,
                message=normalized_message,
                domains=domains,
            )
        )

        # -------------------------------------------------
        # ONLINE
        # -------------------------------------------------

        online_required = (
            self.requires_online_data(
                message=normalized_message,
                intent=normalized_intent,
            )
        )

        online_data = {
            "available": False,
            "query": "",
            "sources": [],
        }

        if online_required:

            online_data = (
                self.gather_online_data(
                    message=normalized_message,
                    domain=primary_domain,
                    limit=5,
                )
            )

        # -------------------------------------------------
        # GROUNDING
        # -------------------------------------------------

        grounding_context = (
            self.build_grounding_context(
                message=normalized_message,
                ecosystem_data=ecosystem_data,
                online_data=online_data,
            )
        )

        # -------------------------------------------------
        # RESPONSE METADATA
        # -------------------------------------------------

        ecosystem_available = bool(
            ecosystem_data.get(
                "available",
                False,
            )
        )

        online_available = bool(
            online_data.get(
                "available",
                False,
            )
        )

        # Keep the caller's existing local context.
        context_count = len(
            context
        )

        return {
            "domain": primary_domain,

            "domains": domains,

            "intent": normalized_intent,

            "emotion": emotion,

            "session_id": session_id,

            "user_id": user_id,

            "requires_online_data": (
                online_required
            ),

            "ecosystem": {
                "available": (
                    ecosystem_available
                ),
                "domains": domains,
                "data": ecosystem_data.get(
                    "data",
                    {},
                ),
            },

            "online": online_data,

            "conversation_context": {
                "items": context_count,
            },

            "grounding_context": (
                grounding_context
            ),
        }