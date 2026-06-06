"""Unit tests for the closure phase orchestration (AG3-053, FK-29).

Exercise the canonical closure sequence end-to-end against REAL components (the
``ClosureProgress`` model, the ``ArtifactManager`` Finding-Resolution-Gate read,
the merge saga over a stub ``GitBackend``) with stubs only at the external
boundaries (Sonar scan, fast sanity runner, level-4 doc-fidelity, VectorDB sync,
governance) -- see ``closure_fakes``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from tests.unit.closure.closure_fakes import (
    NoOpStoryService,
    RecordingBuildTestPort,
    RecordingDocFidelityPort,
    RecordingGuardDeactivationPort,
    RecordingIntegrityGate,
    RecordingSanityPort,
    RecordingScanPort,
    RecordingVectorDbSyncPort,
    StubGitBackend,
    build_progress_store,
)

from agentkit.artifacts import (
    ArtifactEnvelope,
    EnvelopeStatus,
    Producer,
    ProducerId,
    ProducerType,
)
from agentkit.bootstrap.composition_root import build_artifact_manager
from agentkit.closure.execution_report.writer import (
    ExecutionReport,
    write_execution_report,
)
from agentkit.closure.multi_repo_saga import GitCommandResult
from agentkit.closure.phase import (
    ClosureConfig,
    ClosurePhaseHandler,
    ClosureVerdict,
)
from agentkit.core_types import ArtifactClass
from agentkit.core_types.qa_artifact_names import (
    DOC_FIDELITY_PRODUCER,
    DOC_FIDELITY_STAGE,
    QA_REVIEW_PRODUCER,
    QA_REVIEW_STAGE,
    SEMANTIC_REVIEW_PRODUCER,
    SEMANTIC_REVIEW_STAGE,
)
from agentkit.installer.paths import qa_story_dir
from agentkit.phase_state_store.models import FlowExecution
from agentkit.pipeline_engine.phase_envelope.store import PhaseEnvelopeStore
from agentkit.state_backend.store import (
    append_execution_event,
    load_phase_state,
    save_flow_execution,
    save_phase_snapshot,
)
from agentkit.story_context_manager.models import (
    ClosurePayload,
    ClosureProgress,
    PhaseSnapshot,
    PhaseState,
    PhaseStatus,
    StoryContext,
)
from agentkit.story_context_manager.story_model import WireStoryMode
from agentkit.story_context_manager.types import StoryMode, StoryType
from agentkit.telemetry.contract.records import ExecutionEventRecord
from agentkit.telemetry.events import EventType

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _sqlite_backend(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    from agentkit.state_backend.store import reset_backend_cache_for_tests

    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    monkeypatch.delenv("AGENTKIT_STATE_DATABASE_URL", raising=False)
    reset_backend_cache_for_tests()
    yield
    reset_backend_cache_for_tests()


def _make_ctx(
    *,
    project_key: str = "test-project",
    story_id: str = "TEST-001",
    story_type: StoryType = StoryType.IMPLEMENTATION,
    execution_route: StoryMode | None = StoryMode.EXECUTION,
    mode: WireStoryMode = WireStoryMode.STANDARD,
    project_root: Path | None = None,
) -> StoryContext:
    return StoryContext(
        project_key=project_key,
        story_id=story_id,
        story_type=story_type,
        execution_route=execution_route,
        mode=mode,
        project_root=project_root,
    )


def _make_state(
    *,
    story_id: str = "TEST-001",
    progress: ClosureProgress | None = None,
    status: PhaseStatus = PhaseStatus.IN_PROGRESS,
) -> PhaseState:
    return PhaseState(
        story_id=story_id,
        phase="closure",
        status=status,
        payload=ClosurePayload(progress=progress or ClosureProgress()),
    )


def _save_snapshot(story_dir: Path, phase: str, story_id: str = "TEST-001") -> None:
    save_phase_snapshot(
        story_dir,
        PhaseSnapshot(
            story_id=story_id,
            phase=phase,
            status=PhaseStatus.COMPLETED,
            completed_at=datetime.now(tz=UTC),
            artifacts=[],
            evidence={},
        ),
    )


def _save_flow(
    story_dir: Path,
    story_id: str = "TEST-001",
    project_key: str = "test-project",
) -> None:
    save_flow_execution(
        story_dir,
        FlowExecution(
            project_key=project_key,
            story_id=story_id,
            run_id=f"run-{story_id.lower()}",
            flow_id="implementation",
            level="story",
            owner="pipeline_engine",
            status="COMPLETED",
            started_at=datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC),
        ),
    )


def _append_agent_start_event(
    story_dir: Path,
    *,
    story_id: str = "TEST-001",
    project_key: str = "test-project",
) -> None:
    append_execution_event(
        story_dir,
        ExecutionEventRecord(
            project_key=project_key,
            story_id=story_id,
            run_id=f"run-{story_id.lower()}",
            event_id=f"evt-agent-start-{story_id.lower()}",
            event_type=EventType.AGENT_START.value,
            occurred_at=datetime(2026, 1, 1, 9, 45, 0, tzinfo=UTC),
            source_component="telemetry-test",
            severity="info",
            payload={"subagent_type": "worker"},
        ),
    )


def _prepare_impl_story(
    tmp_path: Path,
    *,
    story_id: str = "TEST-001",
    phases: tuple[str, ...] = ("setup", "exploration", "implementation"),
) -> Path:
    """Persist the prior-phase snapshots + flow + agent_start for an impl run."""
    s_dir = tmp_path / "stories" / story_id
    s_dir.mkdir(parents=True)
    for phase in phases:
        _save_snapshot(s_dir, phase, story_id=story_id)
    _save_flow(s_dir, story_id=story_id)
    _append_agent_start_event(s_dir, story_id=story_id)
    return s_dir


def _write_layer2_artifact(
    manager: object,
    *,
    story_id: str,
    run_id: str,
    stage: str,
    producer_name: str,
    resolution_map: dict[str, str] | None = None,
) -> None:
    """Write one Layer-2 QA envelope (optionally carrying a resolution map)."""
    metadata: dict[str, object] = {"verdict": "PASS"}
    if resolution_map is not None:
        metadata["finding_resolutions"] = resolution_map
    envelope = ArtifactEnvelope(
        schema_version="3.0",
        story_id=story_id,
        run_id=run_id,
        stage=stage,
        attempt=1,
        producer=Producer(
            type=ProducerType.LLM_REVIEWER,
            name=producer_name,
            id=ProducerId(f"{producer_name}-{run_id}-1"),
        ),
        started_at=datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC),
        finished_at=datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC),
        status=EnvelopeStatus.PASS,
        artifact_class=ArtifactClass.QA,
        payload={"layer": stage, "passed": True, "findings": [], "metadata": metadata},
    )
    manager.write(envelope)  # type: ignore[attr-defined]


def _write_all_layer2(
    manager: object,
    *,
    story_id: str,
    run_id: str,
    resolution_map: dict[str, str] | None = None,
) -> None:
    """Write all three Layer-2 envelopes for the Finding-Resolution-Gate read."""
    for stage, producer in (
        (QA_REVIEW_STAGE, QA_REVIEW_PRODUCER),
        (SEMANTIC_REVIEW_STAGE, SEMANTIC_REVIEW_PRODUCER),
        (DOC_FIDELITY_STAGE, DOC_FIDELITY_PRODUCER),
    ):
        _write_layer2_artifact(
            manager,
            story_id=story_id,
            run_id=run_id,
            stage=stage,
            producer_name=producer,
            resolution_map=resolution_map,
        )


def _run_id_for(story_id: str) -> str:
    return f"run-{story_id.lower()}"


def _impl_config(
    s_dir: Path,
    *,
    scan: RecordingScanPort | None = None,
    build_test: RecordingBuildTestPort | None = None,
    sanity: RecordingSanityPort | None = None,
    integrity: RecordingIntegrityGate | None = None,
    doc_fidelity: RecordingDocFidelityPort | None = None,
    vectordb: RecordingVectorDbSyncPort | None = None,
    guard: RecordingGuardDeactivationPort | None = None,
    git_backend: StubGitBackend | None = None,
) -> ClosureConfig:
    """Build a fully-collaborated ClosureConfig with recording stubs."""
    manager = build_artifact_manager(s_dir)
    return ClosureConfig(
        story_dir=s_dir,
        close_issue=False,
        story_service=NoOpStoryService(),  # type: ignore[arg-type]
        integrity_gate=integrity or RecordingIntegrityGate(),  # type: ignore[arg-type]
        scan_port=scan or RecordingScanPort(),
        build_test_port=build_test or RecordingBuildTestPort(),
        sanity_port=sanity or RecordingSanityPort(),
        artifact_manager=manager,
        doc_fidelity_port=doc_fidelity or RecordingDocFidelityPort(),
        vectordb_sync_port=vectordb or RecordingVectorDbSyncPort(),
        guard_deactivation_port=guard or RecordingGuardDeactivationPort(),
        git_backend=git_backend or StubGitBackend(),
        progress_store=build_progress_store(s_dir),  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# Happy path + order enforcement (AC#1, AC#2, AC#3, AC#10)
# ---------------------------------------------------------------------------


class TestImplClosureHappyPath:
    def test_impl_closure_completes_and_calls_all_capabilities(
        self, tmp_path: Path
    ) -> None:
        s_dir = _prepare_impl_story(tmp_path)
        manager = build_artifact_manager(s_dir)
        _write_all_layer2(manager, story_id="TEST-001", run_id=_run_id_for("TEST-001"))

        scan = RecordingScanPort()
        build_test = RecordingBuildTestPort()
        integrity = RecordingIntegrityGate()
        doc = RecordingDocFidelityPort()
        vdb = RecordingVectorDbSyncPort()
        guard = RecordingGuardDeactivationPort()
        git = StubGitBackend()
        config = ClosureConfig(
            story_dir=s_dir,
            close_issue=False,
            story_service=NoOpStoryService(),  # type: ignore[arg-type]
            integrity_gate=integrity,  # type: ignore[arg-type]
            scan_port=scan,
            build_test_port=build_test,
            sanity_port=RecordingSanityPort(),
            artifact_manager=manager,
            doc_fidelity_port=doc,
            vectordb_sync_port=vdb,
            guard_deactivation_port=guard,
            git_backend=git,
            progress_store=build_progress_store(s_dir),  # type: ignore[arg-type]
        )
        handler = ClosurePhaseHandler(config)
        ctx = _make_ctx(project_root=tmp_path)

        result = handler.on_enter(
            ctx, PhaseEnvelopeStore.make_fresh_envelope(_make_state())
        )

        assert result.status == PhaseStatus.COMPLETED
        # AC#1/AC#2: the gate and the saga were actually invoked (verdrahtet).
        assert scan.calls == ["scan"]
        assert build_test.calls == ["build_test"]
        assert integrity.calls == ["gate"]
        # AC#7: every post-merge finalization step ran.
        assert doc.calls == ["doc_fidelity"]
        assert vdb.calls == ["vectordb"]
        assert guard.calls == ["guard"]
        # The saga ran a push (story-branch) -> merge truth is the saga.
        assert any(cmd[:1] == ("push",) for cmd in git.commands)

    def test_scan_runs_before_gate_runs_before_push(self, tmp_path: Path) -> None:
        """AC#3: scan -> gate -> push order is structural (single shared log)."""
        s_dir = _prepare_impl_story(tmp_path)
        manager = build_artifact_manager(s_dir)
        _write_all_layer2(manager, story_id="TEST-001", run_id=_run_id_for("TEST-001"))

        order: list[str] = []

        class _OrderScan(RecordingScanPort):
            def produce_attestation(self, candidate):  # type: ignore[no-untyped-def]
                order.append("scan")
                return super().produce_attestation(candidate)

        class _OrderGate(RecordingIntegrityGate):
            def evaluate(self, story_dir, story_type, *, fresh_attestation=None):  # type: ignore[no-untyped-def]
                order.append("gate")
                return super().evaluate(
                    story_dir, story_type, fresh_attestation=fresh_attestation
                )

        class _OrderGit(StubGitBackend):
            def run(self, repo, *args):  # type: ignore[no-untyped-def]
                if args[:1] == ("push",):
                    order.append("push")
                return super().run(repo, *args)

        config = _impl_config(
            s_dir,
            scan=_OrderScan(),
            integrity=_OrderGate(),
            git_backend=_OrderGit(),
        )
        handler = ClosurePhaseHandler(config)
        result = handler.on_enter(
            _make_ctx(project_root=tmp_path),
            PhaseEnvelopeStore.make_fresh_envelope(_make_state()),
        )

        assert result.status == PhaseStatus.COMPLETED
        assert order.index("scan") < order.index("gate")
        assert order.index("gate") < order.index("push")

    def test_doc_fidelity_runs_before_postflight_before_vectordb_before_guard(
        self, tmp_path: Path
    ) -> None:
        """AC#7: finalization order doc-fidelity -> (postflight) -> vdb -> guard."""
        s_dir = _prepare_impl_story(tmp_path)
        manager = build_artifact_manager(s_dir)
        _write_all_layer2(manager, story_id="TEST-001", run_id=_run_id_for("TEST-001"))

        order: list[str] = []
        doc = RecordingDocFidelityPort(order_log=order)
        vdb = RecordingVectorDbSyncPort(order_log=order)
        guard = RecordingGuardDeactivationPort(order_log=order)
        config = _impl_config(
            s_dir, doc_fidelity=doc, vectordb=vdb, guard=guard
        )
        handler = ClosurePhaseHandler(config)
        result = handler.on_enter(
            _make_ctx(project_root=tmp_path),
            PhaseEnvelopeStore.make_fresh_envelope(_make_state()),
        )

        assert result.status == PhaseStatus.COMPLETED
        assert order == ["doc_fidelity", "vectordb", "guard"]


# ---------------------------------------------------------------------------
# Negative paths -> ESCALATED (AC#1, AC#3, AC#4, AC#10)
# ---------------------------------------------------------------------------


class TestImplClosureEscalation:
    def test_finding_resolution_fail_escalates(self, tmp_path: Path) -> None:
        """AC#4: an unresolved Layer-2 finding -> ESCALATED, no scan/gate/push."""
        s_dir = _prepare_impl_story(tmp_path)
        manager = build_artifact_manager(s_dir)
        _write_all_layer2(
            manager,
            story_id="TEST-001",
            run_id=_run_id_for("TEST-001"),
            resolution_map={"qa_review:ac_fulfilled": "not_resolved"},
        )
        scan = RecordingScanPort()
        integrity = RecordingIntegrityGate()
        git = StubGitBackend()
        config = _impl_config(
            s_dir, scan=scan, integrity=integrity, git_backend=git
        )
        handler = ClosurePhaseHandler(config)
        result = handler.on_enter(
            _make_ctx(project_root=tmp_path),
            PhaseEnvelopeStore.make_fresh_envelope(_make_state()),
        )

        assert result.status == PhaseStatus.ESCALATED
        # Fail-closed BEFORE scan/gate/push.
        assert scan.calls == []
        assert integrity.calls == []
        assert not any(cmd[:1] == ("push",) for cmd in git.commands)

    def test_missing_layer2_artifact_escalates(self, tmp_path: Path) -> None:
        """AC#4: a missing Layer-2 artefact is fail-closed (no silent pass)."""
        s_dir = _prepare_impl_story(tmp_path)
        # Deliberately write NO Layer-2 artefacts.
        config = _impl_config(s_dir)
        handler = ClosurePhaseHandler(config)
        result = handler.on_enter(
            _make_ctx(project_root=tmp_path),
            PhaseEnvelopeStore.make_fresh_envelope(_make_state()),
        )
        assert result.status == PhaseStatus.ESCALATED

    def test_integrity_gate_fail_escalates_before_push(self, tmp_path: Path) -> None:
        """AC#1/AC#3: a gate FAIL escalates -- scan ran, but NO push, NO merge."""
        s_dir = _prepare_impl_story(tmp_path)
        manager = build_artifact_manager(s_dir)
        _write_all_layer2(manager, story_id="TEST-001", run_id=_run_id_for("TEST-001"))
        scan = RecordingScanPort()
        integrity = RecordingIntegrityGate(passed=False, failure_reason="SONAR_NOT_GREEN")
        git = StubGitBackend()
        config = _impl_config(
            s_dir, scan=scan, integrity=integrity, git_backend=git
        )
        handler = ClosurePhaseHandler(config)
        result = handler.on_enter(
            _make_ctx(project_root=tmp_path),
            PhaseEnvelopeStore.make_fresh_envelope(_make_state()),
        )

        assert result.status == PhaseStatus.ESCALATED
        assert scan.calls == ["scan"]
        assert integrity.calls == ["gate"]
        assert not any(cmd[:1] == ("push",) for cmd in git.commands)

    def test_scan_not_produced_escalates_before_gate(self, tmp_path: Path) -> None:
        """AC#3: a non-produced attestation blocks BEFORE the gate (no gate call)."""
        s_dir = _prepare_impl_story(tmp_path)
        manager = build_artifact_manager(s_dir)
        _write_all_layer2(manager, story_id="TEST-001", run_id=_run_id_for("TEST-001"))
        scan = RecordingScanPort(produced=False, reason="integrated candidate red")
        integrity = RecordingIntegrityGate()
        config = _impl_config(s_dir, scan=scan, integrity=integrity)
        handler = ClosurePhaseHandler(config)
        result = handler.on_enter(
            _make_ctx(project_root=tmp_path),
            PhaseEnvelopeStore.make_fresh_envelope(_make_state()),
        )

        assert result.status == PhaseStatus.ESCALATED
        assert scan.calls == ["scan"]
        assert integrity.calls == []  # gate never reached without a scan

    def test_push_failure_escalates_with_saga_rollback(self, tmp_path: Path) -> None:
        """AC#2: a push failure escalates (the saga owns the rollback)."""
        s_dir = _prepare_impl_story(tmp_path)
        manager = build_artifact_manager(s_dir)
        _write_all_layer2(manager, story_id="TEST-001", run_id=_run_id_for("TEST-001"))
        git = StubGitBackend(fail_command="push")
        config = _impl_config(s_dir, git_backend=git)
        handler = ClosurePhaseHandler(config)
        result = handler.on_enter(
            _make_ctx(project_root=tmp_path),
            PhaseEnvelopeStore.make_fresh_envelope(_make_state()),
        )
        assert result.status == PhaseStatus.ESCALATED

    def test_integrate_main_conflict_escalates_before_build_scan_gate_push(
        self, tmp_path: Path
    ) -> None:
        """#1: an un-integrable main (merge conflict) escalates before build/scan/gate."""
        s_dir = _prepare_impl_story(tmp_path)
        manager = build_artifact_manager(s_dir)
        _write_all_layer2(manager, story_id="TEST-001", run_id=_run_id_for("TEST-001"))
        scan = RecordingScanPort()
        build_test = RecordingBuildTestPort()
        integrity = RecordingIntegrityGate()
        # ``merge`` fails -> integrate-latest-main cannot produce a candidate.
        git = StubGitBackend(fail_command="merge")
        config = _impl_config(
            s_dir,
            scan=scan,
            build_test=build_test,
            integrity=integrity,
            git_backend=git,
        )
        handler = ClosurePhaseHandler(config)
        result = handler.on_enter(
            _make_ctx(project_root=tmp_path),
            PhaseEnvelopeStore.make_fresh_envelope(_make_state()),
        )

        assert result.status == PhaseStatus.ESCALATED
        # Fail-closed BEFORE build/test, scan, gate and push.
        assert build_test.calls == []
        assert scan.calls == []
        assert integrity.calls == []
        assert not any(cmd[:1] == ("push",) for cmd in git.commands)
        # The barrier aborted the half-merge (no mid-merge worktree left behind).
        assert ("merge", "--abort") in git.commands

    def test_dirty_workspace_after_integrate_escalates(self, tmp_path: Path) -> None:
        """#1: a non-clean integrated workspace escalates (scan tree not reproducible)."""
        s_dir = _prepare_impl_story(tmp_path)
        manager = build_artifact_manager(s_dir)
        _write_all_layer2(manager, story_id="TEST-001", run_id=_run_id_for("TEST-001"))
        scan = RecordingScanPort()
        build_test = RecordingBuildTestPort()
        git = StubGitBackend(dirty_status=True)
        config = _impl_config(
            s_dir, scan=scan, build_test=build_test, git_backend=git
        )
        handler = ClosurePhaseHandler(config)
        result = handler.on_enter(
            _make_ctx(project_root=tmp_path),
            PhaseEnvelopeStore.make_fresh_envelope(_make_state()),
        )

        assert result.status == PhaseStatus.ESCALATED
        assert build_test.calls == []
        assert scan.calls == []

    def test_build_test_red_escalates_before_scan(self, tmp_path: Path) -> None:
        """#1: a red Build/Test on the integrated candidate blocks BEFORE the scan."""
        s_dir = _prepare_impl_story(tmp_path)
        manager = build_artifact_manager(s_dir)
        _write_all_layer2(manager, story_id="TEST-001", run_id=_run_id_for("TEST-001"))
        scan = RecordingScanPort()
        build_test = RecordingBuildTestPort(green=False, reason="3 tests failed")
        integrity = RecordingIntegrityGate()
        git = StubGitBackend()
        config = _impl_config(
            s_dir,
            scan=scan,
            build_test=build_test,
            integrity=integrity,
            git_backend=git,
        )
        handler = ClosurePhaseHandler(config)
        result = handler.on_enter(
            _make_ctx(project_root=tmp_path),
            PhaseEnvelopeStore.make_fresh_envelope(_make_state()),
        )

        assert result.status == PhaseStatus.ESCALATED
        assert build_test.calls == ["build_test"]
        # Scan / gate / push never reached after a red build.
        assert scan.calls == []
        assert integrity.calls == []
        assert not any(cmd[:1] == ("push",) for cmd in git.commands)

    def test_build_test_runs_before_scan_before_gate_before_push(
        self, tmp_path: Path
    ) -> None:
        """#1: build/test -> scan -> gate -> push order is structural."""
        s_dir = _prepare_impl_story(tmp_path)
        manager = build_artifact_manager(s_dir)
        _write_all_layer2(manager, story_id="TEST-001", run_id=_run_id_for("TEST-001"))
        order: list[str] = []

        class _OrderBuild(RecordingBuildTestPort):
            def run(self, candidate):  # type: ignore[no-untyped-def]
                order.append("build_test")
                return super().run(candidate)

        class _OrderScan(RecordingScanPort):
            def produce_attestation(self, candidate):  # type: ignore[no-untyped-def]
                order.append("scan")
                return super().produce_attestation(candidate)

        class _OrderGate(RecordingIntegrityGate):
            def evaluate(self, story_dir, story_type, *, fresh_attestation=None):  # type: ignore[no-untyped-def]
                order.append("gate")
                return super().evaluate(
                    story_dir, story_type, fresh_attestation=fresh_attestation
                )

        class _OrderGit(StubGitBackend):
            def run(self, repo, *args):  # type: ignore[no-untyped-def]
                if args[:1] == ("push",):
                    order.append("push")
                return super().run(repo, *args)

        config = _impl_config(
            s_dir,
            scan=_OrderScan(),
            build_test=_OrderBuild(),
            integrity=_OrderGate(),
            git_backend=_OrderGit(),
        )
        handler = ClosurePhaseHandler(config)
        result = handler.on_enter(
            _make_ctx(project_root=tmp_path),
            PhaseEnvelopeStore.make_fresh_envelope(_make_state()),
        )

        assert result.status == PhaseStatus.COMPLETED
        assert order.index("build_test") < order.index("scan")
        assert order.index("scan") < order.index("gate")
        assert order.index("gate") < order.index("push")

    def test_tree_hash_mismatch_escalates_before_gate(self, tmp_path: Path) -> None:
        """E3: tree_hash(scan) != tree_hash(merge) escalates before the gate, no push."""
        s_dir = _prepare_impl_story(tmp_path)
        manager = build_artifact_manager(s_dir)
        _write_all_layer2(manager, story_id="TEST-001", run_id=_run_id_for("TEST-001"))
        scan = RecordingScanPort(tree_hash_override="deadbeefdead")
        integrity = RecordingIntegrityGate()
        git = StubGitBackend()
        config = _impl_config(
            s_dir, scan=scan, integrity=integrity, git_backend=git
        )
        handler = ClosurePhaseHandler(config)
        result = handler.on_enter(
            _make_ctx(project_root=tmp_path),
            PhaseEnvelopeStore.make_fresh_envelope(_make_state()),
        )

        assert result.status == PhaseStatus.ESCALATED
        # E3 binding (scan==merge) blocks BEFORE the gate, so the gate never runs.
        assert scan.calls == ["scan"]
        assert integrity.calls == []
        assert not any(cmd[:1] == ("push",) for cmd in git.commands)

    def test_commit_hash_mismatch_escalates_before_gate(self, tmp_path: Path) -> None:
        """E3: commit_sha(scan) != commit_sha(merge) escalates before the gate."""
        s_dir = _prepare_impl_story(tmp_path)
        manager = build_artifact_manager(s_dir)
        _write_all_layer2(manager, story_id="TEST-001", run_id=_run_id_for("TEST-001"))
        scan = RecordingScanPort(commit_sha_override="9999wrongcommit9999")
        integrity = RecordingIntegrityGate()
        git = StubGitBackend()
        config = _impl_config(
            s_dir, scan=scan, integrity=integrity, git_backend=git
        )
        handler = ClosurePhaseHandler(config)
        result = handler.on_enter(
            _make_ctx(project_root=tmp_path),
            PhaseEnvelopeStore.make_fresh_envelope(_make_state()),
        )

        assert result.status == PhaseStatus.ESCALATED
        # E3 binding blocks BEFORE the gate (a scan bound to a foreign commit).
        assert scan.calls == ["scan"]
        assert integrity.calls == []
        assert not any(cmd[:1] == ("push",) for cmd in git.commands)

    def test_fresh_attestation_flows_into_gate(self, tmp_path: Path) -> None:
        """FK-35 §35.2.4a: the barrier passes the FRESH attestation into Dim 9."""
        s_dir = _prepare_impl_story(tmp_path)
        manager = build_artifact_manager(s_dir)
        _write_all_layer2(manager, story_id="TEST-001", run_id=_run_id_for("TEST-001"))
        scan = RecordingScanPort()
        integrity = RecordingIntegrityGate()
        config = _impl_config(s_dir, scan=scan, integrity=integrity)
        handler = ClosurePhaseHandler(config)
        result = handler.on_enter(
            _make_ctx(project_root=tmp_path),
            PhaseEnvelopeStore.make_fresh_envelope(_make_state()),
        )

        assert result.status == PhaseStatus.COMPLETED
        # The gate received the fresh attestation from the scan (not a re-read).
        assert integrity.received_fresh_attestation is not None

    def test_scan_attestation_unbindable_escalates_before_push(
        self, tmp_path: Path
    ) -> None:
        """#1: a produced attestation with NO commit/tree binding fails closed."""
        s_dir = _prepare_impl_story(tmp_path)
        manager = build_artifact_manager(s_dir)
        _write_all_layer2(manager, story_id="TEST-001", run_id=_run_id_for("TEST-001"))
        scan = RecordingScanPort(omit_binding=True)
        git = StubGitBackend()
        config = _impl_config(s_dir, scan=scan, git_backend=git)
        handler = ClosurePhaseHandler(config)
        result = handler.on_enter(
            _make_ctx(project_root=tmp_path),
            PhaseEnvelopeStore.make_fresh_envelope(_make_state()),
        )

        assert result.status == PhaseStatus.ESCALATED
        assert not any(cmd[:1] == ("push",) for cmd in git.commands)

    def test_main_drift_cas_failure_escalates_before_push(self, tmp_path: Path) -> None:
        """#1: origin/main drift since the lock (CAS failure) escalates, no push."""
        s_dir = _prepare_impl_story(tmp_path)
        manager = build_artifact_manager(s_dir)
        _write_all_layer2(manager, story_id="TEST-001", run_id=_run_id_for("TEST-001"))
        scan = RecordingScanPort()
        integrity = RecordingIntegrityGate()
        # main moves away from locked_sha on the CAS re-read (3rd origin/main read).
        git = StubGitBackend(main_drift_sha="9999drift9999")
        config = _impl_config(
            s_dir, scan=scan, integrity=integrity, git_backend=git
        )
        handler = ClosurePhaseHandler(config)
        result = handler.on_enter(
            _make_ctx(project_root=tmp_path),
            PhaseEnvelopeStore.make_fresh_envelope(_make_state()),
        )

        assert result.status == PhaseStatus.ESCALATED
        # The barrier ran scan + gate but the CAS guard blocks before the push.
        assert scan.calls == ["scan"]
        assert integrity.calls == ["gate"]
        assert not any(cmd[:1] == ("push",) for cmd in git.commands)

    def test_full_applicability_missing_build_runner_fails_closed(
        self, tmp_path: Path
    ) -> None:
        """FIX-3: FULL applicability with no Build/Test runner is a wiring bug ->
        ESCALATED (never merge without a confirmed integrated-candidate build)."""
        from agentkit.closure.merge_sequence import MergeApplicability

        s_dir = _prepare_impl_story(tmp_path)
        manager = build_artifact_manager(s_dir)
        _write_all_layer2(manager, story_id="TEST-001", run_id=_run_id_for("TEST-001"))
        config = ClosureConfig(
            story_dir=s_dir,
            close_issue=False,
            story_service=NoOpStoryService(),  # type: ignore[arg-type]
            integrity_gate=RecordingIntegrityGate(),  # type: ignore[arg-type]
            scan_port=RecordingScanPort(),
            build_test_port=None,  # FULL but no build runner -> wiring bug
            sanity_port=RecordingSanityPort(),
            artifact_manager=manager,
            doc_fidelity_port=RecordingDocFidelityPort(),
            vectordb_sync_port=RecordingVectorDbSyncPort(),
            guard_deactivation_port=RecordingGuardDeactivationPort(),
            git_backend=StubGitBackend(),
            progress_store=build_progress_store(s_dir),  # type: ignore[arg-type]
            merge_applicability=MergeApplicability.FULL,
        )
        handler = ClosurePhaseHandler(config)
        result = handler.on_enter(
            _make_ctx(project_root=tmp_path),
            PhaseEnvelopeStore.make_fresh_envelope(_make_state()),
        )
        assert result.status == PhaseStatus.ESCALATED
        assert any("Build/Test runner is not wired" in err for err in result.errors)

    def test_ci_absent_code_story_fails_closed(self, tmp_path: Path) -> None:
        """FIX-3: a declared-absent CI for a code-producing story FAILS CLOSED.

        CI_ABSENT means there is no Build/Test+scan runner -> the integrated
        candidate cannot be verified -> cannot merge unverified code (FK-29
        §29.1a / FK-33 §33.6.5). Decided at the applicability layer.
        """
        from agentkit.closure.merge_sequence import MergeApplicability

        s_dir = _prepare_impl_story(tmp_path)
        manager = build_artifact_manager(s_dir)
        _write_all_layer2(manager, story_id="TEST-001", run_id=_run_id_for("TEST-001"))
        git = StubGitBackend()
        config = ClosureConfig(
            story_dir=s_dir,
            close_issue=False,
            story_service=NoOpStoryService(),  # type: ignore[arg-type]
            integrity_gate=RecordingIntegrityGate(),  # type: ignore[arg-type]
            scan_port=None,
            build_test_port=None,
            sanity_port=RecordingSanityPort(),
            artifact_manager=manager,
            doc_fidelity_port=RecordingDocFidelityPort(),
            vectordb_sync_port=RecordingVectorDbSyncPort(),
            guard_deactivation_port=RecordingGuardDeactivationPort(),
            git_backend=git,
            progress_store=build_progress_store(s_dir),  # type: ignore[arg-type]
            merge_applicability=MergeApplicability.CI_ABSENT,
        )
        handler = ClosurePhaseHandler(config)
        result = handler.on_enter(
            _make_ctx(project_root=tmp_path),
            PhaseEnvelopeStore.make_fresh_envelope(_make_state()),
        )
        assert result.status == PhaseStatus.ESCALATED
        assert any("CI is declared absent" in err for err in result.errors)
        # No merge of unverified code.
        assert not any(cmd[:1] == ("push",) for cmd in git.commands)

    def test_sonar_absent_runs_build_and_merges_without_scan_or_dim9(
        self, tmp_path: Path
    ) -> None:
        """FIX-3: Sonar declared absent (CI present) -> Build/Test runs, scan+Dim9
        skipped, merge still gated + proceeds (no SONAR_NOT_GREEN)."""
        from agentkit.closure.merge_sequence import MergeApplicability

        s_dir = _prepare_impl_story(tmp_path)
        manager = build_artifact_manager(s_dir)
        _write_all_layer2(manager, story_id="TEST-001", run_id=_run_id_for("TEST-001"))
        scan = RecordingScanPort()
        build_test = RecordingBuildTestPort()
        integrity = RecordingIntegrityGate()
        git = StubGitBackend()
        config = ClosureConfig(
            story_dir=s_dir,
            close_issue=False,
            story_service=NoOpStoryService(),  # type: ignore[arg-type]
            integrity_gate=integrity,  # type: ignore[arg-type]
            scan_port=None,  # Sonar declared absent: no scan runner
            build_test_port=build_test,
            sanity_port=RecordingSanityPort(),
            artifact_manager=manager,
            doc_fidelity_port=RecordingDocFidelityPort(),
            vectordb_sync_port=RecordingVectorDbSyncPort(),
            guard_deactivation_port=RecordingGuardDeactivationPort(),
            git_backend=git,
            progress_store=build_progress_store(s_dir),  # type: ignore[arg-type]
            merge_applicability=MergeApplicability.SONAR_ABSENT,
        )
        handler = ClosurePhaseHandler(config)
        result = handler.on_enter(
            _make_ctx(project_root=tmp_path),
            PhaseEnvelopeStore.make_fresh_envelope(_make_state()),
        )
        assert result.status == PhaseStatus.COMPLETED
        # Build/Test RAN; the scan did not (Sonar absent); the gate ran WITHOUT a
        # fresh attestation (Dim 9 not-applicable); the merge proceeded.
        assert build_test.calls == ["build_test"]
        assert scan.calls == []  # scan port not even wired
        assert integrity.calls == ["gate"]
        assert integrity.received_fresh_attestation is None
        assert any(cmd[:1] == ("push",) for cmd in git.commands)


# ---------------------------------------------------------------------------
# E4: atomic CAS / force-with-lease main update
# ---------------------------------------------------------------------------


class TestAtomicMainUpdate:
    def test_main_update_uses_force_with_lease_against_locked_sha(
        self, tmp_path: Path
    ) -> None:
        """E4: the main update is an atomic CAS via --force-with-lease=main:<locked>."""
        s_dir = _prepare_impl_story(tmp_path)
        manager = build_artifact_manager(s_dir)
        _write_all_layer2(manager, story_id="TEST-001", run_id=_run_id_for("TEST-001"))
        git = StubGitBackend()
        config = _impl_config(s_dir, git_backend=git)
        handler = ClosurePhaseHandler(config)
        result = handler.on_enter(
            _make_ctx(project_root=tmp_path),
            PhaseEnvelopeStore.make_fresh_envelope(_make_state()),
        )

        assert result.status == PhaseStatus.COMPLETED
        lease = f"--force-with-lease=main:{git.main_sha}"
        # The main update is the lease push (CAS to the exact locked sha), never
        # an unconditional ``push origin main``.
        assert ("push", lease, "origin", "main") in git.commands
        assert ("push", "origin", "main") not in git.commands

    def test_lease_rejection_rolls_back_local_merge_no_clobber(
        self, tmp_path: Path
    ) -> None:
        """E4: a lease rejection (concurrent advance) rolls back -- never a clobber."""
        s_dir = _prepare_impl_story(tmp_path)
        manager = build_artifact_manager(s_dir)
        _write_all_layer2(manager, story_id="TEST-001", run_id=_run_id_for("TEST-001"))

        class _LeaseRejectGit(StubGitBackend):
            """Rejects ONLY the force-with-lease main push (concurrent advance)."""

            def run(self, repo, *args):  # type: ignore[no-untyped-def]
                if args[:1] == ("push",) and any(
                    a.startswith("--force-with-lease") for a in args
                ):
                    self.commands.append(args)
                    return GitCommandResult(
                        returncode=1, stderr="stale info: remote ref moved"
                    )
                return super().run(repo, *args)

        git = _LeaseRejectGit()
        integrity = RecordingIntegrityGate()
        config = _impl_config(s_dir, integrity=integrity, git_backend=git)
        handler = ClosurePhaseHandler(config)
        result = handler.on_enter(
            _make_ctx(project_root=tmp_path),
            PhaseEnvelopeStore.make_fresh_envelope(_make_state()),
        )

        assert result.status == PhaseStatus.ESCALATED
        # The local ff-merge was rolled back (reset --hard to the pre-merge sha),
        # never a forced overwrite of the concurrent advance.
        assert any(cmd[:1] == ("reset",) for cmd in git.commands)
        assert any("CAS rejected" in err for err in result.errors)
        # merge_done was NOT persisted (the CAS push failed).
        state = load_phase_state(s_dir)
        assert isinstance(state.payload, ClosurePayload)
        assert not state.payload.progress.merge_done
        # story_branch_pushed IS durable (the push landed; resumable, §29.1.3).
        assert state.payload.progress.story_branch_pushed


# ---------------------------------------------------------------------------
# Multi-repo boundary (WARNING-2 / Stop-and-ask #2): single-repo barrier only
# ---------------------------------------------------------------------------


class TestMultiRepo:
    """FIX-6: the in-scope multi-repo path (per-repo barrier + saga + CAS)."""

    def test_multi_repo_all_green_merges_all(self, tmp_path: Path) -> None:
        """FIX-6: all repos green -> per-repo barrier + push + ff-merge + CAS."""
        from agentkit.closure.merge_sequence import (
            MergeBlockStatus,
            run_pre_merge_and_merge_block,
        )
        from agentkit.closure.multi_repo_saga import ClosureRepo

        repos = (
            ClosureRepo(name="repo-a", repo_root=tmp_path / "a"),
            ClosureRepo(name="repo-b", repo_root=tmp_path / "b"),
        )
        scan = RecordingScanPort()
        build_test = RecordingBuildTestPort()
        integrity = RecordingIntegrityGate()
        git = StubGitBackend()
        result = run_pre_merge_and_merge_block(
            _make_ctx(project_root=tmp_path),
            story_dir=tmp_path,
            repos=repos,
            integrity_gate=integrity,  # type: ignore[arg-type]
            scan_port=scan,
            build_test_port=build_test,
            sanity_port=RecordingSanityPort(),
            git_backend=git,
        )

        assert result.status is MergeBlockStatus.MERGED
        assert result.progress.merge_done
        # The per-repo barrier ran for BOTH repos (build/test + scan + gate x2).
        assert build_test.calls == ["build_test", "build_test"]
        assert scan.calls == ["scan", "scan"]
        assert integrity.calls == ["gate", "gate"]
        # A per-repo CAS lease main update landed (E4) for each repo.
        lease_pushes = [
            cmd
            for cmd in git.commands
            if cmd[:1] == ("push",)
            and any(a.startswith("--force-with-lease") for a in cmd)
        ]
        assert len(lease_pushes) == 2

    def test_multi_repo_one_repo_gate_fail_blocks_all(self, tmp_path: Path) -> None:
        """FIX-6: one repo's Dim 9 fail escalates the whole block, no repo merged."""
        from agentkit.closure.merge_sequence import (
            MergeBlockStatus,
            run_pre_merge_and_merge_block,
        )
        from agentkit.closure.multi_repo_saga import ClosureRepo

        repos = (
            ClosureRepo(name="repo-a", repo_root=tmp_path / "a"),
            ClosureRepo(name="repo-b", repo_root=tmp_path / "b"),
        )
        git = StubGitBackend()
        integrity = RecordingIntegrityGate(passed=False, failure_reason="SONAR_NOT_GREEN")
        result = run_pre_merge_and_merge_block(
            _make_ctx(project_root=tmp_path),
            story_dir=tmp_path,
            repos=repos,
            integrity_gate=integrity,  # type: ignore[arg-type]
            scan_port=RecordingScanPort(),
            build_test_port=RecordingBuildTestPort(),
            sanity_port=RecordingSanityPort(),
            git_backend=git,
        )

        assert result.status is MergeBlockStatus.ESCALATED
        assert not result.progress.merge_done
        # Fail-closed on the first repo's gate -> NO repo merged (no push).
        assert not any(cmd[:1] == ("push",) for cmd in git.commands)

    def test_multi_repo_cas_failure_rolls_back_and_escalates(
        self, tmp_path: Path
    ) -> None:
        """FIX-6: a per-repo CAS rejection rolls back local merges + escalates."""
        from agentkit.closure.merge_sequence import (
            MergeBlockStatus,
            run_pre_merge_and_merge_block,
        )
        from agentkit.closure.multi_repo_saga import ClosureRepo

        class _LeaseRejectGit(StubGitBackend):
            """Rejects every force-with-lease main push (concurrent advance)."""

            def run(self, repo, *args):  # type: ignore[no-untyped-def]
                if args[:1] == ("push",) and any(
                    a.startswith("--force-with-lease") for a in args
                ):
                    self.commands.append(args)
                    return GitCommandResult(
                        returncode=1, stderr="stale info: remote ref moved"
                    )
                return super().run(repo, *args)

        repos = (
            ClosureRepo(name="repo-a", repo_root=tmp_path / "a"),
            ClosureRepo(name="repo-b", repo_root=tmp_path / "b"),
        )
        git = _LeaseRejectGit()
        result = run_pre_merge_and_merge_block(
            _make_ctx(project_root=tmp_path),
            story_dir=tmp_path,
            repos=repos,
            integrity_gate=RecordingIntegrityGate(),  # type: ignore[arg-type]
            scan_port=RecordingScanPort(),
            build_test_port=RecordingBuildTestPort(),
            sanity_port=RecordingSanityPort(),
            git_backend=git,
        )

        assert result.status is MergeBlockStatus.ESCALATED
        assert not result.progress.merge_done
        # The local ff-merges were rolled back (reset --hard), never a clobber.
        assert any(cmd[:1] == ("reset",) for cmd in git.commands)
        assert any("CAS rejected" in err for err in result.errors)

    def test_multi_repo_partial_remote_push_rolled_back(self, tmp_path: Path) -> None:
        """FIX-B: repo A's CAS push OK, repo B fails -> A's REMOTE rolled back.

        No repo's ``origin/main`` may carry the story merge after a failure. The
        already-advanced remote (repo A) is reset to its pre-merge sha with a
        ``--force-with-lease`` leased against the sha this run just wrote (a CAS,
        never a clobber), then the block escalates.
        """
        from agentkit.closure.merge_sequence import (
            MergeBlockStatus,
            run_pre_merge_and_merge_block,
        )
        from agentkit.closure.multi_repo_saga import ClosureRepo

        class _RepoBCasFailsGit(StubGitBackend):
            """repo-a's forward CAS push succeeds; repo-b's forward CAS fails."""

            def run(self, repo, *args):  # type: ignore[no-untyped-def]
                is_lease = args[:1] == ("push",) and any(
                    a.startswith("--force-with-lease") for a in args
                )
                # The forward CAS push targets the bare ``main`` refspec; the
                # rollback push targets ``<sha>:main`` -- only fail repo-b's
                # forward CAS (never the rollback of repo-a).
                forward_cas = is_lease and args[-1] == "main"
                if forward_cas and repo.name == "repo-b":
                    self.commands.append(args)
                    return GitCommandResult(
                        returncode=1, stderr="stale info: remote ref moved"
                    )
                return super().run(repo, *args)

        repos = (
            ClosureRepo(name="repo-a", repo_root=tmp_path / "a"),
            ClosureRepo(name="repo-b", repo_root=tmp_path / "b"),
        )
        git = _RepoBCasFailsGit()
        result = run_pre_merge_and_merge_block(
            _make_ctx(project_root=tmp_path),
            story_dir=tmp_path,
            repos=repos,
            integrity_gate=RecordingIntegrityGate(),  # type: ignore[arg-type]
            scan_port=RecordingScanPort(),
            build_test_port=RecordingBuildTestPort(),
            sanity_port=RecordingSanityPort(),
            git_backend=git,
        )

        assert result.status is MergeBlockStatus.ESCALATED
        assert not result.progress.merge_done
        # repo-a's forward CAS landed; repo-b's failed -> repo-a's REMOTE main is
        # rolled back via a ``--force-with-lease`` push to ``<pre_merge>:main``.
        rollback_pushes = [
            cmd
            for cmd in git.commands
            if cmd[:1] == ("push",)
            and any(a.startswith("--force-with-lease") for a in cmd)
            and cmd[-1].endswith(":main")
            and cmd[-1] != "main"
        ]
        assert rollback_pushes, "repo-a's remote main must be rolled back (FIX-B)"
        # The local ff-merges were reset too (no half-merge survives).
        assert any(cmd[:1] == ("reset",) for cmd in git.commands)

    def test_unreadable_post_merge_head_fails_closed_no_push(
        self, tmp_path: Path
    ) -> None:
        """FIX-B edge: an unreadable post-merge HEAD must NOT push the remote.

        After repo-a's successful local ff-merge, its ``rev-parse HEAD`` (the
        ``_local_head`` read whose sha is the rollback lease base) returns nothing.
        Pushing repo-a's remote would advance an ``origin/main`` whose just-pushed
        sha is unknown -- no later repo could ever roll it back (a fail-open). So
        the block must refuse repo-a's remote CAS push entirely, roll back every
        local ff-merge, and escalate -- EVEN THOUGH the CAS push command itself
        would have succeeded.
        """
        from agentkit.closure.merge_sequence import (
            MergeBlockStatus,
            run_pre_merge_and_merge_block,
        )
        from agentkit.closure.multi_repo_saga import ClosureRepo

        class _RepoAHeadUnreadableGit(StubGitBackend):
            """repo-a's 3rd ``rev-parse HEAD`` (the ``_local_head`` read) returns ``.

            Calls 1/2 (barrier candidate-commit capture + saga pre_merge_sha
            capture) succeed so the block reaches the CAS loop; the 3rd HEAD read
            -- the ``_local_head`` whose sha must be recorded for rollback -- comes
            back empty, simulating a post-merge HEAD that cannot be read.
            """

            def __init__(self) -> None:
                super().__init__()
                self._repo_a_head_reads = 0

            def run(self, repo, *args):  # type: ignore[no-untyped-def]
                if (
                    args[:2] == ("rev-parse", "HEAD")
                    and repo.name == "repo-a"
                ):
                    self._repo_a_head_reads += 1
                    if self._repo_a_head_reads >= 3:
                        self.commands.append(args)
                        return GitCommandResult(returncode=0, stdout="")
                return super().run(repo, *args)

        repos = (
            ClosureRepo(name="repo-a", repo_root=tmp_path / "a"),
            ClosureRepo(name="repo-b", repo_root=tmp_path / "b"),
        )
        git = _RepoAHeadUnreadableGit()
        result = run_pre_merge_and_merge_block(
            _make_ctx(project_root=tmp_path),
            story_dir=tmp_path,
            repos=repos,
            integrity_gate=RecordingIntegrityGate(),  # type: ignore[arg-type]
            scan_port=RecordingScanPort(),
            build_test_port=RecordingBuildTestPort(),
            sanity_port=RecordingSanityPort(),
            git_backend=git,
        )

        assert result.status is MergeBlockStatus.ESCALATED
        assert not result.progress.merge_done
        # repo-a's remote CAS push must NEVER have been issued (the bare ``main``
        # forward refspec): a remote may be advanced only if its just-pushed sha is
        # known and recorded for rollback coverage.
        forward_cas_pushes = [
            cmd
            for cmd in git.commands
            if cmd[:1] == ("push",)
            and any(a.startswith("--force-with-lease") for a in cmd)
            and cmd[-1] == "main"
        ]
        assert not forward_cas_pushes, "no remote may be advanced with an unknown sha"
        # All local ff-merges were rolled back (reset --hard to the pre-merge sha).
        assert any(cmd[:1] == ("reset",) for cmd in git.commands)
        assert any("post-merge HEAD unreadable" in err for err in result.errors)

    def test_multi_repo_each_repo_verified_against_own_root(
        self, tmp_path: Path
    ) -> None:
        """FIX-C: each repo is built/scanned against ITS OWN runner pair/root.

        With a per-repo ``RepoRunners`` mapping the merge block selects the pair
        keyed by ``repo.repo_root`` -- repo-a's runner verifies repo-a, repo-b's
        runner verifies repo-b (no shared first-repo root/ledger/tree).
        """
        from agentkit.closure.merge_sequence import (
            MergeBlockStatus,
            RepoRunners,
            run_pre_merge_and_merge_block,
        )
        from agentkit.closure.multi_repo_saga import ClosureRepo

        root_a = tmp_path / "a"
        root_b = tmp_path / "b"
        scan_a, scan_b = RecordingScanPort(), RecordingScanPort()
        build_a, build_b = RecordingBuildTestPort(), RecordingBuildTestPort()
        repo_runners = {
            root_a: RepoRunners(scan_port=scan_a, build_test_port=build_a),
            root_b: RepoRunners(scan_port=scan_b, build_test_port=build_b),
        }
        repos = (
            ClosureRepo(name="repo-a", repo_root=root_a),
            ClosureRepo(name="repo-b", repo_root=root_b),
        )
        git = StubGitBackend()
        result = run_pre_merge_and_merge_block(
            _make_ctx(project_root=tmp_path),
            story_dir=tmp_path,
            repos=repos,
            integrity_gate=RecordingIntegrityGate(),  # type: ignore[arg-type]
            scan_port=None,
            build_test_port=None,
            sanity_port=RecordingSanityPort(),
            git_backend=git,
            repo_runners=repo_runners,
        )

        assert result.status is MergeBlockStatus.MERGED
        # Each repo's OWN runner ran exactly once for ITS repo (not the shared
        # first-repo pair -- the single scan_port/build_test_port were None).
        assert scan_a.calls == ["scan"]
        assert scan_b.calls == ["scan"]
        assert build_a.calls == ["build_test"]
        assert build_b.calls == ["build_test"]


# ---------------------------------------------------------------------------
# Story-type switch (AC#5)
# ---------------------------------------------------------------------------


class TestStoryTypeSwitch:
    @pytest.mark.parametrize("story_type", [StoryType.CONCEPT, StoryType.RESEARCH])
    def test_concept_research_skips_merge_block(
        self, tmp_path: Path, story_type: StoryType
    ) -> None:
        """AC#5: concept/research skip finding-gate + gate + merge; booleans true."""
        s_dir = tmp_path / "stories" / "TEST-101"
        s_dir.mkdir(parents=True)
        for phase in ("setup", "implementation"):
            _save_snapshot(s_dir, phase, story_id="TEST-101")
        _save_flow(s_dir, story_id="TEST-101")
        _append_agent_start_event(s_dir, story_id="TEST-101")

        scan = RecordingScanPort()
        integrity = RecordingIntegrityGate()
        git = StubGitBackend()
        config = _impl_config(
            s_dir, scan=scan, integrity=integrity, git_backend=git
        )
        handler = ClosurePhaseHandler(config)
        ctx = _make_ctx(
            story_id="TEST-101",
            story_type=story_type,
            execution_route=None,
            project_root=tmp_path,
        )
        result = handler.on_enter(
            ctx, PhaseEnvelopeStore.make_fresh_envelope(_make_state(story_id="TEST-101"))
        )

        assert result.status == PhaseStatus.COMPLETED
        # No scan, no gate, no push for non-code stories.
        assert scan.calls == []
        assert integrity.calls == []
        assert not any(cmd[:1] == ("push",) for cmd in git.commands)
        # Booleans set directly true (FK-29 §29.1.1).
        state = load_phase_state(s_dir)
        assert isinstance(state.payload, ClosurePayload)
        progress = state.payload.progress
        assert progress.integrity_passed
        assert progress.story_branch_pushed
        assert progress.merge_done


# ---------------------------------------------------------------------------
# Fast-mode sanity-gate weiche (AC#6)
# ---------------------------------------------------------------------------


class TestFastModeWeiche:
    def test_fast_mode_uses_sanity_gate_not_scan_or_integrity(
        self, tmp_path: Path
    ) -> None:
        """AC#6: mode==fast uses the Sanity-Gate; scan/IntegrityGate NOT called."""
        s_dir = _prepare_impl_story(tmp_path)
        manager = build_artifact_manager(s_dir)
        _write_all_layer2(manager, story_id="TEST-001", run_id=_run_id_for("TEST-001"))
        scan = RecordingScanPort()
        integrity = RecordingIntegrityGate()
        sanity = RecordingSanityPort(passed=True)
        config = _impl_config(
            s_dir, scan=scan, integrity=integrity, sanity=sanity
        )
        handler = ClosurePhaseHandler(config)
        ctx = _make_ctx(project_root=tmp_path, mode=WireStoryMode.FAST)
        result = handler.on_enter(
            ctx, PhaseEnvelopeStore.make_fresh_envelope(_make_state())
        )

        assert result.status == PhaseStatus.COMPLETED
        assert sanity.calls == ["sanity"]
        # Negative: neither the Sonar scan nor the 9-dim gate is invoked in fast.
        assert scan.calls == []
        assert integrity.calls == []

    def test_fast_mode_sanity_violation_escalates(self, tmp_path: Path) -> None:
        """AC#6: a sanity violation (e.g. rebase conflict) -> ESCALATED."""
        s_dir = _prepare_impl_story(tmp_path)
        manager = build_artifact_manager(s_dir)
        _write_all_layer2(manager, story_id="TEST-001", run_id=_run_id_for("TEST-001"))
        sanity = RecordingSanityPort(passed=False, reason="rebase conflict")
        config = _impl_config(s_dir, sanity=sanity)
        handler = ClosurePhaseHandler(config)
        ctx = _make_ctx(project_root=tmp_path, mode=WireStoryMode.FAST)
        result = handler.on_enter(
            ctx, PhaseEnvelopeStore.make_fresh_envelope(_make_state())
        )
        assert result.status == PhaseStatus.ESCALATED


# ---------------------------------------------------------------------------
# Post-merge finalization non-blocking (AC#7, AC#10)
# ---------------------------------------------------------------------------


class TestPostMergeFinalization:
    def test_postflight_fail_is_warning_not_escalated(self, tmp_path: Path) -> None:
        """AC#7/AC#10: a postflight FAIL keeps COMPLETED + emits a Warning."""
        s_dir = _prepare_impl_story(tmp_path)
        manager = build_artifact_manager(s_dir)
        _write_all_layer2(manager, story_id="TEST-001", run_id=_run_id_for("TEST-001"))
        # No protocol.md and no agent_end event -> postflight checks FAIL, but the
        # story is already merged -> COMPLETED + Warning.
        config = _impl_config(s_dir)
        handler = ClosurePhaseHandler(config)
        result = handler.on_enter(
            _make_ctx(project_root=tmp_path),
            PhaseEnvelopeStore.make_fresh_envelope(_make_state()),
        )

        assert result.status == PhaseStatus.COMPLETED
        report = json.loads(
            (qa_story_dir(tmp_path, "TEST-001") / "closure.json").read_text(
                encoding="utf-8"
            )
        )
        assert report["status"] == "completed_with_warnings"
        assert any("postflight" in w for w in report["warnings"])

    def test_doc_fidelity_fail_is_warning_not_escalated(self, tmp_path: Path) -> None:
        """AC#7: a level-4 doc-fidelity FAIL is a non-blocking Warning."""
        s_dir = _prepare_impl_story(tmp_path)
        manager = build_artifact_manager(s_dir)
        _write_all_layer2(manager, story_id="TEST-001", run_id=_run_id_for("TEST-001"))
        doc = RecordingDocFidelityPort(passed=False, warning="docs need update")
        config = _impl_config(s_dir, doc_fidelity=doc)
        handler = ClosurePhaseHandler(config)
        result = handler.on_enter(
            _make_ctx(project_root=tmp_path),
            PhaseEnvelopeStore.make_fresh_envelope(_make_state()),
        )
        assert result.status == PhaseStatus.COMPLETED
        assert doc.calls == ["doc_fidelity"]


# ---------------------------------------------------------------------------
# Checkpoint persistence + config validation (AC#8, AC#11)
# ---------------------------------------------------------------------------


class TestCheckpointAndConfig:
    def test_progress_persisted_to_phase_state(self, tmp_path: Path) -> None:
        """AC#8: each substate boolean is persisted to the closure phase state."""
        s_dir = _prepare_impl_story(tmp_path)
        manager = build_artifact_manager(s_dir)
        _write_all_layer2(manager, story_id="TEST-001", run_id=_run_id_for("TEST-001"))
        config = _impl_config(s_dir)
        handler = ClosurePhaseHandler(config)
        result = handler.on_enter(
            _make_ctx(project_root=tmp_path),
            PhaseEnvelopeStore.make_fresh_envelope(_make_state()),
        )

        assert result.status == PhaseStatus.COMPLETED
        state = load_phase_state(s_dir)
        assert isinstance(state.payload, ClosurePayload)
        progress = state.payload.progress
        assert progress.integrity_passed
        assert progress.story_branch_pushed
        assert progress.merge_done
        assert progress.story_closed
        assert progress.metrics_written
        assert progress.postflight_done

    def test_unwired_merge_collaborators_fail_closed(self, tmp_path: Path) -> None:
        """AC#11: a bare ClosureConfig (no merge ports) for impl -> FAILED."""
        s_dir = _prepare_impl_story(tmp_path)
        config = ClosureConfig(
            story_dir=s_dir,
            close_issue=False,
            story_service=NoOpStoryService(),  # type: ignore[arg-type]
            doc_fidelity_port=RecordingDocFidelityPort(),
            vectordb_sync_port=RecordingVectorDbSyncPort(),
            guard_deactivation_port=RecordingGuardDeactivationPort(),
            progress_store=build_progress_store(s_dir),  # type: ignore[arg-type]
        )
        handler = ClosurePhaseHandler(config)
        result = handler.on_enter(
            _make_ctx(project_root=tmp_path),
            PhaseEnvelopeStore.make_fresh_envelope(_make_state()),
        )
        assert result.status == PhaseStatus.FAILED
        assert "merge collaborators not wired" in " ".join(result.errors)

    def test_unwired_finalization_collaborators_fail_closed(
        self, tmp_path: Path
    ) -> None:
        """AC#11: missing finalization ports -> FAILED (even concept/research)."""
        s_dir = tmp_path / "stories" / "TEST-101"
        s_dir.mkdir(parents=True)
        for phase in ("setup", "implementation"):
            _save_snapshot(s_dir, phase, story_id="TEST-101")
        config = ClosureConfig(
            story_dir=s_dir,
            close_issue=False,
            story_service=NoOpStoryService(),  # type: ignore[arg-type]
        )
        handler = ClosurePhaseHandler(config)
        ctx = _make_ctx(
            story_id="TEST-101", story_type=StoryType.RESEARCH, execution_route=None
        )
        result = handler.on_enter(
            ctx, PhaseEnvelopeStore.make_fresh_envelope(_make_state(story_id="TEST-101"))
        )
        assert result.status == PhaseStatus.FAILED
        assert "finalization collaborators not wired" in " ".join(result.errors)

    def test_fails_without_story_dir(self) -> None:
        config = ClosureConfig(story_dir=None, close_issue=False)
        handler = ClosurePhaseHandler(config)
        result = handler.on_enter(
            _make_ctx(), PhaseEnvelopeStore.make_fresh_envelope(_make_state())
        )
        assert result.status == PhaseStatus.FAILED
        assert "story_dir" in result.errors[0]


# ---------------------------------------------------------------------------
# Prior-phase validation (unchanged behaviour, kept)
# ---------------------------------------------------------------------------


class TestPriorPhaseValidation:
    def test_fails_when_prior_phase_missing(self, tmp_path: Path) -> None:
        s_dir = tmp_path / "stories" / "TEST-001"
        s_dir.mkdir(parents=True)
        _save_snapshot(s_dir, "setup")
        _save_snapshot(s_dir, "implementation")
        config = _impl_config(s_dir)
        handler = ClosurePhaseHandler(config)
        result = handler.on_enter(
            _make_ctx(project_root=tmp_path),
            PhaseEnvelopeStore.make_fresh_envelope(_make_state()),
        )
        assert result.status == PhaseStatus.FAILED
        assert "exploration" in " ".join(result.errors)

    def test_fails_when_prior_phase_failed(self, tmp_path: Path) -> None:
        s_dir = tmp_path / "stories" / "TEST-102"
        s_dir.mkdir(parents=True)
        for phase in ("setup", "exploration"):
            _save_snapshot(s_dir, phase, story_id="TEST-102")
        save_phase_snapshot(
            s_dir,
            PhaseSnapshot(
                story_id="TEST-102",
                phase="implementation",
                status=PhaseStatus.FAILED,
                completed_at=datetime.now(tz=UTC),
                artifacts=[],
                evidence={},
            ),
        )
        config = _impl_config(s_dir)
        handler = ClosurePhaseHandler(config)
        result = handler.on_enter(
            _make_ctx(story_id="TEST-102", project_root=tmp_path),
            PhaseEnvelopeStore.make_fresh_envelope(_make_state(story_id="TEST-102")),
        )
        assert result.status == PhaseStatus.FAILED
        assert "implementation" in " ".join(result.errors)


# ---------------------------------------------------------------------------
# Verdict enum
# ---------------------------------------------------------------------------


def test_closure_verdict_values() -> None:
    assert ClosureVerdict.COMPLETED.value == "COMPLETED"
    assert ClosureVerdict.ESCALATED.value == "ESCALATED"


# ---------------------------------------------------------------------------
# ExecutionReport (unchanged)
# ---------------------------------------------------------------------------


class TestExecutionReport:
    def test_execution_report_contains_correct_fields(self, tmp_path: Path) -> None:
        report = ExecutionReport(
            story_id="TEST-001",
            story_type="implementation",
            status="completed",
            phases_executed=("setup", "exploration", "implementation", "closure"),
            started_at="2026-01-01T00:00:00+00:00",
            completed_at="2026-01-01T01:00:00+00:00",
            story_closed=True,
            warnings=(),
        )
        data = report.to_dict()
        assert data["story_id"] == "TEST-001"
        assert len(data["phases_executed"]) == 4
        assert data["story_closed"] is True

    def test_write_execution_report_creates_file(self, tmp_path: Path) -> None:
        report = ExecutionReport(
            story_id="TEST-002",
            story_type="bugfix",
            status="completed",
            phases_executed=("setup", "implementation", "closure"),
        )
        path = write_execution_report(tmp_path, report)
        assert path == tmp_path / "closure.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["story_id"] == "TEST-002"
