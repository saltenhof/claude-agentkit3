"""Test fuer agentkit.bootstrap.composition_root (AG3-023 §2.1.6.2).

Verifiziert, dass ``build_producer_registry`` eine frische Registry
liefert, in die alle bekannten BC-Init-Hooks eingehaengt sind.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.artifacts import ProducerRegistry
from agentkit.bootstrap import build_producer_registry
from agentkit.core_types import ArtifactClass

if TYPE_CHECKING:
    from pathlib import Path


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


def test_build_verify_system_wires_story_context_port(tmp_path: Path) -> None:
    """AG3-035 (echter Drift-Fix): build_verify_system verdrahtet den
    state-backed StoryContextQueryPort-Adapter, damit verify_system NICHT
    direkt aus state_backend.store importiert (BC-Topologie).
    """
    from agentkit.bootstrap.composition_root import build_verify_system
    from agentkit.state_backend.store.verify_story_context_repository import (
        StateBackendVerifyStoryContextAdapter,
    )

    vs = build_verify_system(tmp_path)

    assert isinstance(vs.story_context_port, StateBackendVerifyStoryContextAdapter)
