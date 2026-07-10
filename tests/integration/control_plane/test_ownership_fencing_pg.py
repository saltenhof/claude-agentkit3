"""Integration: AG3-142 ownership-fencing end-to-end against REAL Postgres.

Drives the PUBLIC :class:`ControlPlaneRuntimeService` API (``start_phase`` /
``complete_phase``) against the real Postgres backend -- true phase
boundaries, pipeline state produced by the REAL dispatch path, never
fabricated:

* AC1 -- a real setup start atomically creates the active
  ``run_ownership_records`` row (``ownership_epoch=1``) together with the
  claim-CAS finalize, through the full public ``start_phase`` call.
* AC5 (executor fenced, no TOCTOU) -- the legacy dispatch-window race still
  proves the AG3-142 commit-time fence; AG3-148's productive transfer-confirm
  CAS is covered below by the AC15 real-transfer regression.
* AC4/AC6 -- ``complete_phase`` end-to-end: an ex-owner's call against a
  REAL prior admitted run is rejected with the structured
  ``ownership_transferred`` payload.

Resource note: single physical connection per worker (see the sibling
``tests/integration/state_backend/test_ownership_fence_postgres.py`` for the
full explanation).

``tests/integration/control_plane/`` is NOT in the conftest Postgres
auto-attach allow-list (mirrors the sibling AG3-141 object-claim-serialization
suite), so this module requests the isolation fixture explicitly.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.auth.middleware import AuthMiddleware
from agentkit.backend.control_plane.models import PhaseDispatchResult, PhaseMutationRequest
from agentkit.backend.control_plane.push_sync import (
    PushBarrierVerdict,
    PushBarrierVerdictStatus,
    PushFreshnessRecord,
    SyncPointBarrierType,
)
from agentkit.backend.control_plane.runtime import ControlPlaneRuntimeService
from agentkit.backend.control_plane_http.app import ControlPlaneApplication
from agentkit.backend.state_backend import postgres_store
from agentkit.backend.state_backend.operation_ledger import load_control_plane_operation_global
from agentkit.backend.state_backend.state_backend_connection_manager import (
    boot_backend_instance_identity_global,
)
from agentkit.backend.state_backend.story_closure_store import (
    upsert_push_barrier_verdict_global,
    upsert_push_freshness_record_global,
)
from agentkit.backend.state_backend.story_lifecycle_store import (
    load_active_run_ownership_record_global,
    load_session_run_binding_global,
    save_story_context_global,
)
from agentkit.backend.story_context_manager.models import StoryContext
from agentkit.backend.story_context_manager.types import StoryMode, StoryType

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.control_plane_http.responses import HttpResponse

pytestmark = pytest.mark.integration

_T0 = datetime(2026, 7, 4, 10, 0, tzinfo=UTC)
_PROJECT = "tenant-a"
_SHA = "a" * 40


@pytest.fixture(autouse=True)
def _isolated_postgres(postgres_isolated_schema: object) -> None:
    """Bind the per-test isolated Postgres control-plane schema (K5 Postgres-only)."""
    del postgres_isolated_schema


def _seed_story_context(tmp_path: Path, story_id: str) -> None:
    project_root = tmp_path / _PROJECT
    (project_root / "stories" / story_id).mkdir(parents=True, exist_ok=True)
    save_story_context_global(
        None,
        StoryContext(
            project_key=_PROJECT,
            story_id=story_id,
            story_type=StoryType.IMPLEMENTATION,
            execution_route=StoryMode.EXECUTION,
            project_root=project_root,
        ),
    )


def _request(*, story_id: str, op_id: str, session_id: str) -> PhaseMutationRequest:
    return PhaseMutationRequest(
        project_key=_PROJECT,
        story_id=story_id,
        session_id=session_id,
        op_id=op_id,
        principal_type="orchestrator",
        worktree_roots=[f"T:/worktrees/{story_id}"],
    )


def _seed_pushed_only_evidence(*, story_id: str, run_id: str) -> None:
    upsert_push_freshness_record_global(
        PushFreshnessRecord(
            project_key=_PROJECT,
            story_id=story_id,
            run_id=run_id,
            repo_id="api",
            last_reported_head_sha=_SHA,
            last_pushed_head_sha=_SHA,
            last_reported_at=_T0,
            last_sync_point_id=f"phase_completion:{run_id}",
            last_command_id=f"{run_id}::sync_push::phase_completion:{run_id}::api",
            backlog=False,
            backlog_detail=None,
        )
    )
    upsert_push_barrier_verdict_global(
        PushBarrierVerdict(
            project_key=_PROJECT,
            story_id=story_id,
            run_id=run_id,
            boundary_type=SyncPointBarrierType.PHASE_COMPLETION,
            boundary_id=run_id,
            repo_id="api",
            producer="control_plane.push_barrier",
            boundary_epoch=1,
            expected_head_sha=_SHA,
            server_head_sha=_SHA,
            ownership_epoch=1,
            status=PushBarrierVerdictStatus.PASSED,
            created_at=_T0,
            updated_at=_T0,
            resolved_at=_T0,
            status_detail="verified",
        )
    )


def _human_headers(auth: AuthMiddleware, *, project_key: str) -> dict[str, str]:
    session = auth.session_store.create()
    return {
        "Cookie": f"{auth.session_cookie_name()}={session.session_id}",
        auth.csrf_header_name(): session.csrf_token,
        "X-Project-Key": project_key,
    }


def _json(response: HttpResponse) -> dict[str, object]:
    parsed = json.loads(response.body)
    assert isinstance(parsed, dict)
    return parsed


class _AdmittedDispatcher:
    """A dispatcher that always reports the phase as completed."""

    def dispatch(
        self,
        *,
        ctx: StoryContext,
        phase: str,
        run_id: str,
        run_admitted: bool,
        detail: dict[str, object] | None = None,
    ) -> PhaseDispatchResult:
        del ctx, run_id, run_admitted, detail
        return PhaseDispatchResult(
            phase=phase,
            status="phase_completed",
            reaction="advance",
            dispatched=True,
            next_phase="implementation",
        )


class _RacingDispatcher:
    """A dispatcher whose OWN execution window injects a "concurrent transfer".

    Mirrors, at the PUBLIC API boundary, exactly the window a real (slow)
    engine dispatch occupies in production: this call's EARLY admission
    check has already passed (the caller was the recognised owner at that
    moment) by the time ``dispatch`` runs; a direct UPDATE here simulates a
    transfer landing DURING that window, before this call's own commit-time
    fence re-verifies.
    """

    def __init__(self, *, project_key: str, story_id: str) -> None:
        self._project_key = project_key
        self._story_id = story_id
        self.dispatched = False

    def dispatch(
        self,
        *,
        ctx: StoryContext,
        phase: str,
        run_id: str,
        run_admitted: bool,
        detail: dict[str, object] | None = None,
    ) -> PhaseDispatchResult:
        del ctx, run_id, run_admitted, detail
        self.dispatched = True
        with postgres_store._connect_global() as conn:  # noqa: SLF001 -- sanctioned test-only direct touch
            conn.execute(
                """
                UPDATE run_ownership_records
                SET owner_session_id = ?, ownership_epoch = ?
                WHERE project_key = ? AND story_id = ? AND status = 'active'
                """,
                ("sess-HIJACK", 2, self._project_key, self._story_id),
            )
        return PhaseDispatchResult(
            phase=phase,
            status="phase_completed",
            reaction="advance",
            dispatched=True,
            next_phase="implementation",
        )


def test_real_setup_start_atomically_creates_the_active_ownership_record(
    tmp_path: Path,
) -> None:
    """AC1 end-to-end: a genuine ``start_phase(phase="setup")`` call, through
    the full public API against real Postgres, atomically materializes the
    active ``run_ownership_records`` row alongside the committed op.
    """
    story_id = "AG3-620"
    run_id = "run-620"
    _seed_story_context(tmp_path, story_id)
    identity = boot_backend_instance_identity_global("inst-ac1-e2e", _T0)
    service = ControlPlaneRuntimeService(
        phase_dispatcher=_AdmittedDispatcher(),  # type: ignore[arg-type]
        now_fn=lambda: _T0,
        instance_identity=identity,
    )

    result = service.start_phase(
        run_id=run_id,
        phase="setup",
        request=_request(story_id=story_id, op_id="op-ac1-setup", session_id="sess-A"),
    )

    assert result.status == "committed"
    assert result.ownership_epoch == 1
    active = load_active_run_ownership_record_global(_PROJECT, story_id)
    assert active is not None
    assert active.run_id == run_id
    assert active.owner_session_id == "sess-A"
    assert active.ownership_epoch == 1


def test_executor_dispatch_then_ownership_changes_before_commit_rejects_with_no_state(
    tmp_path: Path,
) -> None:
    """AC5 (the crux): a real dispatch->finalize race is fenced with NO state
    written, driven entirely through the real ``start_phase`` public API and
    real Postgres pipeline state (never manually assembled).
    """
    story_id = "AG3-621"
    run_id = "run-621"
    _seed_story_context(tmp_path, story_id)
    identity = boot_backend_instance_identity_global("inst-ac5-e2e", _T0)

    # Step 1: a REAL setup start admits run_id under session A (mints epoch 1).
    setup_service = ControlPlaneRuntimeService(
        phase_dispatcher=_AdmittedDispatcher(),  # type: ignore[arg-type]
        now_fn=lambda: _T0,
        instance_identity=identity,
    )
    setup_result = setup_service.start_phase(
        run_id=run_id,
        phase="setup",
        request=_request(story_id=story_id, op_id="op-ac5-setup", session_id="sess-A"),
    )
    assert setup_result.status == "committed"
    binding_before = load_session_run_binding_global("sess-A")
    assert binding_before is not None
    assert binding_before.run_id == run_id

    # Step 2: session A starts the NEXT phase. Its early admission check sees
    # itself as the (still valid) owner; its OWN dispatch call is where the
    # "concurrent transfer" is injected (the real engine's execution window).
    racing_dispatcher = _RacingDispatcher(project_key=_PROJECT, story_id=story_id)
    exploration_service = ControlPlaneRuntimeService(
        phase_dispatcher=racing_dispatcher,  # type: ignore[arg-type]
        now_fn=lambda: _T0,
        instance_identity=identity,
    )

    result = exploration_service.start_phase(
        run_id=run_id,
        phase="exploration",
        request=_request(story_id=story_id, op_id="op-ac5-exploration", session_id="sess-A"),
    )

    # The dispatcher DID run (the race window was genuinely opened) but the
    # commit-time fence caught the staleness and rejected fail-closed.
    assert racing_dispatcher.dispatched is True
    assert result.status == "rejected"
    assert result.error_code == "ownership_transferred"
    assert result.ownership_conflict is not None
    assert result.ownership_conflict.new_owner_session_id == "sess-HIJACK"
    assert result.ownership_conflict.new_ownership_epoch == 2
    # NO state was written for the racing attempt: no op, and A's ORIGINAL
    # setup binding is untouched (never re-materialized/clobbered).
    assert load_control_plane_operation_global("op-ac5-exploration") is None
    binding_after = load_session_run_binding_global("sess-A")
    assert binding_after is not None
    assert binding_after.binding_version == binding_before.binding_version
    # The hijacked record stands (the fence does not "fix" or roll back the
    # ownership row itself -- it only refuses to commit A's stale mutation).
    active = load_active_run_ownership_record_global(_PROJECT, story_id)
    assert active is not None
    assert active.owner_session_id == "sess-HIJACK"
    assert active.ownership_epoch == 2


def test_complete_phase_ex_owner_rejected_end_to_end(tmp_path: Path) -> None:
    """AC4/AC6 end-to-end: a real prior admitted run, then an ex-owner's
    ``complete_phase`` call is rejected with the structured
    ``ownership_transferred`` payload -- through the real public API and
    real Postgres.
    """
    story_id = "AG3-622"
    run_id = "run-622"
    _seed_story_context(tmp_path, story_id)
    identity = boot_backend_instance_identity_global("inst-ac4-e2e", _T0)
    service = ControlPlaneRuntimeService(
        phase_dispatcher=_AdmittedDispatcher(),  # type: ignore[arg-type]
        now_fn=lambda: _T0,
        instance_identity=identity,
    )
    setup_result = service.start_phase(
        run_id=run_id,
        phase="setup",
        request=_request(story_id=story_id, op_id="op-ac4-setup", session_id="sess-REAL-OWNER"),
    )
    assert setup_result.status == "committed"

    # An ex-owner (a DIFFERENT session) attempts to complete a later phase.
    result = service.complete_phase(
        run_id=run_id,
        phase="implementation",
        request=_request(story_id=story_id, op_id="op-ac4-complete", session_id="sess-IMPOSTOR"),
    )

    assert result.status == "rejected"
    assert result.error_code == "ownership_transferred"
    assert result.ownership_conflict is not None
    assert result.ownership_conflict.new_owner_session_id == "sess-REAL-OWNER"
    assert load_control_plane_operation_global("op-ac4-complete") is None


def test_t3_real_takeover_confirm_fences_ex_owner_mutations_but_allows_operation_reads(
    tmp_path: Path,
) -> None:
    """AC15 end-to-end: real AG3-148 confirm CAS transfers ownership.

    The ex-owner is then rejected at a regime mutation boundary with the
    AG3-142 ``ownership_transferred`` payload, while operation reconciliation
    reads remain allowed.
    """
    story_id = "AG3-623"
    run_id = "run-623"
    _seed_story_context(tmp_path, story_id)
    identity = boot_backend_instance_identity_global("inst-ac7-e2e", _T0)
    service = ControlPlaneRuntimeService(
        phase_dispatcher=_AdmittedDispatcher(),  # type: ignore[arg-type]
        now_fn=lambda: _T0,
        instance_identity=identity,
    )
    created = service.start_phase(
        run_id=run_id,
        phase="setup",
        request=_request(story_id=story_id, op_id="op-ac7-setup", session_id="sess-EX-OWNER"),
    )
    assert created.status == "committed"
    _seed_pushed_only_evidence(story_id=story_id, run_id=run_id)
    auth = AuthMiddleware()
    app = ControlPlaneApplication(
        runtime_service=service,
        auth_middleware=auth,
    )
    headers = _human_headers(auth, project_key=_PROJECT)
    offered = app.handle_request(
        method="POST",
        path=f"/v1/project-edge/story-runs/{run_id}/ownership/takeover-request",
        body=json.dumps(
            {
                "project_key": _PROJECT,
                "story_id": story_id,
                "session_id": "sess-NEW-OWNER",
                "principal_type": "human_cli",
                "op_id": "op-ac15-request",
                "reason": "owner unavailable",
                "worktree_roots": [f"T:/worktrees/{story_id}/new"],
            }
        ).encode(),
        request_headers=headers,
    )
    assert offered.status_code == HTTPStatus.CREATED
    offered_body = _json(offered)
    challenge = offered_body["takeover_challenge"]
    assert isinstance(challenge, dict)
    confirmed = app.handle_request(
        method="POST",
        path=f"/v1/project-edge/story-runs/{run_id}/ownership/takeover-confirm",
        body=json.dumps(
            {
                "project_key": _PROJECT,
                "story_id": story_id,
                "op_id": "op-ac15-confirm",
                "challenge_id": challenge["challenge_id"],
                "reason": "human confirmed",
                "source_component": "integration_test",
            }
        ).encode(),
        request_headers=headers,
    )
    assert confirmed.status_code == HTTPStatus.CREATED
    confirmed_body = _json(confirmed)
    assert confirmed_body["status"] == "committed"

    rejected = service.start_phase(
        run_id=run_id,
        phase="exploration",
        request=_request(
            story_id=story_id,
            op_id="op-ac15-ex-owner-start",
            session_id="sess-EX-OWNER",
        ),
    )
    assert rejected.status == "rejected"
    assert rejected.error_code == "takeover_reconcile_required"
    assert rejected.ownership_conflict is None
    assert load_control_plane_operation_global("op-ac15-ex-owner-start") is None

    replayed = service.get_operation("op-ac7-setup")
    assert replayed is not None
    assert replayed.status == "replayed"
    assert replayed.op_id == "op-ac7-setup"
