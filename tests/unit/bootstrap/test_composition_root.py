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

    import pytest


def test_build_producer_registry_returns_registry() -> None:
    registry = build_producer_registry()
    assert isinstance(registry, ProducerRegistry)


def test_build_producer_registry_includes_prompt_runtime_producer() -> None:
    """E2 (Review R1): the prompt-runtime audit producer is wired in the real
    composition root -- not only in test-local registries.
    """
    from agentkit.prompt_runtime.audit import PROMPT_AUDIT_PRODUCER_NAME

    registry = build_producer_registry()
    assert PROMPT_AUDIT_PRODUCER_NAME in registry.known_producers(
        ArtifactClass.PROMPT_AUDIT,
    )


def test_build_artifact_manager_writes_prompt_audit_envelope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """E2 end-to-end: a prompt_audit envelope is writable via the PRODUCTION
    ``build_artifact_manager`` path (no locally faked registry seed).
    """
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    from agentkit.bootstrap.composition_root import build_artifact_manager
    from agentkit.prompt_runtime.audit import (
        build_prompt_audit_envelope,
        compute_prompt_audit_hash,
    )

    manager = build_artifact_manager(tmp_path)
    envelope = build_prompt_audit_envelope(
        story_id="AG3-015",
        run_id="run-e2e-1",
        invocation_id="inv-1",
        attempt=1,
        logical_prompt_id="prompt.worker-implementation",
        template_relpath="internal/prompts/worker-implementation.md",
        prompt_bundle_version="2",
        prompt_bundle_manifest_digest="d" * 64,
        render_mode="rendered",
        audit_hash=compute_prompt_audit_hash(
            template_text="# T {x}",
            render_inputs={"x": "1"},
            output_text="# T 1",
        ),
        artifact_path=".agentkit/prompts/run-e2e-1/inv-1/prompt.md",
    )

    reference = manager.write(envelope)
    assert reference.artifact_class is ArtifactClass.PROMPT_AUDIT
    loaded = manager.read(reference)
    assert loaded.payload is not None
    assert loaded.payload["render_mode"] == "rendered"


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
