"""Unit tests for the closure phase handler and execution report.

Uses ``save_phase_snapshot`` to create real phase snapshots
on disk (no manual state construction). GitHub ``close_issue``
is monkeypatched in tests that exercise error paths.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.exceptions import IntegrationError
from agentkit.installer.paths import qa_story_dir
from agentkit.phase_state_store.models import FlowExecution
from agentkit.pipeline.phases.closure.execution_report import (
    ExecutionReport,
    write_execution_report,
)
from agentkit.pipeline.phases.closure.phase import (
    ClosureConfig,
    ClosurePhaseHandler,
)
from agentkit.pipeline.state import save_phase_snapshot
from agentkit.pipeline_engine.phase_executor.records import AttemptRecord
from agentkit.state_backend.store import (
    append_execution_event,
    load_story_metrics,
    save_attempt,
    save_flow_execution,
    save_story_context,
)
from agentkit.story_context_manager.models import (
    PhaseSnapshot,
    PhaseState,
    PhaseStatus,
    StoryContext,
)
from agentkit.story_context_manager.types import StoryMode, StoryType
from agentkit.telemetry.contract.records import ExecutionEventRecord
from agentkit.telemetry.events import EventType

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
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
    execution_route: StoryMode = StoryMode.EXECUTION,
    project_root: Path | None = None,
) -> StoryContext:
    """Create a minimal ``StoryContext`` for testing."""
    return StoryContext(
        project_key=project_key,
        story_id=story_id,
        story_type=story_type,
        execution_route=execution_route,
        project_root=project_root,
    )


def _make_state(
    *,
    story_id: str = "TEST-001",
    phase: str = "closure",
    status: PhaseStatus = PhaseStatus.IN_PROGRESS,
) -> PhaseState:
    """Create a ``PhaseState`` for testing."""
    return PhaseState(
        story_id=story_id,
        phase=phase,
        status=status,
    )


def _save_snapshot(story_dir: Path, phase: str, story_id: str = "TEST-001") -> None:
    """Persist a completed phase snapshot to disk."""
    snapshot = PhaseSnapshot(
        story_id=story_id,
        phase=phase,
        status=PhaseStatus.COMPLETED,
        completed_at=datetime.now(tz=UTC),
        artifacts=[],
        evidence={},
    )
    save_phase_snapshot(story_dir, snapshot)


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


def _run_id_for(story_id: str) -> str:
    return f"run-{story_id.lower()}"


def _append_agent_start_event(
    story_dir: Path,
    *,
    story_id: str = "TEST-001",
    project_key: str = "test-project",
    occurred_at: datetime | None = None,
) -> None:
    event_time = occurred_at or datetime(2026, 1, 1, 9, 45, 0, tzinfo=UTC)
    append_execution_event(
        story_dir,
        ExecutionEventRecord(
            project_key=project_key,
            story_id=story_id,
            run_id=_run_id_for(story_id),
            event_id=(
                f"evt-agent-start-{story_id.lower()}-"
                f"{event_time.strftime('%H%M%S')}"
            ),
            event_type=EventType.AGENT_START.value,
            occurred_at=event_time,
            source_component="telemetry-test",
            severity="info",
            payload={"subagent_type": "worker"},
        ),
    )


def _append_increment_event(
    story_dir: Path,
    story_id: str = "TEST-001",
    project_key: str = "test-project",
) -> None:
    append_execution_event(
        story_dir,
        ExecutionEventRecord(
            project_key=project_key,
            story_id=story_id,
            run_id=_run_id_for(story_id),
            event_id="evt-increment-001",
            event_type=EventType.INCREMENT_COMMIT.value,
            occurred_at=datetime(2026, 1, 1, 10, 5, 0, tzinfo=UTC),
            source_component="telemetry-test",
            severity="info",
            payload={"increment_number": 1},
        ),
    )


# ---------------------------------------------------------------------------
# ClosurePhaseHandler tests
# ---------------------------------------------------------------------------


class TestClosurePhaseHandler:
    """Tests for ``ClosurePhaseHandler.on_enter``."""

    def test_closure_completes_when_all_prior_phases_done(
        self,
        tmp_path: Path,
    ) -> None:
        """Closure succeeds when all prior phase snapshots exist."""
        # Implementation profile: setup, exploration, implementation, closure
        s_dir = tmp_path / "stories" / "TEST-001"
        s_dir.mkdir(parents=True)
        for phase in ("setup", "exploration", "implementation"):
            _save_snapshot(s_dir, phase)
        _save_flow(s_dir)
        _append_agent_start_event(s_dir)

        config = ClosureConfig(story_dir=s_dir, close_issue=False)
        handler = ClosurePhaseHandler(config)
        ctx = _make_ctx(project_root=tmp_path)
        state = _make_state()

        result = handler.on_enter(ctx, state)

        assert result.status == PhaseStatus.COMPLETED
        assert len(result.errors) == 0

    def test_closure_fails_when_prior_phase_missing(
        self,
        tmp_path: Path,
    ) -> None:
        """Closure fails when a required prior phase snapshot is missing."""
        s_dir = tmp_path / "stories" / "TEST-001"
        s_dir.mkdir(parents=True)
        # Save setup and implementation but NOT exploration
        _save_snapshot(s_dir, "setup")
        _save_snapshot(s_dir, "implementation")

        config = ClosureConfig(story_dir=s_dir, close_issue=False)
        handler = ClosurePhaseHandler(config)
        ctx = _make_ctx(project_root=tmp_path)
        state = _make_state()

        result = handler.on_enter(ctx, state)

        assert result.status == PhaseStatus.FAILED
        assert len(result.errors) >= 1
        error_text = " ".join(result.errors)
        assert "exploration" in error_text

    def test_closure_writes_execution_report(self, tmp_path: Path) -> None:
        """Closure writes ``closure.json`` with execution summary."""
        s_dir = tmp_path / "stories" / "TEST-001"
        s_dir.mkdir(parents=True)
        for phase in ("setup", "exploration", "implementation"):
            _save_snapshot(s_dir, phase)
        _save_flow(s_dir)
        _append_agent_start_event(s_dir)
        _append_increment_event(s_dir)

        config = ClosureConfig(story_dir=s_dir, close_issue=False)
        handler = ClosurePhaseHandler(config)
        ctx = _make_ctx(project_root=tmp_path)
        state = _make_state()

        handler.on_enter(ctx, state)

        report_path = qa_story_dir(tmp_path, "TEST-001") / "closure.json"
        assert report_path.exists()

        with report_path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        assert data["story_id"] == "TEST-001"
        assert data["story_type"] == "implementation"
        assert data["status"] == "completed"
        assert isinstance(data["phases_executed"], list)
        assert "closure" in data["phases_executed"]
        assert data["metrics"]["qa_rounds"] == 0
        assert data["metrics"]["increments"] == 1
        metrics = load_story_metrics(s_dir)
        assert len(metrics) == 1
        assert metrics[0].mode == "execution"

    def test_closure_without_github_config(self, tmp_path: Path) -> None:
        """Closure works without GitHub configuration (no issue close)."""
        s_dir = tmp_path / "stories" / "TEST-001"
        s_dir.mkdir(parents=True)
        for phase in ("setup", "exploration", "implementation"):
            _save_snapshot(s_dir, phase)
        _save_flow(s_dir)
        _append_agent_start_event(s_dir)

        # No owner/repo/issue_nr
        config = ClosureConfig(story_dir=s_dir)
        handler = ClosurePhaseHandler(config)
        ctx = _make_ctx(project_root=tmp_path)
        state = _make_state()

        result = handler.on_enter(ctx, state)

        assert result.status == PhaseStatus.COMPLETED

        with (qa_story_dir(tmp_path, "TEST-001") / "closure.json").open(
            "r",
            encoding="utf-8",
        ) as f:
            data = json.load(f)
        assert data["issue_closed"] is False

    def test_closure_github_error_is_warning_not_failure(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """GitHub issue close failure produces warning, not FAILED status."""
        s_dir = tmp_path / "stories" / "TEST-001"
        s_dir.mkdir(parents=True)
        for phase in ("setup", "exploration", "implementation"):
            _save_snapshot(s_dir, phase)
        _save_flow(s_dir)
        _append_agent_start_event(s_dir)

        config = ClosureConfig(
            owner="owner",
            repo="repo",
            issue_nr=99999,
            close_issue=True,
            story_dir=s_dir,
        )

        # Monkeypatch close_issue to raise IntegrationError
        def _raise_integration_error(
            owner: str,
            repo: str,
            issue_nr: int,
        ) -> None:
            raise IntegrationError("Issue not found")

        monkeypatch.setattr(
            "agentkit.integrations.github.issues.close_issue",
            _raise_integration_error,
        )

        handler = ClosurePhaseHandler(config)
        ctx = _make_ctx(project_root=tmp_path)
        state = _make_state()

        result = handler.on_enter(ctx, state)

        assert result.status == PhaseStatus.COMPLETED
        assert len(result.errors) == 0

        with (qa_story_dir(tmp_path, "TEST-001") / "closure.json").open(
            "r",
            encoding="utf-8",
        ) as f:
            data = json.load(f)
        assert data["status"] == "completed_with_warnings"
        assert data["issue_closed"] is False
        assert len(data["warnings"]) > 0

    def test_closure_does_not_support_resume(self, tmp_path: Path) -> None:
        """``on_resume`` returns FAILED."""
        config = ClosureConfig(story_dir=tmp_path)
        handler = ClosurePhaseHandler(config)
        ctx = _make_ctx()
        state = _make_state()

        result = handler.on_resume(ctx, state, "some_trigger")

        assert result.status == PhaseStatus.FAILED
        assert "resume" in result.errors[0].lower()

    def test_closure_research_story_has_fewer_prior_phases(
        self,
        tmp_path: Path,
    ) -> None:
        """Research stories only need setup + implementation snapshots.

        Research profile phases: setup, implementation, closure.
        """
        s_dir = tmp_path / "stories" / "TEST-101"
        s_dir.mkdir(parents=True)
        _save_snapshot(s_dir, "setup", story_id="TEST-101")
        _save_snapshot(s_dir, "implementation", story_id="TEST-101")
        _save_flow(s_dir, story_id="TEST-101")
        _append_agent_start_event(s_dir, story_id="TEST-101")

        config = ClosureConfig(story_dir=s_dir, close_issue=False)
        handler = ClosurePhaseHandler(config)
        ctx = _make_ctx(
            story_id="TEST-101",
            story_type=StoryType.RESEARCH,
            execution_route=StoryMode.NOT_APPLICABLE,
            project_root=tmp_path,
        )
        state = _make_state(story_id="TEST-101")

        result = handler.on_enter(ctx, state)

        assert result.status == PhaseStatus.COMPLETED

    def test_closure_fails_without_story_dir(self) -> None:
        """Closure fails when story_dir is not configured."""
        config = ClosureConfig(story_dir=None, close_issue=False)
        handler = ClosurePhaseHandler(config)
        ctx = _make_ctx()
        state = _make_state()

        result = handler.on_enter(ctx, state)

        assert result.status == PhaseStatus.FAILED
        assert "story_dir" in result.errors[0]

    def test_closure_fails_when_prior_phase_has_failed_snapshot(
        self,
        tmp_path: Path,
    ) -> None:
        """Closure returns FAILED when a prior phase snapshot has FAILED status.

        A snapshot that exists but has status != COMPLETED must be
        rejected -- presence alone is not sufficient.
        """
        s_dir = tmp_path / "stories" / "TEST-102"
        s_dir.mkdir(parents=True)

        # Save completed snapshots for setup and exploration
        _save_snapshot(s_dir, "setup", story_id="TEST-102")
        _save_snapshot(s_dir, "exploration", story_id="TEST-102")

        # Save a FAILED snapshot for implementation
        failed_snapshot = PhaseSnapshot(
            story_id="TEST-102",
            phase="implementation",
            status=PhaseStatus.FAILED,
            completed_at=datetime.now(tz=UTC),
            artifacts=[],
            evidence={},
        )
        save_phase_snapshot(s_dir, failed_snapshot)

        config = ClosureConfig(story_dir=s_dir, close_issue=False)
        handler = ClosurePhaseHandler(config)
        ctx = _make_ctx(story_id="TEST-102", project_root=tmp_path)
        state = _make_state(story_id="TEST-102")

        result = handler.on_enter(ctx, state)

        assert result.status == PhaseStatus.FAILED
        assert len(result.errors) >= 1
        error_text = " ".join(result.errors)
        assert "implementation" in error_text
        assert "failed" in error_text

    def test_closure_fails_when_prior_phase_has_escalated_snapshot(
        self,
        tmp_path: Path,
    ) -> None:
        """Closure returns FAILED when a prior phase has ESCALATED status.

        ESCALATED means the phase exceeded retry limits -- closure
        must not proceed.
        """
        s_dir = tmp_path / "stories" / "TEST-103"
        s_dir.mkdir(parents=True)

        # Save completed snapshots before implementation.
        for phase in ("setup", "exploration"):
            _save_snapshot(s_dir, phase, story_id="TEST-103")

        # Save an ESCALATED snapshot for implementation.
        escalated_snapshot = PhaseSnapshot(
            story_id="TEST-103",
            phase="implementation",
            status=PhaseStatus.ESCALATED,
            completed_at=datetime.now(tz=UTC),
            artifacts=[],
            evidence={},
        )
        save_phase_snapshot(s_dir, escalated_snapshot)

        config = ClosureConfig(story_dir=s_dir, close_issue=False)
        handler = ClosurePhaseHandler(config)
        ctx = _make_ctx(story_id="TEST-103", project_root=tmp_path)
        state = _make_state(story_id="TEST-103")

        result = handler.on_enter(ctx, state)

        assert result.status == PhaseStatus.FAILED
        assert len(result.errors) >= 1
        error_text = " ".join(result.errors)
        assert "implementation" in error_text
        assert "escalated" in error_text

    def test_closure_uses_implementation_attempts_for_qa_rounds(self, tmp_path: Path) -> None:
        s_dir = tmp_path / "stories" / "TEST-104"
        s_dir.mkdir(parents=True)
        for phase in ("setup", "exploration", "implementation"):
            _save_snapshot(s_dir, phase, story_id="TEST-104")
        _save_flow(s_dir, story_id="TEST-104")
        _append_agent_start_event(s_dir, story_id="TEST-104")
        ctx = _make_ctx(story_id="TEST-104", project_root=tmp_path)
        state = _make_state(story_id="TEST-104")
        handler = ClosurePhaseHandler(ClosureConfig(story_dir=s_dir, close_issue=False))
        save_story_context(s_dir, ctx)

        append_execution_event(
            s_dir,
            ExecutionEventRecord(
                project_key=s_dir.parent.parent.name,
                story_id="TEST-104",
                run_id=_run_id_for("TEST-104"),
                event_id="evt-noise-001",
                event_type=EventType.WARNING.value,
                occurred_at=datetime(2026, 1, 1, 10, 6, 0, tzinfo=UTC),
                source_component="telemetry-test",
                severity="info",
                payload={},
            ),
        )

        save_attempt(
            s_dir,
            AttemptRecord(
                attempt_id="implementation-001",
                phase="implementation",
                entered_at=datetime(2026, 1, 1, 10, 1, 0, tzinfo=UTC),
                exit_status=PhaseStatus.FAILED,
            ),
        )
        save_attempt(
            s_dir,
            AttemptRecord(
                attempt_id="implementation-002",
                phase="implementation",
                entered_at=datetime(2026, 1, 1, 10, 2, 0, tzinfo=UTC),
                exit_status=PhaseStatus.COMPLETED,
            ),
        )

        result = handler.on_enter(ctx, state)

        assert result.status == PhaseStatus.COMPLETED
        metrics = load_story_metrics(s_dir)
        assert len(metrics) == 1
        assert metrics[0].qa_rounds == 2

    def test_closure_fails_without_canonical_run_id(self, tmp_path: Path) -> None:
        s_dir = tmp_path / "stories" / "TEST-105"
        s_dir.mkdir(parents=True)
        for phase in ("setup", "exploration", "implementation"):
            _save_snapshot(s_dir, phase, story_id="TEST-105")

        handler = ClosurePhaseHandler(ClosureConfig(story_dir=s_dir, close_issue=False))
        ctx = _make_ctx(story_id="TEST-105", project_root=tmp_path)
        state = _make_state(story_id="TEST-105")

        result = handler.on_enter(ctx, state)

        assert result.status == PhaseStatus.FAILED
        assert result.errors == (
            "Failed to materialize story metrics: Cannot build story metrics "
            "without a canonical run_id",
        )

    def test_closure_processing_time_uses_first_agent_start_event(
        self,
        tmp_path: Path,
    ) -> None:
        s_dir = tmp_path / "stories" / "TEST-106"
        s_dir.mkdir(parents=True)
        for phase in ("setup", "exploration", "implementation"):
            _save_snapshot(s_dir, phase, story_id="TEST-106")
        _save_flow(s_dir, story_id="TEST-106")
        _append_agent_start_event(
            s_dir,
            story_id="TEST-106",
            occurred_at=datetime(2026, 1, 1, 9, 30, 0, tzinfo=UTC),
        )
        _append_agent_start_event(
            s_dir,
            story_id="TEST-106",
            occurred_at=datetime(2026, 1, 1, 9, 45, 0, tzinfo=UTC),
        )

        handler = ClosurePhaseHandler(ClosureConfig(story_dir=s_dir, close_issue=False))
        ctx = _make_ctx(story_id="TEST-106", project_root=tmp_path)
        state = _make_state(story_id="TEST-106")

        result = handler.on_enter(ctx, state)

        assert result.status == PhaseStatus.COMPLETED
        metrics = load_story_metrics(s_dir)
        assert len(metrics) == 1
        assert metrics[0].processing_time_min >= 30.0

    def test_closure_fails_without_agent_start_event(self, tmp_path: Path) -> None:
        s_dir = tmp_path / "stories" / "TEST-107"
        s_dir.mkdir(parents=True)
        for phase in ("setup", "exploration", "implementation"):
            _save_snapshot(s_dir, phase, story_id="TEST-107")
        _save_flow(s_dir, story_id="TEST-107")

        handler = ClosurePhaseHandler(ClosureConfig(story_dir=s_dir, close_issue=False))
        ctx = _make_ctx(story_id="TEST-107", project_root=tmp_path)
        state = _make_state(story_id="TEST-107")

        result = handler.on_enter(ctx, state)

        assert result.status == PhaseStatus.FAILED
        assert result.errors == (
            "Failed to materialize story metrics: Cannot build story metrics "
            "without a canonical agent_start",
        )


# ---------------------------------------------------------------------------
# ExecutionReport tests
# ---------------------------------------------------------------------------


class TestExecutionReport:
    """Tests for ``ExecutionReport`` and ``write_execution_report``."""

    def test_execution_report_contains_correct_fields(
        self,
        tmp_path: Path,
    ) -> None:
        """ExecutionReport has story_id, type, phases, timestamps."""
        report = ExecutionReport(
            story_id="TEST-001",
            story_type="implementation",
            status="completed",
            phases_executed=(
                "setup",
                "exploration",
                "implementation",
                "closure",
            ),
            started_at="2026-01-01T00:00:00+00:00",
            completed_at="2026-01-01T01:00:00+00:00",
            issue_closed=True,
            warnings=(),
        )

        data = report.to_dict()

        assert data["story_id"] == "TEST-001"
        assert data["story_type"] == "implementation"
        assert data["status"] == "completed"
        assert isinstance(data["phases_executed"], list)
        assert len(data["phases_executed"]) == 4
        assert data["started_at"] == "2026-01-01T00:00:00+00:00"
        assert data["completed_at"] == "2026-01-01T01:00:00+00:00"
        assert data["issue_closed"] is True
        assert data["warnings"] == []

    def test_write_execution_report_creates_file(
        self,
        tmp_path: Path,
    ) -> None:
        """``write_execution_report`` writes valid JSON to closure.json."""
        report = ExecutionReport(
            story_id="TEST-002",
            story_type="bugfix",
            status="completed",
            phases_executed=("setup", "implementation", "closure"),
        )

        path = write_execution_report(tmp_path, report)

        assert path == tmp_path / "closure.json"
        assert path.exists()

        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        assert data["story_id"] == "TEST-002"
        assert data["story_type"] == "bugfix"

    def test_execution_report_with_warnings(self, tmp_path: Path) -> None:
        """Report with warnings has status ``completed_with_warnings``."""
        report = ExecutionReport(
            story_id="TEST-003",
            story_type="implementation",
            status="completed_with_warnings",
            phases_executed=("setup", "implementation", "closure"),
            warnings=("Could not close issue",),
        )

        data = report.to_dict()
        assert data["status"] == "completed_with_warnings"
        assert len(data["warnings"]) == 1  # type: ignore[arg-type]

    def test_to_dict_roundtrips_through_json(self, tmp_path: Path) -> None:
        """``to_dict`` output survives JSON serialization roundtrip."""
        report = ExecutionReport(
            story_id="RT-001",
            story_type="research",
            status="completed",
            phases_executed=("setup", "implementation", "closure"),
            started_at="2026-04-07T10:00:00+00:00",
            completed_at="2026-04-07T10:05:00+00:00",
            issue_closed=False,
            warnings=("warn1", "warn2"),
        )

        serialized = json.dumps(report.to_dict())
        deserialized = json.loads(serialized)

        assert deserialized["story_id"] == "RT-001"
        assert deserialized["warnings"] == ["warn1", "warn2"]
