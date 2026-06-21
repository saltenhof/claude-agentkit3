"""Recovery-dispatching tests for ``ClosurePhaseHandler.on_resume`` (AG3-053, AC#9).

FK-29 §29.1.3: ``on_resume`` dispatches over the persisted ``ClosureProgress``
booleans -- already-true substates are skipped, the sequence continues from the
first open substate, and an irreversible substate (``merge_done``) is never
re-run. There is no deterministic FAILED anymore.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from tests.phase_state_factory import make_phase_state
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

from agentkit.backend.bootstrap.composition_root import build_artifact_manager
from agentkit.backend.closure.phase import ClosureConfig, ClosurePhaseHandler
from agentkit.backend.core_types import ArtifactClass
from agentkit.backend.core_types.qa_artifact_names import (
    DOC_FIDELITY_PRODUCER,
    DOC_FIDELITY_STAGE,
    HANDOVER_FILE,
    PROTOCOL_FILE,
    QA_REVIEW_PRODUCER,
    QA_REVIEW_STAGE,
    SEMANTIC_REVIEW_PRODUCER,
    SEMANTIC_REVIEW_STAGE,
    WORKER_MANIFEST_FILE,
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
)
from agentkit.backend.story_context_manager.models import StoryContext
from agentkit.backend.story_context_manager.types import StoryMode, StoryType
from agentkit.backend.telemetry.contract.records import ExecutionEventRecord
from agentkit.backend.telemetry.events import EventType
from agentkit.backend.verify_system.structural.system_evidence import ChangeEvidence

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from agentkit.backend.artifacts import ArtifactManager


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
    _write_all_layer2(build_artifact_manager(s_dir), story_id=story_id)
    _write_required_worker_artifacts(s_dir, story_id=story_id)
    return s_dir


def _write_required_worker_artifacts(story_dir: Path, story_id: str) -> None:
    (story_dir / HANDOVER_FILE).write_text("handover\n", encoding="utf-8")
    (story_dir / PROTOCOL_FILE).write_text("protocol\n", encoding="utf-8")
    (story_dir / WORKER_MANIFEST_FILE).write_text(
        json.dumps(
            {
                "story_id": story_id,
                "run_id": f"run-{story_id.lower()}",
                "status": "completed",
                "completed_at": datetime(2026, 1, 1, tzinfo=UTC).isoformat(),
                "files_changed": ["src/agentkit/backend/done.py"],
                "tests_added": [],
                "acceptance_criteria_status": {"AC1": "done"},
            }
        ),
        encoding="utf-8",
    )


class _StaticChangeEvidencePort:
    def collect(self, story_dir: Path) -> ChangeEvidence:
        del story_dir
        return ChangeEvidence(
            available=True,
            changed_files=("src/agentkit/backend/done.py",),
        )


def _write_all_layer2(manager: ArtifactManager, *, story_id: str) -> None:
    from agentkit.backend.artifacts import (
        ArtifactEnvelope,
        EnvelopeStatus,
        Producer,
        ProducerId,
        ProducerType,
    )

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


def _config(
    s_dir: Path,
    *,
    scan: RecordingScanPort,
    integrity: RecordingIntegrityGate,
    git: StubGitBackend,
) -> ClosureConfig:
    return ClosureConfig(
        story_dir=s_dir,
        close_issue=False,
        story_service=NoOpStoryService(),  # type: ignore[arg-type]
        integrity_gate=integrity,  # type: ignore[arg-type]
        scan_port=scan,
        build_test_port=RecordingBuildTestPort(),
        sanity_port=RecordingSanityPort(),
        artifact_manager=build_artifact_manager(s_dir),
        doc_fidelity_port=RecordingDocFidelityPort(),
        vectordb_sync_port=RecordingVectorDbSyncPort(),
        guard_deactivation_port=RecordingGuardDeactivationPort(),
        git_backend=git,
        progress_store=build_progress_store(s_dir),  # type: ignore[arg-type]
        change_evidence_port=_StaticChangeEvidencePort(),
    )


def _ctx(tmp_path: Path, story_id: str = "TEST-001") -> StoryContext:
    return StoryContext(
        project_key="test-project",
        story_id=story_id,
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXECUTION,
        project_root=tmp_path,
    )


def _envelope(story_id: str, progress: ClosureProgress) -> object:
    state = make_phase_state(
        story_id=story_id,
        phase="closure",
        status=PhaseStatus.IN_PROGRESS,
        payload=ClosurePayload(progress=progress),
    )
    return PhaseEnvelopeStore.make_fresh_envelope(state)


class TestClosureResume:
    def test_resume_with_merge_done_skips_merge(self, tmp_path: Path) -> None:
        """AC#9: merge_done=true -> no re-scan, no re-gate, no re-push."""
        s_dir = _prepare(tmp_path)
        scan = RecordingScanPort()
        integrity = RecordingIntegrityGate()
        git = StubGitBackend()
        handler = ClosurePhaseHandler(
            _config(s_dir, scan=scan, integrity=integrity, git=git)
        )
        progress = ClosureProgress(
            integrity_passed=True, story_branch_pushed=True, merge_done=True
        )

        result = handler.on_resume(
            _ctx(tmp_path), _envelope("TEST-001", progress), "operator_retry"
        )

        assert result.status == PhaseStatus.COMPLETED
        # Irreversible merge substate not re-run.
        assert scan.calls == []
        assert integrity.calls == []
        assert not any(cmd[:1] == ("push",) for cmd in git.commands)
        # The remaining substates ran and were persisted.
        state = load_phase_state(s_dir)
        assert isinstance(state.payload, ClosurePayload)
        assert state.payload.progress.story_closed
        assert state.payload.progress.metrics_written
        assert state.payload.progress.postflight_done

    def test_resume_from_open_merge_runs_block(self, tmp_path: Path) -> None:
        """AC#9: an open merge (merge_done=false) re-runs the full block."""
        s_dir = _prepare(tmp_path)
        scan = RecordingScanPort()
        integrity = RecordingIntegrityGate()
        git = StubGitBackend()
        handler = ClosurePhaseHandler(
            _config(s_dir, scan=scan, integrity=integrity, git=git)
        )

        result = handler.on_resume(
            _ctx(tmp_path), _envelope("TEST-001", ClosureProgress()), "operator_retry"
        )

        assert result.status == PhaseStatus.COMPLETED
        assert scan.calls == ["scan"]
        assert integrity.calls == ["gate"]
        assert any(cmd[:1] == ("push",) for cmd in git.commands)

    def test_resume_after_push_before_merge_skips_to_merge_no_rescan(
        self, tmp_path: Path
    ) -> None:
        """FIX-A: a ``story_branch_pushed`` resume SKIPS scan/gate/push.

        FK-29 §29.1.0/§29.1.3: the granular booleans are recovery checkpoints; a
        ``story_branch_pushed=true`` resume goes STRAIGHT to the ff/CAS merge of
        the already-pushed, already-verified branch -- NO re-scan, NO re-gate, NO
        re-push of the story branch. Dim 1-9 (proven on the original run) is not
        re-run. The single main update is the CAS lease (no double-merge).
        """
        s_dir = _prepare(tmp_path)
        scan = RecordingScanPort()
        integrity = RecordingIntegrityGate()
        git = StubGitBackend()
        handler = ClosurePhaseHandler(
            _config(s_dir, scan=scan, integrity=integrity, git=git)
        )
        # Crash state: story branch pushed, but merge not yet done.
        progress = ClosureProgress(integrity_passed=True, story_branch_pushed=True)

        result = handler.on_resume(
            _ctx(tmp_path), _envelope("TEST-001", progress), "operator_retry"
        )

        assert result.status == PhaseStatus.COMPLETED
        # FIX-A: NO re-scan, NO re-gate (integrity already proven on the run).
        assert scan.calls == []
        assert integrity.calls == []
        # NO story-branch push (it already landed); only the ff/CAS main update.
        story_pushes = [
            cmd
            for cmd in git.commands
            if cmd[:1] == ("push",)
            and not any(a.startswith("--force-with-lease") for a in cmd)
        ]
        assert story_pushes == []
        lease_pushes = [
            cmd
            for cmd in git.commands
            if cmd[:1] == ("push",)
            and any(a.startswith("--force-with-lease") for a in cmd)
        ]
        assert len(lease_pushes) == 1  # exactly one main update (no double-merge)
        state = load_phase_state(s_dir)
        assert isinstance(state.payload, ClosurePayload)
        assert state.payload.progress.merge_done

    def test_resume_after_integrity_before_push_skips_to_push(
        self, tmp_path: Path
    ) -> None:
        """FIX-A: an ``integrity_passed`` (not pushed) resume SKIPS scan/gate.

        Dim 1-9 already PASSed on the original run, so the resume re-pushes the
        story branch (idempotent) then ff/CAS-merges -- NO re-scan, NO re-gate.
        """
        s_dir = _prepare(tmp_path)
        scan = RecordingScanPort()
        integrity = RecordingIntegrityGate()
        git = StubGitBackend()
        handler = ClosurePhaseHandler(
            _config(s_dir, scan=scan, integrity=integrity, git=git)
        )
        progress = ClosureProgress(integrity_passed=True)

        result = handler.on_resume(
            _ctx(tmp_path), _envelope("TEST-001", progress), "operator_retry"
        )

        assert result.status == PhaseStatus.COMPLETED
        # FIX-A: integrity already proven -> NO re-scan, NO re-gate.
        assert scan.calls == []
        assert integrity.calls == []
        # The story branch is (idempotently) re-pushed, then ff/CAS-merged.
        story_pushes = [
            cmd
            for cmd in git.commands
            if cmd[:1] == ("push",)
            and not any(a.startswith("--force-with-lease") for a in cmd)
        ]
        assert len(story_pushes) == 1
        lease_pushes = [
            cmd
            for cmd in git.commands
            if cmd[:1] == ("push",)
            and any(a.startswith("--force-with-lease") for a in cmd)
        ]
        assert len(lease_pushes) == 1
        state = load_phase_state(s_dir)
        assert isinstance(state.payload, ClosurePayload)
        assert state.payload.progress.merge_done

    def test_resume_after_push_main_diverged_lease_fail_escalates(
        self, tmp_path: Path
    ) -> None:
        """FIX-A: a ``story_branch_pushed`` resume where main diverged -> escalate.

        The skip-to-merge ff/CAS is the ONLY safety without a persisted candidate:
        if ``origin/main`` advanced so the CAS lease is rejected (main diverged),
        the resume FAILS CLOSED (escalates) -- it never re-scans silently and never
        forces a non-ff merge over the concurrent advance.
        """
        from agentkit.backend.closure.multi_repo_saga import GitCommandResult

        class _LeaseRejectGit(StubGitBackend):
            def run(self, repo, *args):  # type: ignore[no-untyped-def]
                if args[:1] == ("push",) and any(
                    a.startswith("--force-with-lease") for a in args
                ):
                    self.commands.append(args)
                    return GitCommandResult(
                        returncode=1, stderr="stale info: remote ref moved"
                    )
                return super().run(repo, *args)

        s_dir = _prepare(tmp_path)
        scan = RecordingScanPort()
        integrity = RecordingIntegrityGate()
        git = _LeaseRejectGit()
        handler = ClosurePhaseHandler(
            _config(s_dir, scan=scan, integrity=integrity, git=git)
        )
        progress = ClosureProgress(integrity_passed=True, story_branch_pushed=True)

        result = handler.on_resume(
            _ctx(tmp_path), _envelope("TEST-001", progress), "operator_retry"
        )

        assert result.status == PhaseStatus.ESCALATED
        # Fail-closed: NO re-scan, NO re-gate, and merge_done was never set.
        assert scan.calls == []
        assert integrity.calls == []
        assert any("CAS rejected" in err for err in result.errors)
        state = load_phase_state(s_dir)
        assert isinstance(state.payload, ClosurePayload)
        assert not state.payload.progress.merge_done

    def test_resume_with_metrics_written_does_not_rewrite_metrics(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """FIX-5: a metrics_written resume re-materialises metrics WITHOUT a second
        ``write_projection`` (no rewrite/clobber)."""
        from agentkit.backend.bootstrap import composition_root as comp_root

        s_dir = _prepare(tmp_path)
        handler = ClosurePhaseHandler(
            _config(
                s_dir,
                scan=RecordingScanPort(),
                integrity=RecordingIntegrityGate(),
                git=StubGitBackend(),
            )
        )
        # First run to completion so a metrics projection exists.
        first = handler.on_resume(
            _ctx(tmp_path), _envelope("TEST-001", ClosureProgress()), "retry"
        )
        assert first.status == PhaseStatus.COMPLETED

        # FIX-5: on a metrics_written resume the handler must NOT call
        # ``build_projection_accessor`` (the projection-write path) at all.
        def _boom(_store_dir: object) -> object:
            msg = "build_projection_accessor must not run on a metrics_written resume"
            raise AssertionError(msg)

        monkeypatch.setattr(comp_root, "build_projection_accessor", _boom)
        progress = ClosureProgress(
            integrity_passed=True,
            story_branch_pushed=True,
            merge_done=True,
            story_closed=True,
            metrics_written=True,
        )
        result = handler.on_resume(
            _ctx(tmp_path), _envelope("TEST-001", progress), "retry"
        )
        assert result.status == PhaseStatus.COMPLETED

    def test_resume_with_metrics_written_reuses_persisted_completed_at(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """FIX-D: a metrics_written resume returns the PERSISTED row (same
        ``completed_at``), NOT a rebuild with a fresh timestamp."""
        from agentkit.backend.closure import phase as phase_mod
        from agentkit.backend.state_backend.store import load_story_metrics

        s_dir = _prepare(tmp_path)
        handler = ClosurePhaseHandler(
            _config(
                s_dir,
                scan=RecordingScanPort(),
                integrity=RecordingIntegrityGate(),
                git=StubGitBackend(),
            )
        )
        # First run to completion persists a metrics projection with a completed_at.
        first = handler.on_resume(
            _ctx(tmp_path), _envelope("TEST-001", ClosureProgress()), "retry"
        )
        assert first.status == PhaseStatus.COMPLETED
        persisted = load_story_metrics(s_dir, story_id="TEST-001")
        assert persisted
        original_completed_at = persisted[-1].completed_at

        # A rebuild on resume would stamp a DIFFERENT completed_at; force a new
        # clock so a rebuild would be detectable.
        monkeypatch.setattr(phase_mod, "_completed_at", lambda: datetime(
            2099, 12, 31, 23, 59, 59, tzinfo=UTC
        ))
        progress = ClosureProgress(
            integrity_passed=True,
            story_branch_pushed=True,
            merge_done=True,
            story_closed=True,
            metrics_written=True,
        )
        result = handler.on_resume(
            _ctx(tmp_path), _envelope("TEST-001", progress), "retry"
        )
        assert result.status == PhaseStatus.COMPLETED
        # The persisted row is unchanged and is what the resume reused.
        after = load_story_metrics(s_dir, story_id="TEST-001")
        assert [r.completed_at for r in after] == [original_completed_at]
        assert "2099" not in original_completed_at

    def test_resume_with_postflight_done_skips_finalization(
        self, tmp_path: Path
    ) -> None:
        """FIX-5: postflight_done resume does NOT re-run finalization (no rerun)."""
        s_dir = _prepare(tmp_path)
        doc = RecordingDocFidelityPort()
        guard = RecordingGuardDeactivationPort()
        config = ClosureConfig(
            story_dir=s_dir,
            close_issue=False,
            story_service=NoOpStoryService(),  # type: ignore[arg-type]
            integrity_gate=RecordingIntegrityGate(),  # type: ignore[arg-type]
            scan_port=RecordingScanPort(),
            build_test_port=RecordingBuildTestPort(),
            sanity_port=RecordingSanityPort(),
            artifact_manager=build_artifact_manager(s_dir),
            doc_fidelity_port=doc,
            vectordb_sync_port=RecordingVectorDbSyncPort(),
            guard_deactivation_port=guard,
            git_backend=StubGitBackend(),
            progress_store=build_progress_store(s_dir),  # type: ignore[arg-type]
            change_evidence_port=_StaticChangeEvidencePort(),
        )
        handler = ClosurePhaseHandler(config)
        # First run to completion so a metrics projection exists (postflight_done
        # resume re-materialises metrics from it but skips finalization).
        first = handler.on_resume(
            _ctx(tmp_path), _envelope("TEST-001", ClosureProgress()), "retry"
        )
        assert first.status == PhaseStatus.COMPLETED
        doc.calls.clear()
        guard.calls.clear()

        progress = ClosureProgress(
            integrity_passed=True,
            story_branch_pushed=True,
            merge_done=True,
            story_closed=True,
            metrics_written=True,
            postflight_done=True,
        )
        result = handler.on_resume(
            _ctx(tmp_path), _envelope("TEST-001", progress), "retry"
        )
        assert result.status == PhaseStatus.COMPLETED
        # Finalization (doc-fidelity / guard) was NOT re-run.
        assert doc.calls == []
        assert guard.calls == []

    def test_resume_does_not_return_deterministic_failed(self, tmp_path: Path) -> None:
        """AC#9: legacy deterministic-FAILED resume behaviour is gone."""
        s_dir = _prepare(tmp_path)
        handler = ClosurePhaseHandler(
            _config(
                s_dir,
                scan=RecordingScanPort(),
                integrity=RecordingIntegrityGate(),
                git=StubGitBackend(),
            )
        )
        result = handler.on_resume(
            _ctx(tmp_path), _envelope("TEST-001", ClosureProgress()), "any_trigger"
        )
        assert result.status != PhaseStatus.FAILED
