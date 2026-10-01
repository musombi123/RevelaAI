"""
RevelaAI Ecosystem Integration

Provides the intelligence layer with a controlled interface to
the RevelaCode platform ecosystem.

Domains:
    - Biashara
    - Shamba
    - Elimu
    - Community
"""

from .registry import EcosystemRegistry


# Shared registry instance.
#
# The registry is intentionally created once so the orchestrator
# and other AI services can reuse the same ecosystem interface.
ecosystem = EcosystemRegistry()


__all__ = [
    "EcosystemRegistry",
    "ecosystem",
]