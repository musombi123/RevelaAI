"""
RevelaAI Ecosystem Registry

Central dispatcher for all RevelaCode ecosystem domains.

The registry allows the orchestrator to ask for ecosystem
context without knowing how each domain is implemented.

Architecture:

    Orchestrator
         │
         ▼
    EcosystemRegistry
         │
    ┌────┼────┬──────────┐
    ▼    ▼    ▼          ▼
 Biashara Shamba Elimu Community
    │    │    │          │
    └────┴────┴──────────┘
               │
               ▼
       RevelaCode AI Gateway
"""

from __future__ import annotations

from typing import Any, Protocol


# =========================================================
# PROVIDER CONTRACT
# =========================================================

class EcosystemProvider(Protocol):
    """
    Contract every ecosystem provider should implement.
    """

    domain: str

    def get_context(
        self,
        *,
        user_id: str,
        message: str,
        include: dict[str, Any] | None = None,
    ) -> dict:
        """
        Retrieve context for a user and domain.
        """
        ...


# =========================================================
# REGISTRY
# =========================================================

class EcosystemRegistry:
    """
    Central registry of RevelaCode ecosystem providers.

    Providers are registered by domain:

        biashara
        shamba
        elimu
        community
    """

    def __init__(
        self,
        providers: list[EcosystemProvider] | None = None,
    ):
        self._providers: dict[
            str,
            EcosystemProvider,
        ] = {}

        if providers:

            for provider in providers:

                self.register(
                    provider
                )

    # =====================================================
    # REGISTER
    # =====================================================

    def register(
        self,
        provider: EcosystemProvider,
    ) -> None:
        """
        Register an ecosystem provider.
        """

        if provider is None:

            raise ValueError(
                "Ecosystem provider cannot be None."
            )

        domain = (
            getattr(
                provider,
                "domain",
                "",
            )
            or ""
        )

        domain = (
            str(domain)
            .strip()
            .lower()
        )

        if not domain:

            raise ValueError(
                "Ecosystem provider must define a domain."
            )

        if not callable(
            getattr(
                provider,
                "get_context",
                None,
            )
        ):

            raise ValueError(
                f"Ecosystem provider '{domain}' "
                "must implement get_context()."
            )

        self._providers[
            domain
        ] = provider

    # =====================================================
    # UNREGISTER
    # =====================================================

    def unregister(
        self,
        domain: str,
    ) -> bool:
        """
        Remove a provider from the registry.

        Returns True when a provider existed.
        """

        normalized = (
            str(domain or "")
            .strip()
            .lower()
        )

        return (
            self._providers.pop(
                normalized,
                None,
            )
            is not None
        )

    # =====================================================
    # LOOKUP
    # =====================================================

    def get_provider(
        self,
        domain: str,
    ) -> EcosystemProvider | None:
        """
        Return the provider registered for a domain.
        """

        normalized = (
            str(domain or "")
            .strip()
            .lower()
        )

        return self._providers.get(
            normalized
        )

    # =====================================================
    # AVAILABLE DOMAINS
    # =====================================================

    def domains(self) -> list[str]:
        """
        Return all currently registered domains.
        """

        return sorted(
            self._providers.keys()
        )

    # =====================================================
    # DOMAIN SUPPORT
    # =====================================================

    def supports(
        self,
        domain: str,
    ) -> bool:
        """
        Return whether a provider exists for the domain.
        """

        return (
            self.get_provider(
                domain
            )
            is not None
        )

    # =====================================================
    # CONTEXT
    # =====================================================

    def get_context(
        self,
        *,
        user_id: str,
        domain: str = "general",
        message: str = "",
        include: dict[str, Any] | None = None,
    ) -> dict:
        """
        Retrieve ecosystem context for a domain.

        Unknown domains return structured metadata rather
        than causing the entire AI pipeline to fail.
        """

        normalized_domain = (
            str(domain or "general")
            .strip()
            .lower()
        )

        normalized_user_id = (
            str(user_id or "")
            .strip()
        )

        if not normalized_user_id:

            return {
                "available": False,
                "domain": normalized_domain,
                "context": {},
                "error": {
                    "code": "missing_user_id",
                    "message": (
                        "user_id is required "
                        "for ecosystem context."
                    ),
                },
            }

        provider = self.get_provider(
            normalized_domain
        )

        if provider is None:

            return {
                "available": False,
                "domain": normalized_domain,
                "context": {},
                "error": {
                    "code": "unsupported_domain",
                    "message": (
                        f"No ecosystem provider is "
                        f"registered for '{normalized_domain}'."
                    ),
                },
            }

        try:

            result = provider.get_context(
                user_id=normalized_user_id,
                message=str(
                    message or ""
                ),
                include=(
                    include
                    if isinstance(
                        include,
                        dict,
                    )
                    else {}
                ),
            )

        except Exception:

            return {
                "available": False,
                "domain": normalized_domain,
                "context": {},
                "error": {
                    "code": "provider_error",
                    "message": (
                        "The ecosystem provider "
                        "could not retrieve context."
                    ),
                },
            }

        if not isinstance(
            result,
            dict,
        ):

            return {
                "available": False,
                "domain": normalized_domain,
                "context": {},
                "error": {
                    "code": "invalid_provider_response",
                    "message": (
                        "The ecosystem provider returned "
                        "an invalid context response."
                    ),
                },
            }

        return {
            "available": True,
            "domain": normalized_domain,
            "context": result,
        }

    # =====================================================
    # MULTI-DOMAIN CONTEXT
    # =====================================================

    def get_multi_context(
        self,
        *,
        user_id: str,
        domains: list[str],
        message: str = "",
        include: dict[str, Any] | None = None,
    ) -> dict:
        """
        Retrieve context from multiple ecosystem domains.

        This is useful for cross-hub questions such as:

            "How can my farm supply my business?"

        which may require:

            shamba + biashara
        """

        requested_domains = []

        for domain in domains:

            normalized = (
                str(domain or "")
                .strip()
                .lower()
            )

            if (
                normalized
                and normalized
                not in requested_domains
            ):

                requested_domains.append(
                    normalized
                )

        results = {}

        for domain in requested_domains:

            results[
                domain
            ] = self.get_context(
                user_id=user_id,
                domain=domain,
                message=message,
                include=include,
            )

        available_domains = [
            domain
            for domain, result
            in results.items()
            if result.get(
                "available",
                False,
            )
        ]

        return {
            "available": bool(
                available_domains
            ),
            "requested_domains": (
                requested_domains
            ),
            "available_domains": (
                available_domains
            ),
            "results": results,
        }

    # =====================================================
    # STATUS
    # =====================================================

    def status(self) -> dict:
        """
        Return a safe registry status snapshot.
        """

        return {
            "registered": self.domains(),
            "count": len(
                self._providers
            ),
        }