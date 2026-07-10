"""Unit tests for Story-Reset composition adapters."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import pytest

from agentkit.backend.bootstrap.story_reset_adapters import (
    AnalyticsPurgeAdapter,
    CompetingOperationAdapter,
    EscalationEvidenceAdapter,
    FenceAdapter,
    LockPurgeAdapter,
    ReadModelPurgeAdapter,
    RunScopeAdapter,
    RuntimePurgeAdapter,
    StoryResetLockError,
    WorkspacePurgeAdapter,
)
from agentkit.backend.control_plane.records import ControlPlaneOperationRecord


@dataclass(frozen=True)
class _Flow:
    run_id: str


@dataclass(frozen=True)
class _Event:
    event_type: str
    payload: dict[str, object]


class _StoryRepo:
    def __init__(self) -> None:
        self.flow: _Flow | None = _Flow("run-1")
        self.events: list[_Event] = []

    def load_flow_execution(self, _project_key: str, _story_id: str) -> _Flow | None:
        return self.flow

    def load_recent_execution_events(self, _project_key: str, _story_id: str, _run_id: str, _limit: int) -> list[_Event]:
        return self.events


class _ControlPlaneRepo:
    def __init__(self) -> None:
        self.committed = False
        self.claimed: list[object] = []
        self.deleted: list[str] = []
        self.finalized: list[object] = []
        now = datetime(2026, 7, 10, tzinfo=UTC)
        self.records: dict[str, Any] = {
            "reset-1": ControlPlaneOperationRecord(
                op_id="reset-1",
                project_key="p",
                story_id="s",
                run_id="run-1",
                session_id=None,
                operation_kind="story_reset",
                phase=None,
                status="claimed",
                response_payload={"reset_status": "started"},
                created_at=now,
                updated_at=now,
                claimed_by="story-reset-reset-1",
                claimed_at=now,
                operation_epoch=1,
            )
        }

    def has_committed_ownership_invalidating_operation_for_run(
        self,
        _project_key: str,
        _story_id: str,
        _run_id: str,
    ) -> bool:
        return self.committed

    def claim_operation(self, record: object) -> bool:
        self.claimed.append(record)
        return True

    def load_operation(self, op_id: str) -> object | None:
        return self.records.get(op_id)

    def delete_operation(self, op_id: str) -> None:
        self.deleted.append(op_id)

    def finalize_operation(self, record: Any, **_kwargs: object) -> bool:
        self.finalized.append(record)
        self.records[record.op_id] = record
        return True


@dataclass(frozen=True)
class _PurgeResult:
    purged_rows: dict[str, int]


@dataclass(frozen=True)
class _ResidueResult:
    residue_rows: dict[str, int]


class _RuntimePurge:
    def purge_run(self, project_key: str, story_id: str, run_id: str) -> _PurgeResult:
        return _PurgeResult({"events": len(project_key + story_id + run_id)})


class _ResidueProbe:
    def check_run(self, _project_key: str, _story_id: str, _run_id: str) -> _ResidueResult:
        return _ResidueResult({"events": 0})


class _LockError(RuntimeError):
    pass


class _Governance:
    def __init__(self, errors: list[Exception] | None = None) -> None:
        self.errors = errors or []
        self.deactivated: list[str] = []

    def deactivate_locks(self, story_id: str) -> object:
        self.deactivated.append(story_id)
        return type("Result", (), {"errors": self.errors})()


class _LockRepo:
    def __init__(self, active: int) -> None:
        self.active = active

    def count_active_locks_for_story(self, _story_id: str) -> int:
        return self.active


class _ProjectionKind(StrEnum):
    GUARD = "guard_events"


@dataclass(frozen=True)
class _ProjectionPurgeResult:
    purged_rows: dict[_ProjectionKind, int]
    purged_guard_counters: int


class _ProjectionAccessor:
    def purge_run(self, _project_key: str, _story_id: str, _run_id: str) -> _ProjectionPurgeResult:
        return _ProjectionPurgeResult({_ProjectionKind.GUARD: 3}, purged_guard_counters=2)


class _AnalyticsWorker:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, object]] = []

    def purge_story_analytics(self, project_key: str, story_id: str, run_id: str, periods: object) -> None:
        self.calls.append((project_key, story_id, run_id, periods))


def test_run_scope_and_escalation_adapters_read_story_evidence() -> None:
    story_repo = _StoryRepo()

    assert RunScopeAdapter(story_repo).resolve_run_id("p", "s") == "run-1"  # type: ignore[arg-type]
    assert EscalationEvidenceAdapter(story_repo).has_escalation_finding("p", "s", None) is False  # type: ignore[arg-type]

    story_repo.events = [_Event("worker_event", {"escalation_class": "scope_explosion"})]
    assert EscalationEvidenceAdapter(story_repo).has_escalation_finding("p", "s", "run-1") is True  # type: ignore[arg-type]

    story_repo.events = [_Event("scope_explosion_check", {})]
    assert EscalationEvidenceAdapter(story_repo).has_escalation_finding("p", "s", "run-1") is True  # type: ignore[arg-type]


def test_control_plane_adapters_delegate_to_committed_owner() -> None:
    cp_repo = _ControlPlaneRepo()
    cp_repo.committed = True
    record = object()

    assert CompetingOperationAdapter(cp_repo).has_competing_admin_operation("p", "s", None, "reset") is False  # type: ignore[arg-type]
    assert CompetingOperationAdapter(cp_repo).has_competing_admin_operation("p", "s", "run-1", "reset") is True  # type: ignore[arg-type]
    assert FenceAdapter(cp_repo).claim(record) is True  # type: ignore[arg-type]
    assert FenceAdapter(cp_repo).load("reset-1") is not None  # type: ignore[arg-type]
    FenceAdapter(cp_repo).release("reset-1")  # type: ignore[arg-type]
    assert cp_repo.claimed == [record]
    assert cp_repo.deleted == []
    assert len(cp_repo.finalized) == 1
    assert cp_repo.records["reset-1"].status == "committed"


def test_runtime_and_projection_purge_adapters_return_plain_row_maps() -> None:
    runtime = RuntimePurgeAdapter(_RuntimePurge(), _ResidueProbe())  # type: ignore[arg-type]
    read_model = ReadModelPurgeAdapter(_ProjectionAccessor())  # type: ignore[arg-type]

    assert runtime.purge_run("p", "s", "r") == {"events": 3}
    assert runtime.residue("p", "s", "r") == {"events": 0}
    assert read_model.purge_run("p", "s", "r") == {
        "guard_events": 3,
        "guard_invocation_counters": 2,
    }


def test_lock_purge_adapter_converges_absent_rows_and_raises_real_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("agentkit.backend.governance.errors.LockRecordNotFoundError", _LockError)

    adapter = LockPurgeAdapter(_Governance(), _LockRepo(active=1))  # type: ignore[arg-type]
    adapter.deactivate_locks("AG3-147")
    assert adapter.has_active_locks("AG3-147") is True

    class _AbsentGovernance(_Governance):
        def deactivate_locks(self, story_id: str) -> object:
            raise _LockError(story_id)

    LockPurgeAdapter(_AbsentGovernance(), _LockRepo(active=0)).deactivate_locks("AG3-147")  # type: ignore[arg-type]
    lock_adapter = LockPurgeAdapter(_Governance([RuntimeError("database down")]), _LockRepo(active=0))  # type: ignore[arg-type]
    assert lock_adapter.has_active_locks("AG3-147") is False
    with pytest.raises(StoryResetLockError, match="database down"):
        LockPurgeAdapter(_Governance([RuntimeError("database down")]), _LockRepo(active=0)).deactivate_locks("AG3-147")  # type: ignore[arg-type]


def test_analytics_and_workspace_purge_adapters_delegate(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    worker = _AnalyticsWorker()
    AnalyticsPurgeAdapter(worker).purge_story_analytics("p", "s", "r")  # type: ignore[arg-type]
    assert worker.calls[0][:3] == ("p", "s", "r")

    monkeypatch.setattr(
        "agentkit.backend.installer.paths.story_dir",
        lambda project_root, story_id: project_root / "stories" / story_id,
    )
    story_dir = tmp_path / "stories" / "AG3-147"
    for name in ("scratch", "tmp", "adversarial_sandbox", "exports", "keep"):
        (story_dir / name).mkdir(parents=True, exist_ok=True)

    WorkspacePurgeAdapter(tmp_path).purge_workspace("p", "AG3-147")  # type: ignore[arg-type]

    assert not (story_dir / "scratch").exists()
    assert not (story_dir / "tmp").exists()
    assert not (story_dir / "adversarial_sandbox").exists()
    assert not (story_dir / "exports").exists()
    assert (story_dir / "keep").is_dir()
