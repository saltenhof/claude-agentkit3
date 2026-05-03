"""Exceptions raised by the concept catalog adapter."""

from __future__ import annotations

from agentkit.exceptions import AgentKitError


class ConceptCatalogError(AgentKitError):
    """Base error for concept catalog parsing and lookup failures."""


class ConceptRefNotFoundError(ConceptCatalogError):
    """Raised when a concept reference cannot be resolved."""


class ConceptCatalogParseError(ConceptCatalogError):
    """Raised when a concept document cannot be parsed into a read model."""
