"""Integration: an expired permission request escalates the run during REAL
CCAG / hook evaluation (AG3-086 AC7, FIX 2 — productive wiring of
``PermissionExpiryEscalator``).

FK-42 §42.4.2 step 5 / FK-55 §55.10.9a (lazy materialisation): the
``PermissionExpiryEscalator`` is wired into the productive CCAG hook dispatch
(``run_hook("ccag_gatekeeper", ...)``, the path that reads pending permission
requests during a real run). When a pending request has TTL-elapsed, the run's
AUTHORITATIVE ``PhaseState.status`` is deterministically set to ``ESCALATED``
(reason ``permission_request_expired``) — NOT only on the escalator in isolation.

NO CHEATING: the capability layer runs LIVE (a worker-attested Read in story
scope is a KNOWN non-mutating READ that passes the hard matrix and reaches the
CCAG gatekeeper); the request store and the durable PhaseState are the REAL
state-backend stores the production runner uses.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from tests.phase_state_factory import make_phase_state

from agentkit.backend.control_plane.models import (
    EdgeBundle,
    EdgePointer,
    SessionRunBindingView,
    StoryExecutionLockView,
)
from agentkit.backend.governance.ccag.requests import PermissionRequestStore
from agentkit.backend.governance.guard_evaluation import HookEvent
from agentkit.backend.governance.runner import run_hook
from agentkit.backend.pipeline_engine.phase_executor.models import (
    EscalationReason,
    PhaseStatus,
)
from agentkit.backend.state_backend.store import reset_backend_cache_for_tests
from agentkit.backend.state_backend.store.phase_envelope_repository import (
    StateBackendPhaseEnvelopeRepository,
)
from agentkit.harness_client.projectedge.client import LocalEdgePublisher

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

_PROJECT = "tenant-ttl"
_STORY = "AG3-700"
_RUN = "run-700"
_SESSION = "sess-700"
_WORKER_ATTEST = ["--ak3-principal-attest", "worker"]


@pytest.fixture(autouse=True)
def _sqlite_backend(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    monkeypatch.delenv("AGENTKIT_STATE_DATABASE_URL", raising=False)
    reset_backend_cache_for_tests()
    yield
    reset_backend_cache_for_tests()


def _publish_story_binding(project_root: Path, worktree: str) -> None:
    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    bundle = EdgeBundle(
        current=EdgePointer(
            project_key=_PROJECT,
            export_version="edge-700",
            operating_mode="story_execution",
            bundle_dir="_temp/governance/bundles/edge-700",
            sync_after=now + timedelta(minutes=5),
            freshness_class="guarded_read",
            generated_at=now,
        ),
        session=SessionRunBindingView(
            session_id=_SESSION,
            project_key=_PROJECT,
            story_id=_STORY,
            run_id=_RUN,
            principal_type="worker",
            worktree_roots=[worktree],
            binding_version="bind-700",
            operating_mode="story_execution",
        ),
        lock=StoryExecutionLockView(
            project_key=_PROJECT,
            story_id=_STORY,
            run_id=_RUN,
            lock_type="story_execution",
            status="ACTIVE",
            worktree_roots=[worktree],
            binding_version="bind-700",
            activated_at=now,
            updated_at=now,
        ),
        qa_lock=None,
    )
    LocalEdgePublisher(project_root=project_root).publish(bundle)


def _ccag_db_path(project_root: Path) -> Path:
    return project_root / ".agentkit" / "ccag" / "ccag_requests.db"


def _save_phase_state(project_root: Path, status: PhaseStatus) -> None:
    story_dir = project_root / "stories" / _STORY
    StateBackendPhaseEnvelopeRepository(story_dir).save_state(
        make_phase_state(story_id=_STORY, status=status)
    )


def _read_event(worktree: str) -> HookEvent:
    """A worker-attested Read inside the story worktree (a known non-mutating READ
    that passes the live capability layer and reaches the CCAG gatekeeper)."""
    return HookEvent.model_validate(
        {
            "operation": "file_read",
            "freshness_class": "guarded_read",
            "cwd": worktree,
            "session_id": _SESSION,
            "principal_kind": "subagent",
            "cli_args": _WORKER_ATTEST,
            "operation_args": {
                "file_path": worktree + "/README.md",
                "operating_mode": "story_execution",
            },
        }
    )


def _create_expired_request(project_root: Path) -> None:
    db = _ccag_db_path(project_root)
    db.parent.mkdir(parents=True, exist_ok=True)
    PermissionRequestStore(db).create(
        request_id="req-expired-700",
        tool_name="WebFetch",
        story_id=_STORY,
        run_id=_RUN,
        ttl_seconds=-10,  # expires_at 10s in the past -> effective_status "expired"
    )


def test_expired_request_escalates_run_through_ccag_dispatch(tmp_path: Path) -> None:
    # AC7 (productive path): an expired pending request + an active run whose
    # durable PhaseState is IN_PROGRESS -> dispatching the CCAG gatekeeper hook
    # deterministically escalates the AUTHORITATIVE PhaseState to ESCALATED.
    worktree = str(tmp_path / "worktree")
    (tmp_path / "worktree").mkdir()
    _publish_story_binding(tmp_path, worktree)
    _save_phase_state(tmp_path, PhaseStatus.IN_PROGRESS)
    _create_expired_request(tmp_path)

    run_hook("ccag_gatekeeper", _read_event(worktree), phase="pre", project_root=tmp_path)

    story_dir = tmp_path / "stories" / _STORY
    state = StateBackendPhaseEnvelopeRepository(story_dir).load_state(
        _STORY, make_phase_state().phase  # phase is protocol-only; physical key is story_dir
    )
    assert state is not None
    assert state.status is PhaseStatus.ESCALATED
    assert state.escalation_reason is EscalationReason.PERMISSION_REQUEST_EXPIRED


def test_fresh_request_does_not_escalate_through_ccag_dispatch(tmp_path: Path) -> None:
    # A fresh (non-expired) request leaves the run IN_PROGRESS — no spurious escalation.
    worktree = str(tmp_path / "worktree")
    (tmp_path / "worktree").mkdir()
    _publish_story_binding(tmp_path, worktree)
    _save_phase_state(tmp_path, PhaseStatus.IN_PROGRESS)
    db = _ccag_db_path(tmp_path)
    db.parent.mkdir(parents=True, exist_ok=True)
    PermissionRequestStore(db).create(
        request_id="req-fresh-700",
        tool_name="WebFetch",
        story_id=_STORY,
        run_id=_RUN,
        ttl_seconds=3600,  # not expired
    )

    run_hook("ccag_gatekeeper", _read_event(worktree), phase="pre", project_root=tmp_path)

    story_dir = tmp_path / "stories" / _STORY
    state = StateBackendPhaseEnvelopeRepository(story_dir).load_state(
        _STORY, make_phase_state().phase
    )
    assert state is not None
    assert state.status is PhaseStatus.IN_PROGRESS


def test_already_escalated_run_is_idempotent_through_ccag_dispatch(
    tmp_path: Path,
) -> None:
    # An already-ESCALATED run with a different reason is left unchanged
    # (idempotent — the TTL escalation never overwrites a prior escalation reason).
    worktree = str(tmp_path / "worktree")
    (tmp_path / "worktree").mkdir()
    _publish_story_binding(tmp_path, worktree)
    story_dir = tmp_path / "stories" / _STORY
    StateBackendPhaseEnvelopeRepository(story_dir).save_state(
        make_phase_state(
            story_id=_STORY,
            status=PhaseStatus.ESCALATED,
            escalation_reason=EscalationReason.GOVERNANCE_VIOLATION,
        )
    )
    _create_expired_request(tmp_path)

    run_hook("ccag_gatekeeper", _read_event(worktree), phase="pre", project_root=tmp_path)

    state = StateBackendPhaseEnvelopeRepository(story_dir).load_state(
        _STORY, make_phase_state().phase
    )
    assert state is not None
    assert state.status is PhaseStatus.ESCALATED
    assert state.escalation_reason is EscalationReason.GOVERNANCE_VIOLATION
