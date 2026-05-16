"""Composition-Root: explizite App-Initialisierung ohne ``__init__.py``-Side-Effects.

Bietet Builder-Funktionen, die in der App-Initialisierung (z. B. CLI,
Pipeline-Engine-Hochfahren, Test-Fixture) aufgerufen werden. Kein
Modul-Import-Side-Effect; jeder Builder ist explizit zu rufen.

Quelle:
- ``stories/AG3-023-artifact-manager-migration/story.md §2.1.6.2`` —
  Composition-Root-Variante
- ``concept/_meta/bc-cut-decisions.md §BC 8 artifacts`` — Producer-Registry
- AK3-Schnitt-Disziplin: kein operativer Code in ``__init__.py``
"""

from __future__ import annotations

from agentkit.artifacts import ProducerRegistry
from agentkit.verify_system.register import register_verify_producers


def build_producer_registry() -> ProducerRegistry:
    """Erzeugt eine frische ``ProducerRegistry`` und ruft alle bekannten
    BC-Init-Hooks auf.

    Aktueller Stand (AG3-023): nur ``register_verify_producers`` ist
    angebunden. Weitere BC-Init-Hooks (worker, telemetry, governance,
    closure ...) werden in ihren Folgestories analog ergaenzt.

    Returns:
        Eine ``ProducerRegistry`` mit allen heute bekannten Producern.

    Notes:
        Reihenfolge der Init-Hooks ist deterministisch (BC-alphabetisch
        bzw. Capability-Reihenfolge); Verify ist heute die einzige
        registrierte Quelle.
    """
    registry = ProducerRegistry()
    register_verify_producers(registry)
    return registry


__all__ = ["build_producer_registry"]
