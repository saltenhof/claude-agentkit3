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


# ---------------------------------------------------------------------------
# R3-C/A2 — the Dim-9 truth-boundary config loader (_load_sonar_config) is
# FAIL-CLOSED: a broken/unreadable project config PROPAGATES (never a silent
# Dim-9 skip), while a deliberate declared absence (available:false / no stanza
# on a non-code project) legitimately resolves to None.
# ---------------------------------------------------------------------------


def _save_ctx_with_project_root(story_dir: Path, project_root: Path) -> None:
    from agentkit.state_backend.store import save_story_context
    from agentkit.story_context_manager.models import StoryContext
    from agentkit.story_context_manager.story_model import WireStoryMode
    from agentkit.story_context_manager.types import StoryMode, StoryType

    save_story_context(
        story_dir,
        StoryContext(
            project_key="proj",
            story_id="AG3-001",
            story_type=StoryType.IMPLEMENTATION,
            execution_route=StoryMode.EXECUTION,
            mode=WireStoryMode.STANDARD,
            title="dim9 config loader",
            project_root=project_root,
        ),
    )


def _save_ctx_without_project_root(story_dir: Path) -> None:
    from agentkit.state_backend.store import save_story_context
    from agentkit.story_context_manager.models import StoryContext
    from agentkit.story_context_manager.story_model import WireStoryMode
    from agentkit.story_context_manager.types import StoryMode, StoryType

    save_story_context(
        story_dir,
        StoryContext(
            project_key="proj",
            story_id="AG3-001",
            story_type=StoryType.IMPLEMENTATION,
            execution_route=StoryMode.EXECUTION,
            mode=WireStoryMode.STANDARD,
            title="dim9 no project_root",
            project_root=None,
        ),
    )


def _gate_ctx(story_dir: Path) -> object:
    from agentkit.governance.integrity_gate import IntegrityGateContext
    from agentkit.story_context_manager.types import StoryType

    return IntegrityGateContext(
        story_dir=story_dir, story_type=StoryType.IMPLEMENTATION
    )


def _gate_ctx_for(story_dir: Path, story_type: object) -> object:
    from agentkit.governance.integrity_gate import IntegrityGateContext

    return IntegrityGateContext(story_dir=story_dir, story_type=story_type)


def test_load_sonar_config_propagates_config_error_no_silent_skip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R3-C/A2: a code-producing project that OMITS the sonarqube stanza
    raises ``ConfigError`` (E6 hard-fail); ``_load_sonar_config`` must PROPAGATE
    it, never swallow it into ``None`` (which would route to a silent Dim-9
    skip). Mirrors AG3-052 ``test_anchor_propagates_config_error_no_silent_skip``.
    """
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    monkeypatch.delenv("AGENTKIT_STATE_DATABASE_URL", raising=False)
    import pytest

    from agentkit.bootstrap.composition_root import _load_sonar_config
    from agentkit.exceptions import ConfigError
    from agentkit.state_backend.store import reset_backend_cache_for_tests

    reset_backend_cache_for_tests()
    try:
        project_root = tmp_path / "project"
        cfg_dir = project_root / ".agentkit" / "config"
        cfg_dir.mkdir(parents=True, exist_ok=True)
        # Code-producing project, NO sonarqube stanza => E6 ConfigError on load.
        (cfg_dir / "project.yaml").write_text(
            "project_key: proj\n"
            "project_name: Proj\n"
            "repositories:\n  - name: app\n    path: .\n"
            "pipeline:\n  max_feedback_rounds: 3\n",
            encoding="utf-8",
        )
        story_dir = tmp_path / "stories" / "AG3-001"
        story_dir.mkdir(parents=True, exist_ok=True)
        _save_ctx_with_project_root(story_dir, project_root)

        with pytest.raises(ConfigError):
            _load_sonar_config(_gate_ctx(story_dir))
    finally:
        reset_backend_cache_for_tests()


def test_load_sonar_config_available_false_is_declared_absence_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R3-C/A2: only a SUCCESSFULLY loaded config with an explicit
    ``available: false`` is a legitimate declared absence -> ``None`` (skip).
    """
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    monkeypatch.delenv("AGENTKIT_STATE_DATABASE_URL", raising=False)
    from agentkit.bootstrap.composition_root import _load_sonar_config
    from agentkit.config.models import SonarQubeConfig
    from agentkit.state_backend.store import reset_backend_cache_for_tests

    reset_backend_cache_for_tests()
    try:
        project_root = tmp_path / "project"
        cfg_dir = project_root / ".agentkit" / "config"
        cfg_dir.mkdir(parents=True, exist_ok=True)
        (cfg_dir / "project.yaml").write_text(
            "project_key: proj\n"
            "project_name: Proj\n"
            "repositories:\n  - name: app\n    path: .\n"
            "pipeline:\n  sonarqube:\n"
            "    available: false\n    enabled: false\n",
            encoding="utf-8",
        )
        story_dir = tmp_path / "stories" / "AG3-001"
        story_dir.mkdir(parents=True, exist_ok=True)
        _save_ctx_with_project_root(story_dir, project_root)

        stanza = _load_sonar_config(_gate_ctx(story_dir))
        assert isinstance(stanza, SonarQubeConfig)
        assert stanza.available is False
    finally:
        reset_backend_cache_for_tests()


def test_load_sonar_config_no_project_root_code_story_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R4-C/A2: a CODE-PRODUCING story with NO resolvable ``project_root`` is a
    broken precondition, NOT a declared absence. ``_load_sonar_config`` MUST
    raise ``ConfigError`` (fail-closed) rather than return ``None`` (which would
    route the productive port through ``build_sonar_gate_port_for_run(None)`` ->
    deliberate-absence skip = Dim-9 fail-OPEN). The context is fully readable;
    only ``project_root`` is unresolvable.
    """
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    monkeypatch.delenv("AGENTKIT_STATE_DATABASE_URL", raising=False)
    import pytest

    from agentkit.bootstrap.composition_root import _load_sonar_config
    from agentkit.exceptions import ConfigError
    from agentkit.state_backend.store import reset_backend_cache_for_tests

    reset_backend_cache_for_tests()
    try:
        story_dir = tmp_path / "stories" / "AG3-001"
        story_dir.mkdir(parents=True, exist_ok=True)
        _save_ctx_without_project_root(story_dir)

        with pytest.raises(ConfigError):
            _load_sonar_config(_gate_ctx(story_dir))
    finally:
        reset_backend_cache_for_tests()


def test_load_sonar_config_no_project_root_non_code_story_is_absence_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R4-C/A2: a NON-code-producing story (concept/research) with no resolvable
    ``project_root`` is a legitimate, declared absence -> ``None`` (the gate never
    applies to it). Only the code-producing axis turns the missing root into a
    fail-closed precondition; this confirms the distinction is not over-broad.
    """
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    monkeypatch.delenv("AGENTKIT_STATE_DATABASE_URL", raising=False)
    from agentkit.bootstrap.composition_root import _load_sonar_config
    from agentkit.state_backend.store import reset_backend_cache_for_tests
    from agentkit.story_context_manager.types import StoryType

    reset_backend_cache_for_tests()
    try:
        story_dir = tmp_path / "stories" / "AG3-001"
        story_dir.mkdir(parents=True, exist_ok=True)
        _save_ctx_without_project_root(story_dir)

        stanza = _load_sonar_config(
            _gate_ctx_for(story_dir, StoryType.CONCEPT)
        )
        assert stanza is None
    finally:
        reset_backend_cache_for_tests()
