"""
RevelaAI Ecosystem

Global registry for authorized RevelaCode ecosystem providers.

RevelaAI does not access MongoDB directly.
Providers communicate with the RevelaCode Backend through
the approved ecosystem client / AI Gateway.
"""

from ai.ecosystem.registry import EcosystemRegistry

from ai.ecosystem.biashara import BiasharaProvider
from ai.ecosystem.shamba import ShambaProvider
from ai.ecosystem.elimu import ElimuProvider
from ai.ecosystem.community import CommunityProvider


# =========================================================
# GLOBAL ECOSYSTEM REGISTRY
# =========================================================

ecosystem = EcosystemRegistry(
    providers=[
        BiasharaProvider(),
        ShambaProvider(),
        ElimuProvider(),
        CommunityProvider(),
    ]
)


# =========================================================
# PUBLIC EXPORTS
# =========================================================

__all__ = [
    "EcosystemRegistry",
    "ecosystem",
]