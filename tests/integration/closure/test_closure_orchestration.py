"""End-to-end closure orchestration integration tests (AG3-053, AC#1/#2/#7/#11).

Drives the closure sequence through the REAL composition-root handler
(``build_closure_phase_handler``) against a stubbed git backend + stubbed Sonar
scan / IntegrityGate (the external boundaries) but with the REAL Finding-
Resolution-Gate (over the real ``ArtifactManager``), the REAL post-merge
finalization (with the productive guard-deactivation over the real ``Governance``
top surface), and the real ``ClosureProgress`` checkpoints. Proves the
capabilities are WIRED (not just built) and the negative path aborts before main.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from tests.phase_state_factory import make_phase_state
from tests.unit.closure.closure_fakes import (
    NoOpStoryService,
    RecordingBuildTestPort,
    RecordingIntegrityGate,
    RecordingScanPort,
    StubGitBackend,
)

from agentkit.backend.bootstrap.composition_root import (
    build_artifact_manager,
    build_closure_phase_handler,
)
from agentkit.backend.closure.gates import ABSENT_TELEMETRY_EVIDENCE_PORT
from agentkit.backend.closure.phase import ClosureConfig, ClosurePhaseHandler
from agentkit.backend.core_types import ArtifactClass
from agentkit.backend.core_types.qa_artifact_names import (
    DOC_FIDELITY_PRODUCER,
    DOC_FIDELITY_STAGE,
    QA_REVIEW_PRODUCER,
    QA_REVIEW_STAGE,
    SEMANTIC_REVIEW_PRODUCER,
    SEMANTIC_REVIEW_STAGE,
)
from agentkit.backend.phase_state_store.models import FlowExecution
from agentkit.backend.pipeline_engine.phase_envelope.store import PhaseEnvelopeStore
from agentkit.backend.pipeline_engine.phase_executor import (
    ClosurePayload,
    ClosureProgress,
    PhaseSnapshot,
    PhaseStatus,
)
from agentkit.backend.state_backend.store import (
    append_execution_event,
    load_phase_state,
    save_flow_execution,
    save_phase_snapshot,
    save_story_context,
)
from agentkit.backend.story_context_manager.models import StoryContext
from agentkit.backend.story_context_manager.service import StoryService
from agentkit.backend.story_context_manager.story_model import (
    Story,
    StoryStatus,
    WireStoryType,
)
from agentkit.backend.story_context_manager.types import StoryMode, StoryType
from agentkit.backend.telemetry.contract.records import ExecutionEventRecord
from agentkit.backend.telemetry.events import EventType
from integration.implementation_evidence_support import (
    init_git_story_worktree,
    write_implementation_qa_preconditions,
)

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path


@pytest.fixture(autouse=True)
def _sqlite_backend(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    from agentkit.backend.state_backend.store import reset_backend_cache_for_tests

    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    monkeypatch.delenv("AGENTKIT_STATE_DATABASE_URL", raising=False)
    reset_backend_cache_for_tests()
    yield
    reset_backend_cache_for_tests()


def _prepare(tmp_path: Path, story_id: str = "TEST-001") -> Path:
    s_dir = tmp_path / "stories" / story_id
    s_dir.mkdir(parents=True)
    init_git_story_worktree(s_dir)
    for phase in ("setup", "exploration", "implementation"):
        save_phase_snapshot(
            s_dir,
            PhaseSnapshot(
                story_id=story_id,
                phase=phase,
                status=PhaseStatus.COMPLETED,
                completed_at=datetime.now(tz=UTC),
                artifacts=[],
                evidence={},
            ),
        )
    save_flow_execution(
        s_dir,
        FlowExecution(
            project_key="test-project",
            story_id=story_id,
            run_id=f"run-{story_id.lower()}",
            flow_id="implementation",
            level="story",
            owner="pipeline_engine",
            status="COMPLETED",
            started_at=datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC),
        ),
    )
    append_execution_event(
        s_dir,
        ExecutionEventRecord(
            project_key="test-project",
            story_id=story_id,
            run_id=f"run-{story_id.lower()}",
            event_id=f"evt-agent-start-{story_id.lower()}",
            event_type=EventType.AGENT_START.value,
            occurred_at=datetime(2026, 1, 1, 9, 45, 0, tzinfo=UTC),
            source_component="telemetry-test",
            severity="info",
            payload={},
        ),
    )
    _write_all_layer2(s_dir, story_id=story_id)
    # FIX-2: the comp-root reads the persisted story context to resolve the
    # project root; a deliberately-absent project config (no .agentkit dir under
    # tmp_path) keeps the AG3-056 runners declared-absent (None) without a
    # fail-closed config error. AG3-058 also requires real worker delivery
    # artifacts plus independent git change evidence before implementation
    # closure may proceed.
    write_implementation_qa_preconditions(
        s_dir,
        story_id=story_id,
        run_id=f"run-{story_id.lower()}",
        project_root=tmp_path,
    )
    return s_dir


def _write_all_layer2(s_dir: Path, *, story_id: str) -> None:
    from agentkit.backend.artifacts import (
        ArtifactEnvelope,
        EnvelopeStatus,
        Producer,
        ProducerId,
        ProducerType,
    )

    manager = build_artifact_manager(s_dir)
    run_id = f"run-{story_id.lower()}"
    for stage, producer in (
        (QA_REVIEW_STAGE, QA_REVIEW_PRODUCER),
        (SEMANTIC_REVIEW_STAGE, SEMANTIC_REVIEW_PRODUCER),
        (DOC_FIDELITY_STAGE, DOC_FIDELITY_PRODUCER),
    ):
        manager.write(
            ArtifactEnvelope(
                schema_version="3.0",
                story_id=story_id,
                run_id=run_id,
                stage=stage,
                attempt=1,
                producer=Producer(
                    type=ProducerType.LLM_REVIEWER,
                    name=producer,
                    id=ProducerId(f"{producer}-{run_id}-1"),
                ),
                started_at=datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC),
                finished_at=datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC),
                status=EnvelopeStatus.PASS,
                artifact_class=ArtifactClass.QA,
                payload={"layer": stage, "passed": True, "findings": [], "metadata": {}},
            )
        )


def _ctx(tmp_path: Path, story_id: str = "TEST-001") -> StoryContext:
    return StoryContext(
        project_key="test-project",
        story_id=story_id,
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXECUTION,
        project_root=tmp_path,
    )


def _fresh_envelope(story_id: str) -> object:
    state = make_phase_state(
        story_id=story_id,
        phase="closure",
        status=PhaseStatus.IN_PROGRESS,
        payload=ClosurePayload(progress=ClosureProgress()),
    )
    return PhaseEnvelopeStore.make_fresh_envelope(state)


def test_composition_root_wires_all_collaborators(tmp_path: Path) -> None:
    """AC#11: build_closure_phase_handler wires every collaborator (not None)."""
    s_dir = tmp_path / "stories" / "TEST-001"
    s_dir.mkdir(parents=True)
    save_story_context(s_dir, _ctx(tmp_path))
    config = ClosureConfig(story_dir=s_dir)
    handler = build_closure_phase_handler(config, store_dir=s_dir, project_key="p")

    assert isinstance(handler, ClosurePhaseHandler)
    assert config.integrity_gate is not None
    assert config.artifact_manager is not None
    # scan_port / build_test_port are the AG3-056 runners; for a project with no
    # resolvable ci stanza they are a DECLARED-ABSENT None (not a failure). The
    # always-present finalization + gate collaborators must be wired.
    assert config.sanity_port is not None
    assert config.doc_fidelity_port is not None
    assert config.vectordb_sync_port is not None
    assert config.guard_deactivation_port is not None


def test_built_handler_registers_on_phase_registry(tmp_path: Path) -> None:
    """AC#11: the built handler registers on the ``PhaseHandlerRegistry``.

    Blast-radius guard (finding #6): the productive registration path uses the
    wired handler from ``build_closure_phase_handler`` -- never a bare
    ``ClosurePhaseHandler(ClosureConfig(...))`` that would run un-wired.
    """
    from agentkit.backend.pipeline_engine.lifecycle import PhaseHandlerRegistry

    s_dir = tmp_path / "stories" / "TEST-001"
    s_dir.mkdir(parents=True)
    save_story_context(s_dir, _ctx(tmp_path))
    config = ClosureConfig(story_dir=s_dir)
    handler = build_closure_phase_handler(config, store_dir=s_dir, project_key="p")

    registry = PhaseHandlerRegistry()
    registry.register("closure", handler)

    assert "closure" in registry.registered_phases
    assert registry.get_handler("closure") is handler


def test_e2e_impl_closure_completes(tmp_path: Path) -> None:
    """AC#1/#2/#7: full impl closure -> COMPLETED via the comp-root handler.

    The external boundaries (Sonar scan, IntegrityGate, git) are stubbed; the
    Finding-Resolution-Gate, the merge saga ordering, the post-merge
    finalization and the guard deactivation run for real.
    """
    s_dir = _prepare(tmp_path)
    config = ClosureConfig(
        story_dir=s_dir, story_service=NoOpStoryService()  # type: ignore[arg-type]
    )
    handler = build_closure_phase_handler(
        config, store_dir=s_dir, project_key="test-project"
    )
    # Override only the external boundaries with deterministic stubs (the
    # productive Build/Test port is fail-closed without a wired runner, so the
    # e2e happy path injects a recording build/test boundary -- the real runner
    # is an AG3-018-style follow-up capability).
    from agentkit.backend.closure.merge_sequence import MergeApplicability

    git = StubGitBackend()
    config.scan_port = RecordingScanPort()
    config.build_test_port = RecordingBuildTestPort()
    # FIX-C: clear the per-repo runner mapping built by the comp-root so the
    # single overridden boundary ports are used (the single-repo fallback).
    config.repo_runners = None
    config.integrity_gate = RecordingIntegrityGate()  # type: ignore[assignment]
    config.git_backend = git
    # AG3-081: the Telemetry-Evidence-Block (FK-68 §68.4) is a separate boundary
    # (covered by its own tests); this e2e test deliberately has no project config
    # so it stubs the block to a vacuous PASS, exactly like the scan/integrity/git
    # boundaries above.
    config.telemetry_evidence_port = ABSENT_TELEMETRY_EVIDENCE_PORT
    # Simulate a FULL applicability run (the recording ports stand in for the
    # AG3-056 runners a CI+Sonar-present project would wire).
    config.merge_applicability = MergeApplicability.FULL

    result = handler.on_enter(_ctx(tmp_path), _fresh_envelope("TEST-001"))

    assert result.status == PhaseStatus.COMPLETED
    assert any(cmd[:1] == ("push",) for cmd in git.commands)
    state = load_phase_state(s_dir)
    assert isinstance(state.payload, ClosurePayload)
    progress = state.payload.progress
    assert progress.merge_done
    assert progress.story_closed
    assert progress.postflight_done


def test_fix2_unresolvable_project_root_fails_closed(tmp_path: Path) -> None:
    """FIX-2 / AG3-123: an UNRESOLVABLE workspace anchor fails closed (no silent skip).

    Post-AG3-123 the closure pre-merge config root is the Backend-resolved
    ``StoryWorkspace.project_root``, NOT a re-loaded ``ctx.project_root``. With no
    explicit ``project_root`` AND an OFF-LAYOUT ``story_dir`` (not under a
    ``stories/`` parent) the structural fallback cannot derive the anchor either
    -> fail closed (never a silent (None, None) that would disable Sonar/CI).
    """
    from agentkit.backend.bootstrap.composition_root import ClosureConfigUnavailableError

    # Off-layout story_dir: ``project_root_for_story_dir`` cannot resolve a root.
    s_dir = tmp_path / "not-stories" / "TEST-404"
    s_dir.mkdir(parents=True)
    config = ClosureConfig(story_dir=s_dir)
    with pytest.raises(ClosureConfigUnavailableError):
        build_closure_phase_handler(config, store_dir=s_dir, project_key="p")


def test_fix2_malformed_project_config_fails_closed(tmp_path: Path) -> None:
    """FIX-2: a PRESENT-but-malformed project config fails closed (not absence)."""
    from agentkit.backend.bootstrap.composition_root import ClosureConfigUnavailableError
    from agentkit.backend.config.defaults import DEFAULT_CONFIG_DIR, DEFAULT_CONFIG_FILE

    s_dir = tmp_path / "stories" / "TEST-500"
    s_dir.mkdir(parents=True)
    save_story_context(s_dir, _ctx(tmp_path, story_id="TEST-500"))
    config_dir = tmp_path / DEFAULT_CONFIG_DIR
    config_dir.mkdir(parents=True)
    # Present but invalid YAML -> must fail closed, never (None, None).
    (config_dir / DEFAULT_CONFIG_FILE).write_text(
        "{ unclosed: [flow, mapping\n", encoding="utf-8"
    )
    config = ClosureConfig(story_dir=s_dir)
    with pytest.raises(ClosureConfigUnavailableError):
        build_closure_phase_handler(config, store_dir=s_dir, project_key="p")


def test_fix2_deliberate_absence_returns_no_runners(tmp_path: Path) -> None:
    """FIX-2: a project with no AK3 config file is a DELIBERATE absence (None)."""
    s_dir = tmp_path / "stories" / "TEST-600"
    s_dir.mkdir(parents=True)
    save_story_context(s_dir, _ctx(tmp_path, story_id="TEST-600"))
    config = ClosureConfig(story_dir=s_dir)
    handler = build_closure_phase_handler(config, store_dir=s_dir, project_key="p")
    assert isinstance(handler, ClosurePhaseHandler)
    # No .agentkit config under tmp_path -> declared-absent CI runners (None),
    # NOT a fail-closed error.
    assert config.scan_port is None
    assert config.build_test_port is None


def _real_story_service(project_root: Path) -> StoryService:
    """Build a REAL StoryService bound to ``project_root`` (no fake repo)."""
    from agentkit.backend.state_backend.store.inflight_idempotency_guard import (
        InMemoryInflightIdempotencyGuard,
    )
    from agentkit.backend.state_backend.store.project_management_repository import (
        StateBackendProjectRepository,
    )
    from agentkit.backend.state_backend.store.story_dependency_repository import (
        StateBackendStoryDependencyRepository,
    )
    from agentkit.backend.state_backend.store.story_repository import (
        StateBackendStoryRepository,
    )

    return StoryService(
        story_repository=StateBackendStoryRepository(project_root),
        project_repository=StateBackendProjectRepository(project_root),
        idempotency_guard=InMemoryInflightIdempotencyGuard(),
        dependency_repository=StateBackendStoryDependencyRepository(project_root),
        event_emitter=lambda *_: None,
    )


def _seed_in_progress_story(svc: StoryService, *, story_id: str) -> None:
    """Persist an IN_PROGRESS Story through the real Story-Service repository."""
    from uuid import NAMESPACE_URL, uuid5

    from agentkit.backend.state_backend.store.story_repository import (
        StateBackendStoryRepository,
    )

    story = Story(
        story_uuid=uuid5(NAMESPACE_URL, f"ag3120-closure-{story_id}"),
        project_key="test-project",
        story_number=1,
        story_display_id=story_id,
        title="Closure via real Story-Service (no GitHub issue)",
        story_type=WireStoryType.IMPLEMENTATION,
        status=StoryStatus.IN_PROGRESS,
        participating_repos=["agentkit3-testbed"],
        created_at=datetime.now(tz=UTC),
    )
    # The svc is bound to the same store_dir; persist via that same repository.
    repo = svc._story_repo  # noqa: SLF001 -- test seeds via the bound real repo
    assert isinstance(repo, StateBackendStoryRepository)
    repo.save(story)


def test_impl_closure_completes_via_real_story_service(tmp_path: Path) -> None:
    """AC5: closure drives the REAL AK3 Story-Service (not NoOp) to Done.

    A real ``StoryService`` backed by the real SQLite state-backend is injected
    (no recording stub). After closure, the story reaches the Done terminal
    state via ``complete_story`` and NO GitHub-issue call happens -- the dead
    ``_close_github_issue`` path is gone (AG3-120 H4).
    """
    import dataclasses

    from agentkit.backend.closure import phase as closure_phase_module

    # Structural proof the dead GitHub-issue close path is gone (H4).
    assert not hasattr(closure_phase_module, "_close_github_issue")
    assert "issue_nr" not in {f.name for f in dataclasses.fields(ClosureConfig)}

    s_dir = _prepare(tmp_path)
    svc = _real_story_service(tmp_path)
    _seed_in_progress_story(svc, story_id="TEST-001")

    config = ClosureConfig(story_dir=s_dir, story_service=svc)
    handler = build_closure_phase_handler(
        config, store_dir=s_dir, project_key="test-project"
    )
    from agentkit.backend.closure.merge_sequence import MergeApplicability

    git = StubGitBackend()
    config.scan_port = RecordingScanPort()
    config.build_test_port = RecordingBuildTestPort()
    config.repo_runners = None
    config.integrity_gate = RecordingIntegrityGate()  # type: ignore[assignment]
    config.git_backend = git
    config.telemetry_evidence_port = ABSENT_TELEMETRY_EVIDENCE_PORT
    config.merge_applicability = MergeApplicability.FULL

    result = handler.on_enter(_ctx(tmp_path), _fresh_envelope("TEST-001"))

    assert result.status == PhaseStatus.COMPLETED, result.errors
    state = load_phase_state(s_dir)
    assert isinstance(state.payload, ClosurePayload)
    assert state.payload.progress.story_closed
    # The REAL Story-Service transitioned the story to the Done terminal state.
    closed = svc.get_story("TEST-001")
    assert closed is not None
    assert closed.status is StoryStatus.DONE


def test_e2e_integrity_fail_aborts_before_main_update(tmp_path: Path) -> None:
    """AC#1/#3: IntegrityGate FAIL escalates before any main update."""
    s_dir = _prepare(tmp_path)
    config = ClosureConfig(
        story_dir=s_dir, story_service=NoOpStoryService()  # type: ignore[arg-type]
    )
    handler = build_closure_phase_handler(
        config, store_dir=s_dir, project_key="test-project"
    )
    from agentkit.backend.closure.merge_sequence import MergeApplicability

    git = StubGitBackend()
    config.scan_port = RecordingScanPort()
    config.build_test_port = RecordingBuildTestPort()
    config.repo_runners = None  # FIX-C: use the single overridden boundary ports.
    config.integrity_gate = RecordingIntegrityGate(  # type: ignore[assignment]
        passed=False, failure_reason="SONAR_NOT_GREEN"
    )
    config.git_backend = git
    # AG3-081: stub the Telemetry-Evidence-Block to PASS so this test isolates the
    # IntegrityGate-FAIL path (the telemetry block has its own coverage).
    config.telemetry_evidence_port = ABSENT_TELEMETRY_EVIDENCE_PORT
    config.merge_applicability = MergeApplicability.FULL

    result = handler.on_enter(_ctx(tmp_path), _fresh_envelope("TEST-001"))

    assert result.status == PhaseStatus.ESCALATED
    assert "SONAR_NOT_GREEN" in " ".join(result.errors)
    assert not any(
        cmd[:1] == ("push",)
        and any(a.startswith("--force-with-lease") for a in cmd)
        for cmd in git.commands
    )
    state = load_phase_state(s_dir)
    assert isinstance(state.payload, ClosurePayload)
    assert not state.payload.progress.merge_done
