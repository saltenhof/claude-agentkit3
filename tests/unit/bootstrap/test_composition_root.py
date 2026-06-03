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


def _sonar_config(*, available: bool) -> object:
    from agentkit.config.models import SonarQubeConfig

    if available:
        return SonarQubeConfig(
            available=True,
            enabled=True,
            base_url="http://sonar:9901",
            token_env="SONARQUBE_TOKEN",
        )
    return SonarQubeConfig(available=False, enabled=False)


def _bound_analysis() -> object:
    from agentkit.verify_system.sonarqube_gate.adapter import BoundAnalysis

    return BoundAnalysis(
        analysis_id="AX-1",
        ce_task_id="CE-1",
        component="proj",
        branch="feature",
        commit_sha="c0ffee",
        tree_hash="deadbeef",
    )


def test_build_sonar_gate_port_absent_returns_absent_default() -> None:
    """available:false => the absent default port (NOT the fail-closed adapter)."""
    from agentkit.bootstrap.composition_root import build_sonar_gate_port
    from agentkit.verify_system.sonarqube_gate.port import ABSENT_SONAR_GATE_PORT

    port = build_sonar_gate_port(
        _sonar_config(available=False),
        client=None,
        fast=False,
        story_type=None,
        ledger=None,
        bound_analysis=None,
        main_head_revision="",
    )
    assert port is ABSENT_SONAR_GATE_PORT


def test_build_sonar_gate_port_available_returns_configured_adapter() -> None:
    """available:true => the productive ConfiguredSonarGateInputPort."""
    from agentkit.bootstrap.composition_root import build_sonar_gate_port
    from agentkit.integrations.sonar import SonarClient
    from agentkit.story_context_manager.types import StoryType
    from agentkit.verify_system.sonarqube_gate import AcceptedExceptionLedger
    from agentkit.verify_system.sonarqube_gate.adapter import (
        ConfiguredSonarGateInputPort,
    )

    port = build_sonar_gate_port(
        _sonar_config(available=True),
        client=SonarClient("http://sonar:9901", "tok"),
        fast=False,
        story_type=StoryType.IMPLEMENTATION,
        ledger=AcceptedExceptionLedger(),
        bound_analysis=_bound_analysis(),
        main_head_revision="rev-1",
    )
    assert isinstance(port, ConfiguredSonarGateInputPort)


def test_build_sonar_gate_port_rejects_bad_collaborator_types() -> None:
    """Fail-closed type guards in the builder (defensive wiring)."""
    import pytest

    from agentkit.bootstrap.composition_root import build_sonar_gate_port
    from agentkit.integrations.sonar import SonarClient
    from agentkit.verify_system.sonarqube_gate import AcceptedExceptionLedger

    good_client = SonarClient("http://sonar:9901", "tok")
    good_ledger = AcceptedExceptionLedger()
    good_bound = _bound_analysis()

    with pytest.raises(TypeError, match="config must be a SonarQubeConfig"):
        build_sonar_gate_port(
            object(), client=good_client, fast=False, story_type=None,
            ledger=good_ledger, bound_analysis=good_bound, main_head_revision="",
        )
    with pytest.raises(TypeError, match="client must be a SonarClient"):
        build_sonar_gate_port(
            _sonar_config(available=True), client=object(), fast=False,
            story_type=None, ledger=good_ledger, bound_analysis=good_bound,
            main_head_revision="",
        )
    with pytest.raises(TypeError, match="ledger must be an AcceptedExceptionLedger"):
        build_sonar_gate_port(
            _sonar_config(available=True), client=good_client, fast=False,
            story_type=None, ledger=object(), bound_analysis=good_bound,
            main_head_revision="",
        )
    with pytest.raises(TypeError, match="bound_analysis must be a BoundAnalysis"):
        build_sonar_gate_port(
            _sonar_config(available=True), client=good_client, fast=False,
            story_type=None, ledger=good_ledger, bound_analysis=object(),
            main_head_revision="",
        )
    with pytest.raises(TypeError, match="story_type must be a StoryType"):
        build_sonar_gate_port(
            _sonar_config(available=True), client=good_client,
            fast=False, story_type="impl",
            ledger=good_ledger, bound_analysis=good_bound, main_head_revision="",
        )


def test_build_verify_system_wires_injected_sonar_gate_port(tmp_path: Path) -> None:
    """build_verify_system threads the injected sonar_gate_port (AG3-052 E1)."""
    from agentkit.bootstrap.composition_root import (
        build_sonar_gate_port,
        build_verify_system,
    )
    from agentkit.integrations.sonar import SonarClient
    from agentkit.story_context_manager.types import StoryType
    from agentkit.verify_system.sonarqube_gate import AcceptedExceptionLedger
    from agentkit.verify_system.sonarqube_gate.adapter import (
        ConfiguredSonarGateInputPort,
    )

    port = build_sonar_gate_port(
        _sonar_config(available=True),
        client=SonarClient("http://sonar:9901", "tok"),
        fast=False,
        story_type=StoryType.IMPLEMENTATION,
        ledger=AcceptedExceptionLedger(),
        bound_analysis=_bound_analysis(),
        main_head_revision="rev-1",
    )
    vs = build_verify_system(tmp_path, sonar_gate_port=port)
    assert isinstance(vs.sonar_gate_port, ConfiguredSonarGateInputPort)
