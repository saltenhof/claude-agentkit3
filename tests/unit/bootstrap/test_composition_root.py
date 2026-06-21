"""Test fuer agentkit.backend.bootstrap.composition_root (AG3-023 §2.1.6.2).

Verifiziert, dass ``build_producer_registry`` eine frische Registry
liefert, in die alle bekannten BC-Init-Hooks eingehaengt sind.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.artifacts import ProducerRegistry
from agentkit.backend.bootstrap import build_producer_registry
from agentkit.backend.core_types import ArtifactClass

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
    from agentkit.backend.prompt_runtime.audit import PROMPT_AUDIT_PRODUCER_NAME

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
    from agentkit.backend.bootstrap.composition_root import build_artifact_manager
    from agentkit.backend.prompt_runtime.audit import (
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
    from agentkit.backend.bootstrap.composition_root import build_verify_system
    from agentkit.backend.state_backend.store.verify_story_context_repository import (
        StateBackendVerifyStoryContextAdapter,
    )

    vs = build_verify_system(tmp_path)

    assert isinstance(vs.story_context_port, StateBackendVerifyStoryContextAdapter)


def test_build_verify_system_wires_productive_invalidation_sink(
    tmp_path: Path,
) -> None:
    """AG3-041 E5: build_verify_system wires a PRODUCTIVE invalidation sink.

    The lifecycle's sink must NOT be the no-op default in production — it must
    be the telemetry-emitting adapter (FK-27 §27.2.3 / AG3-041 §2.1.3).
    """
    from agentkit.backend.bootstrap.composition_root import build_verify_system
    from agentkit.backend.verify_system.qa_cycle.invalidation import (
        NullArtifactInvalidationSink,
    )

    vs = build_verify_system(tmp_path)

    sink = vs.qa_cycle_lifecycle.invalidation_sink
    assert not isinstance(sink, NullArtifactInvalidationSink)


def test_build_verify_system_threads_max_feedback_rounds(tmp_path: Path) -> None:
    """AG3-041 E3: build_verify_system threads max_feedback_rounds into the
    RemediationLoopController (the hard owner of the round ceiling).
    """
    from agentkit.backend.bootstrap.composition_root import build_verify_system

    vs = build_verify_system(tmp_path, max_feedback_rounds=2)

    assert vs.remediation_loop_controller.max_feedback_rounds == 2  # noqa: PLR2004


def test_artifact_invalidation_sink_emits_event(tmp_path: Path) -> None:
    """AG3-041 E5: the productive sink emits an ARTIFACT_INVALIDATED event.

    Uses an in-memory ``MemoryEmitter`` to prove the adapter builds and emits a
    well-formed telemetry event (no no-op swallow).
    """
    from agentkit.backend.bootstrap.composition_root import (
        _TelemetryArtifactInvalidationSink,
    )
    from agentkit.backend.telemetry.emitters import MemoryEmitter
    from agentkit.backend.telemetry.events import EventType
    from agentkit.backend.verify_system.qa_cycle.invalidation import (
        ArtifactInvalidationEvent,
    )

    emitter = MemoryEmitter()
    sink = _TelemetryArtifactInvalidationSink(emitter)
    sink.artifact_invalidated(
        ArtifactInvalidationEvent(
            story_id="AG3-041",
            filename="structural.json",
            old_epoch=1,
            source_path=tmp_path / "structural.json",
            stale_path=tmp_path / "stale" / "1" / "structural.json",
        )
    )

    events = emitter.query("AG3-041", EventType.ARTIFACT_INVALIDATED)
    assert len(events) == 1
    assert events[0].payload["filename"] == "structural.json"
    assert events[0].payload["old_epoch"] == 1
    assert events[0].source_component == "verify-system"


def _sonar_config(*, available: bool) -> object:
    from agentkit.backend.config.models import SonarQubeConfig

    if available:
        return SonarQubeConfig(
            available=True,
            enabled=True,
            base_url="http://sonar:9901",
            token_env="SONARQUBE_TOKEN",
            scanner_version="5.0.1",
        )
    return SonarQubeConfig(available=False, enabled=False)


def _bound_analysis() -> object:
    from agentkit.backend.verify_system.sonarqube_gate.adapter import BoundAnalysis

    return BoundAnalysis(
        ce_task_id="CE-1",
        component="proj",
        branch="feature",
        commit_sha="c0ffee",
        tree_hash="deadbeef",
        scanner_version="5.0.1",
    )


def test_build_sonar_gate_port_absent_returns_absent_default() -> None:
    """available:false => the absent default port (NOT the fail-closed adapter)."""
    from agentkit.backend.bootstrap.composition_root import build_sonar_gate_port
    from agentkit.backend.verify_system.sonarqube_gate.port import ABSENT_SONAR_GATE_PORT

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
    from agentkit.backend.bootstrap.composition_root import build_sonar_gate_port
    from agentkit.backend.story_context_manager.types import StoryType
    from agentkit.backend.verify_system.sonarqube_gate import AcceptedExceptionLedger
    from agentkit.backend.verify_system.sonarqube_gate.adapter import (
        ConfiguredSonarGateInputPort,
    )
    from agentkit.integration_clients.sonar import SonarClient

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

    from agentkit.backend.bootstrap.composition_root import build_sonar_gate_port
    from agentkit.backend.verify_system.sonarqube_gate import AcceptedExceptionLedger
    from agentkit.integration_clients.sonar import SonarClient

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
    from agentkit.backend.bootstrap.composition_root import (
        build_sonar_gate_port,
        build_verify_system,
    )
    from agentkit.backend.story_context_manager.types import StoryType
    from agentkit.backend.verify_system.sonarqube_gate import AcceptedExceptionLedger
    from agentkit.backend.verify_system.sonarqube_gate.adapter import (
        ConfiguredSonarGateInputPort,
    )
    from agentkit.integration_clients.sonar import SonarClient

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
    from agentkit.backend.state_backend.store import save_story_context
    from agentkit.backend.story_context_manager.models import StoryContext
    from agentkit.backend.story_context_manager.story_model import WireStoryMode
    from agentkit.backend.story_context_manager.types import StoryMode, StoryType

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
    from agentkit.backend.state_backend.store import save_story_context
    from agentkit.backend.story_context_manager.models import StoryContext
    from agentkit.backend.story_context_manager.story_model import WireStoryMode
    from agentkit.backend.story_context_manager.types import StoryMode, StoryType

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
    from agentkit.backend.governance.integrity_gate import IntegrityGateContext
    from agentkit.backend.story_context_manager.types import StoryType

    return IntegrityGateContext(
        story_dir=story_dir, story_type=StoryType.IMPLEMENTATION
    )


def _gate_ctx_for(story_dir: Path, story_type: object) -> object:
    from agentkit.backend.governance.integrity_gate import IntegrityGateContext

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

    from agentkit.backend.bootstrap.composition_root import _load_sonar_config
    from agentkit.backend.exceptions import ConfigError
    from agentkit.backend.state_backend.store import reset_backend_cache_for_tests

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
    from agentkit.backend.bootstrap.composition_root import _load_sonar_config
    from agentkit.backend.config.models import SonarQubeConfig
    from agentkit.backend.state_backend.store import reset_backend_cache_for_tests

    reset_backend_cache_for_tests()
    try:
        project_root = tmp_path / "project"
        cfg_dir = project_root / ".agentkit" / "config"
        cfg_dir.mkdir(parents=True, exist_ok=True)
        (cfg_dir / "project.yaml").write_text(
            "project_key: proj\n"
            "project_name: Proj\n"
            "repositories:\n  - name: app\n    path: .\n"
            "pipeline:\n"
            "  config_version: '3.0'\n"
            "  features:\n    multi_llm: false\n"
            "  sonarqube:\n"
            "    available: false\n    enabled: false\n"
            "  ci:\n    available: false\n    enabled: false\n",
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

    from agentkit.backend.bootstrap.composition_root import _load_sonar_config
    from agentkit.backend.exceptions import ConfigError
    from agentkit.backend.state_backend.store import reset_backend_cache_for_tests

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
    from agentkit.backend.bootstrap.composition_root import _load_sonar_config
    from agentkit.backend.state_backend.store import reset_backend_cache_for_tests
    from agentkit.backend.story_context_manager.types import StoryType

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


# --- AG3-042 FIX-1/FIX-3/WARNING: structural evidence wiring ----------------


def test_derive_actual_impact_diff_proxy() -> None:
    """FIX-3: the SYSTEM actual-impact proxy escalates with components touched."""
    from agentkit.backend.bootstrap.composition_root import _derive_actual_impact
    from agentkit.backend.story_context_manager.story_model import ChangeImpact

    assert _derive_actual_impact(()) is None
    assert _derive_actual_impact(("pkg/a.py",)) is ChangeImpact.LOCAL
    assert (
        _derive_actual_impact(tuple(f"pkg/m{i}.py" for i in range(5)))
        is ChangeImpact.COMPONENT
    )
    assert (
        _derive_actual_impact(("a/x.py", "b/y.py")) is ChangeImpact.CROSS_COMPONENT
    )
    assert (
        _derive_actual_impact(("a/x.py", "b/y.py", "c/z.py"))
        is ChangeImpact.ARCHITECTURE_IMPACT
    )


def test_change_evidence_provider_failclosed_on_bad_base_ref(tmp_path: Path) -> None:
    """FIX-3: the subprocess-git provider fails closed when HEAD is unresolvable.

    Pointing the provider at a non-existent path makes ``git rev-parse`` fail, so
    the evidence is ``available=False`` (the BLOCKING checks then fail closed --
    never a fall-back to worker self-report).
    """
    from agentkit.backend.bootstrap.composition_root import (
        _SubprocessGitChangeEvidenceProvider,
    )

    missing = tmp_path / "definitely" / "not" / "a" / "repo"
    evidence = _SubprocessGitChangeEvidenceProvider().collect(missing)
    assert evidence.available is False


def test_build_structural_build_test_port_absent_ci_is_failclosed(
    tmp_path: Path,
) -> None:
    """FIX-1: declared-absent CI yields the fail-closed absent build/test port."""
    from agentkit.backend.bootstrap.composition_root import (
        build_structural_build_test_port,
    )
    from agentkit.backend.verify_system.structural.checks import ABSENT_BUILD_TEST_PORT

    port = build_structural_build_test_port(None, tmp_path)
    assert port is ABSENT_BUILD_TEST_PORT
    assert port.evaluate(tmp_path) is None


def test_build_structural_are_provider_activation() -> None:
    """FIX-1: the ARE provider reflects features.are and never silently disables."""
    from agentkit.backend.bootstrap.composition_root import build_structural_are_provider
    from agentkit.backend.config.models import SUPPORTED_CONFIG_VERSION, Features, PipelineConfig

    off = PipelineConfig(  # type: ignore[call-arg]
        config_version=SUPPORTED_CONFIG_VERSION,
        features=Features(are=False, multi_llm=False),
    )
    provider_off = build_structural_are_provider(None, off)
    assert provider_off.is_enabled is False
    assert provider_off.coverage_verdict("S-1", "p") is None

    on = PipelineConfig(  # type: ignore[call-arg]
        config_version=SUPPORTED_CONFIG_VERSION,
        features=Features(are=True, multi_llm=False),
    )
    provider_on = build_structural_are_provider(None, on)
    assert provider_on.is_enabled is True


def test_are_client_construction_from_project_config(tmp_path: Path) -> None:
    from agentkit.backend.bootstrap.composition_root import (
        build_are_client_from_project_config,
        build_structural_are_provider,
    )
    from agentkit.backend.config.models import (
        AreConfig,
        JenkinsConfig,
        ProjectConfig,
        RepositoryConfig,
        SonarQubeConfig,
    )
    from agentkit.backend.requirements_coverage.are_client import AreClient

    def _project(rest_base_url: str | None, *, enabled: bool) -> ProjectConfig:
        from agentkit.backend.config.models import SUPPORTED_CONFIG_VERSION, Features, PipelineConfig

        return ProjectConfig(
            project_key="ak3",
            project_name="AK3",
            repositories=[RepositoryConfig(name="repo", path=tmp_path)],
            pipeline=PipelineConfig(  # type: ignore[call-arg]
                config_version=SUPPORTED_CONFIG_VERSION,
                features=Features(are=enabled, multi_llm=False),
                sonarqube=SonarQubeConfig(available=False, enabled=False),
                ci=JenkinsConfig(available=False, enabled=False),
            ),
            are=AreConfig(
                mcp_server="are-mcp",
                rest_base_url=rest_base_url,
                auth_token="token",
            )
            if enabled
            else None,
        )

    off_client = build_are_client_from_project_config(_project(None, enabled=False))
    assert off_client is None

    client = build_are_client_from_project_config(
        _project("https://are.example.com", enabled=True)
    )
    assert isinstance(client, AreClient)
    assert client.base_url == "https://are.example.com"
    assert client.auth_token == "token"

    missing_url = _project(None, enabled=True)
    assert build_are_client_from_project_config(missing_url) is None
    provider = build_structural_are_provider(None, missing_url.pipeline, store_dir=tmp_path)
    verdict = provider.coverage_verdict("AG3-077", "ak3")
    assert verdict is not None
    assert verdict.reason == "are_gate_unavailable"


def test_build_setup_phase_handler_wires_are_bundle_loader(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agentkit.backend.bootstrap import composition_root as cr
    from agentkit.backend.config.models import (
        SUPPORTED_CONFIG_VERSION,
        AreConfig,
        Features,
        JenkinsConfig,
        PipelineConfig,
        ProjectConfig,
        RepositoryConfig,
        SonarQubeConfig,
    )
    from agentkit.backend.governance.setup_preflight_gate.phase import SetupConfig

    project = ProjectConfig(
        project_key="ak3",
        project_name="AK3",
        repositories=[RepositoryConfig(name="repo", path=tmp_path)],
        pipeline=PipelineConfig(  # type: ignore[call-arg]
            config_version=SUPPORTED_CONFIG_VERSION,
            features=Features(are=True, multi_llm=False),
            sonarqube=SonarQubeConfig(available=False, enabled=False),
            ci=JenkinsConfig(available=False, enabled=False),
        ),
        are=AreConfig(
            mcp_server="are-mcp",
            rest_base_url="https://are.example.com",
            auth_token="token",
        ),
    )
    monkeypatch.setattr(cr, "load_project_config", lambda _root: project, raising=False)
    monkeypatch.setattr(
        "agentkit.backend.config.loader.load_project_config",
        lambda _root: project,
    )

    handler = cr.build_setup_phase_handler(
        SetupConfig(
            owner="owner",
            repo="repo",
            issue_nr=77,
            project_root=tmp_path,
            story_id="AG3-077",
        )
    )

    loader = handler._are_bundle_loader
    client = loader._are_client
    assert client.base_url == "https://are.example.com"
    assert client.auth_token == "token"


def test_telemetry_count_port_run_scoped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """WARNING (FK-33 §33.3.2): the count port filters by (project, story, run)."""
    from agentkit.backend.bootstrap import composition_root as cr

    captured: dict[str, object] = {}

    def _fake_load(
        story_dir: Path,
        *,
        project_key: str | None = None,
        story_id: str | None = None,
        run_id: str | None = None,
        event_type: str | None = None,
    ) -> list[object]:
        captured.update(
            project_key=project_key,
            story_id=story_id,
            run_id=run_id,
            event_type=event_type,
        )
        return []

    monkeypatch.setattr(
        "agentkit.backend.state_backend.store.load_execution_events", _fake_load
    )
    port = cr._StateBackendTelemetryEventCountPort()
    port.count_events(
        tmp_path,
        story_id="S-1",
        event_type="review_request",
        project_key="proj",
        run_id="run-9",
    )
    assert captured["project_key"] == "proj"
    assert captured["story_id"] == "S-1"
    assert captured["run_id"] == "run-9"
    assert captured["event_type"] == "review_request"


def test_telemetry_count_port_failclosed_on_unresolvable_run_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FIX-B (FK-33 §33.3.2): never count cross-run on an unresolvable scope.

    When no ``run_id`` is supplied AND the active run scope cannot be resolved,
    the adapter MUST NOT call ``load_execution_events(..., run_id=None)`` (which
    counts across ALL runs, fail-open). It returns ``0`` and reports the scope as
    unresolvable so the BLOCKING recurring guards fail closed.
    """
    from agentkit.backend.bootstrap import composition_root as cr

    called = {"load": False}

    def _fail_load(*args: object, **kwargs: object) -> list[object]:
        called["load"] = True
        raise AssertionError("must not query unscoped on an unresolvable run scope")

    class _NoScope:
        story_id = "S-1"

    monkeypatch.setattr(
        "agentkit.backend.state_backend.store.load_execution_events", _fail_load
    )
    monkeypatch.setattr(
        "agentkit.backend.state_backend.store.facade.resolve_runtime_scope",
        lambda story_dir: _NoScope(),
    )
    port = cr._StateBackendTelemetryEventCountPort()

    # _NoScope carries no run_id -> getattr(...) is None -> unresolvable.
    assert port.run_scope_resolvable(tmp_path) is False
    count = port.count_events(
        tmp_path,
        story_id="S-1",
        event_type="integrity_violation",
        project_key="proj",
    )
    assert count == 0
    assert called["load"] is False


class _FakeGitResult:
    def __init__(self, stdout: str, returncode: int = 0) -> None:
        self.stdout = stdout
        self.stderr = ""
        self.returncode = returncode

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class _FakeGitBackend:
    """Fake git backend: maps git argv to canned stdout (isolated unit, MOCKS)."""

    def __init__(self, responses: dict[tuple[str, ...], str]) -> None:
        self._responses = responses

    def run(self, repo: object, *args: str) -> _FakeGitResult:
        del repo
        return _FakeGitResult(self._responses.get(args, ""))

    def remove_worktree(self, repo: object) -> None:
        del repo


class _FakeBuildTestPort:
    def __init__(self, *, green: bool, reason: str | None = None) -> None:
        self._green = green
        self._reason = reason

    def run(self, candidate: object) -> object:
        from agentkit.backend.verify_system.pre_merge_runner.contract import BuildTestOutcome

        del candidate
        return BuildTestOutcome(green=self._green, reason=self._reason)


def test_ci_build_test_evidence_adapter_maps_green(tmp_path: Path) -> None:
    """FIX-1: a CI-green run maps to build_ok + tests_green; diff drives count."""
    from agentkit.backend.bootstrap.composition_root import _CiBuildTestEvidenceAdapter

    git = _FakeGitBackend(
        {
            ("rev-parse", "--abbrev-ref", "HEAD"): "story/X-1",
            ("rev-parse", "HEAD"): "abc123",
            ("rev-parse", "HEAD^{tree}"): "tree9",
            ("diff", "--name-only", "origin/main...HEAD"): (
                "src/a.py\ntests/test_a.py\n"
            ),
        }
    )
    adapter = _CiBuildTestEvidenceAdapter(
        build_test_port=_FakeBuildTestPort(green=True), git_backend=git
    )
    ev = adapter.evaluate(tmp_path)
    assert ev is not None
    assert ev.build_ok is True
    assert ev.tests_green is True
    assert ev.test_file_count == 1  # tests/test_a.py


def test_ci_build_test_evidence_adapter_failclosed_red(tmp_path: Path) -> None:
    """FIX-1: a red CI run maps to build_ok=False (BLOCKING checks fail closed)."""
    from agentkit.backend.bootstrap.composition_root import _CiBuildTestEvidenceAdapter

    git = _FakeGitBackend(
        {
            ("rev-parse", "--abbrev-ref", "HEAD"): "story/X-1",
            ("rev-parse", "HEAD"): "abc123",
            ("rev-parse", "HEAD^{tree}"): "tree9",
        }
    )
    adapter = _CiBuildTestEvidenceAdapter(
        build_test_port=_FakeBuildTestPort(green=False, reason="tests red"),
        git_backend=git,
    )
    ev = adapter.evaluate(tmp_path)
    assert ev is not None
    assert ev.build_ok is False
    assert ev.tests_green is False


def test_ci_build_test_evidence_adapter_failclosed_no_head(tmp_path: Path) -> None:
    """FIX-1: an unresolvable HEAD yields None (evidence unconfirmable)."""
    from agentkit.backend.bootstrap.composition_root import _CiBuildTestEvidenceAdapter

    git = _FakeGitBackend({})  # every git call returns empty -> None HEAD
    adapter = _CiBuildTestEvidenceAdapter(
        build_test_port=_FakeBuildTestPort(green=True), git_backend=git
    )
    assert adapter.evaluate(tmp_path) is None


def test_are_provider_coverage_verdict_when_enabled() -> None:
    """FIX-1: when ARE is enabled, coverage_verdict delegates to check_gate."""
    from agentkit.backend.bootstrap.composition_root import _RequirementsCoverageAreProvider
    from agentkit.backend.requirements_coverage.contract import (
        AreDockpointStatus,
        CoverageVerdict,
    )

    sentinel = CoverageVerdict(status=AreDockpointStatus.PASS, verdict="PASS")

    class _FakeCoverage:
        is_enabled = True

        def check_gate(self, story_id: str, project_key: str) -> CoverageVerdict:
            del story_id, project_key
            return sentinel

    provider = _RequirementsCoverageAreProvider(_FakeCoverage())
    assert provider.is_enabled is True
    assert provider.coverage_verdict("S-1", "p") is sentinel

