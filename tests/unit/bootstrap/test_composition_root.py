"""Test fuer agentkit.bootstrap.composition_root (AG3-023 §2.1.6.2).

Verifiziert, dass ``build_producer_registry`` eine frische Registry
liefert, in die alle bekannten BC-Init-Hooks eingehaengt sind.
"""

from __future__ import annotations

from agentkit.artifacts import ProducerRegistry
from agentkit.bootstrap import build_producer_registry
from agentkit.core_types import ArtifactClass


def test_build_producer_registry_returns_registry() -> None:
    registry = build_producer_registry()
    assert isinstance(registry, ProducerRegistry)


def test_build_producer_registry_includes_verify_producers() -> None:
    registry = build_producer_registry()
    qa_producers = registry.known_producers(ArtifactClass.QA)
    assert {
        "verify-system.layer-1-structural",
        "verify-system.layer-2-llm",
        "verify-system.layer-3-adversarial",
        "verify-system.layer-4-policy",
    }.issubset(qa_producers)


def test_build_producer_registry_returns_fresh_instance() -> None:
    # Zwei Aufrufe liefern separate Instanzen (kein modul-globaler Singleton).
    first = build_producer_registry()
    second = build_producer_registry()
    assert first is not second
