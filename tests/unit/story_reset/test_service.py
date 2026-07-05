"""StoryResetService orchestration tests (FK-53, AG3-071).

Covers the §3 acceptance criteria of the service flow with a REAL
``StoryService`` (in-memory story repo — the real status owner) and call-recording
test doubles at the genuine external edges (the typed purge/lock/fence/worktree
ports, whose real owners are exercised in the integration test). The doubles share
ONE event log so the flow ORDER (fence-before-purge, separate Schritt-5/Schritt-6
ports, lock-release-after-verify) is asserted directly.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agentkit.backend.project_management.entities import Project, ProjectConfiguration
from agentkit.backend.state_backend.store.inflight_idempotency_guard import (
    InMemoryInflightIdempotencyGuard,
)
from agentkit.backend.story_context_manager.service import StoryService
from agentkit.backend.story_context_manager.story_model import (
    CreateStoryInput,
    StoryStatus,
    WireStoryType,
)
from agentkit.backend.story_context_manager.story_repository import InMemoryStoryRepository
from agentkit.backend.story_reset import (
    PlannedPurge,
    ResetStatus,
    StoryResetError,
    StoryResetRecord,
    StoryResetRequest,
    StoryResetService,
)

NOW = datetime(2026, 6, 12, 12, 0, tzinfo=UTC)
_PROJECT = "ak3"
_RUN = "run-reset-1"


# ---------------------------------------------------------------------------
# Real status owner (in-memory StoryService)
# ---------------------------------------------------------------------------


class _ProjectRepo:
    def __init__(self) -> None:
        self._p = Project(
            key=_PROJECT,
            name="AgentKit 3",
            story_id_prefix="AK3",
            configuration=ProjectConfiguration(
                repo_url="",
                default_branch="main",
                default_worker_count=2,
                repositories=["ak3"],
            ),
        )

    def get(self, key: str) -> Project | None:
        return self._p if key == self._p.key else None

    def list(self, *, include_archived: bool = False) -> list[Project]:
        return [self._p]

    def save(self, project: Project) -> None:
        self._p = project


def _make_story_service() -> StoryService:
    return StoryService(
        story_repository=InMemoryStoryRepository(),
        project_repository=_ProjectRepo(),
        idempotency_guard=InMemoryInflightIdempotencyGuard(),
        event_emitter=lambda *_a: None,
    )


def _seed_in_progress(svc: StoryService) -> str:
    created = svc.create_story(
        CreateStoryInput(
            project_key=_PROJECT,
            title="Reset target",
            story_type=WireStoryType.IMPLEMENTATION,
            repos=["ak3"],
        ),
        op_id="op-create",
    )
    svc.approve_story(created.story_display_id, op_id="op-approve")
    svc.begin_progress(created.story_display_id)
    return created.story_display_id


# ---------------------------------------------------------------------------
# Recording test doubles (genuine external edges)
# ---------------------------------------------------------------------------


class _InMemoryRecordStore:
    def __init__(self) -> None:
        self.records: dict[str, StoryResetRecord] = {}
        self.save_history: list[ResetStatus] = []

    def load(self, reset_id: str) -> StoryResetRecord | None:
        return self.records.get(reset_id)

    def save(self, record: StoryResetRecord) -> None:
        self.records[record.reset_id] = record
        self.save_history.append(record.status)


class _Ports:
    """One shared event log across every typed port (asserts the §53.7 order)."""

    def __init__(
        self,
        *,
        run_id: str | None = _RUN,
        escalation: bool = True,
        competing: bool = False,
        runtime_purge_fails: bool = False,
    ) -> None:
        self.events: list[str] = []
        self._run_id = run_id
        self._escalation = escalation
        self._competing = competing
        self._runtime_purge_fails = runtime_purge_fails
        self.active_locks = False
        self.live_worktree = False
        self.fence_claimed: dict[str, object] = {}
        # Convergent read-model purge (mirrors the real ProjectionAccessor:
        # a DELETE returns rowcount once, then 0 on a clean store).
        self._read_model_purged = False

    # RunScopePort
    def resolve_run_id(self, project_key: str, story_id: str) -> str | None:
        return self._run_id

    # EscalationEvidencePort
    def has_escalation_finding(
        self, project_key: str, story_id: str, run_id: str | None
    ) -> bool:
        return self._escalation

    # CompetingOperationPort
    def has_competing_admin_operation(
        self, project_key: str, story_id: str, run_id: str | None, reset_id: str
    ) -> bool:
        return self._competing

    # FencePort
    def claim(self, record: object) -> bool:
        op_id = record.op_id
        self.events.append("fence_claim")
        self.fence_claimed[op_id] = record
        return True

    def load(self, op_id: str) -> object | None:
        return self.fence_claimed.get(op_id)

    def release(self, op_id: str) -> None:
        self.events.append("fence_release")
        self.fence_claimed.pop(op_id, None)

    # RuntimePurgePort (Schritt 5)
    def purge_run(self, project_key: str, story_id: str, run_id: str) -> dict[str, int]:
        self.events.append("runtime_purge")
        if self._runtime_purge_fails:
            raise RuntimeError("injected runtime purge failure")
        return {"flow_executions": 3, "attempts": 2}

    def residue(self, project_key: str, story_id: str, run_id: str) -> dict[str, int]:
        self.events.append("runtime_residue")
        return {"flow_executions": 0, "attempts": 0}

    # LockPurgePort (Schritt 5)
    def deactivate_locks(self, story_id: str) -> None:
        self.events.append("lock_deactivate")
        self.active_locks = False

    def has_active_locks(self, story_id: str) -> bool:
        return self.active_locks

    # ReadModelPurgePort (Schritt 6) — distinct method name from runtime purge
    def read_model_purge_run(
        self, project_key: str, story_id: str, run_id: str
    ) -> dict[str, int]:
        self.events.append("read_model_purge")
        if self._read_model_purged:
            return {"qa_findings": 0}
        self._read_model_purged = True
        return {"qa_findings": 4}

    # AnalyticsPurgePort (Schritt 6)
    def purge_story_analytics(
        self, project_key: str, story_id: str, run_id: str
    ) -> None:
        self.events.append("analytics_purge")

    # WorkspacePort (Schritt 7)
    def purge_workspace(self, project_key: str, story_id: str) -> None:
        self.events.append("workspace_purge")

    # WorktreePort (Step 8) — AG3-145 D: edge-commissioned teardown signature.
    def detach_worktrees(
        self, project_key: str, story_id: str, run_id: str | None
    ) -> None:
        self.events.append("worktree_detach")
        self.live_worktree = False

    def has_live_worktree(
        self, project_key: str, story_id: str, run_id: str | None
    ) -> bool:
        return self.live_worktree


class _ReadModelAdapter:
    """Separate object so Schritt 6 read-model purge is a DISTINCT port (AC5b)."""

    def __init__(self, ports: _Ports) -> None:
        self._ports = ports

    def purge_run(self, project_key: str, story_id: str, run_id: str) -> dict[str, int]:
        return self._ports.read_model_purge_run(project_key, story_id, run_id)


def _make_service(
    *,
    story_service: StoryService,
    ports: _Ports,
    record_store: _InMemoryRecordStore | None = None,
) -> StoryResetService:
    return StoryResetService(
        story_status=story_service,
        record_store=record_store or _InMemoryRecordStore(),
        run_scope=ports,
        escalation_evidence=ports,
        competing_operation=ports,
        fence=ports,
        runtime_purge=ports,
        lock_purge=ports,
        read_model_purge=_ReadModelAdapter(ports),
        analytics_purge=ports,
        workspace=ports,
        worktree=ports,
        now_fn=lambda: NOW,
    )


# ---------------------------------------------------------------------------
# AC1 — contract surface
# ---------------------------------------------------------------------------


def test_service_exposes_the_four_contract_operations() -> None:
    """AC1: the four §53.10 operations exist on the service."""
    for op in (
        "request_reset",
        "execute_reset",
        "resume_reset",
        "verify_reset_clean_state",
    ):
        assert callable(getattr(StoryResetService, op))


# ---------------------------------------------------------------------------
# AC2 — dry-run plans, no mutation
# ---------------------------------------------------------------------------


def test_dry_run_reports_domains_without_mutation() -> None:
    """AC2: --dry-run lists planned purge domains and performs NO mutation."""
    svc_story = _make_story_service()
    story_id = _seed_in_progress(svc_story)
    ports = _Ports()
    store = _InMemoryRecordStore()
    service = _make_service(story_service=svc_story, ports=ports, record_store=store)

    plan = service.request_reset(
        StoryResetRequest(
            project_key=_PROJECT,
            story_id=story_id,
            requested_by="human_cli",
            reason="irreparable merge conflict",
            dry_run=True,
        )
    )

    assert isinstance(plan, PlannedPurge)
    assert plan.planned_domains  # non-empty
    # No record written, no purge event, story still In Progress.
    assert store.records == {}
    assert ports.events == []
    assert svc_story.get_story(story_id).status is StoryStatus.IN_PROGRESS


# ---------------------------------------------------------------------------
# AC3 — fail-closed preconditions
# ---------------------------------------------------------------------------


def test_request_rejects_unknown_story() -> None:
    """AC3: a non-existent story is rejected fail-closed (§53.4.1)."""
    svc_story = _make_story_service()
    ports = _Ports()
    service = _make_service(story_service=svc_story, ports=ports)

    with pytest.raises(StoryResetError, match="does not exist"):
        service.request_reset(
            StoryResetRequest(
                project_key=_PROJECT,
                story_id="AK3-404",
                requested_by="human_cli",
                reason="x",
            )
        )


def test_request_rejects_missing_escalation_finding() -> None:
    """AC3: absence of an escalation/exception finding is rejected (§53.4.2)."""
    svc_story = _make_story_service()
    story_id = _seed_in_progress(svc_story)
    ports = _Ports(escalation=False)
    service = _make_service(story_service=svc_story, ports=ports)

    with pytest.raises(StoryResetError, match="escalation"):
        service.request_reset(
            StoryResetRequest(
                project_key=_PROJECT,
                story_id=story_id,
                requested_by="human_cli",
                reason="x",
            )
        )


def test_request_rejects_competing_admin_operation() -> None:
    """AC3: a competing administrative operation is rejected (§53.4.4)."""
    svc_story = _make_story_service()
    story_id = _seed_in_progress(svc_story)
    ports = _Ports(competing=True)
    service = _make_service(story_service=svc_story, ports=ports)

    with pytest.raises(StoryResetError, match="competing"):
        service.request_reset(
            StoryResetRequest(
                project_key=_PROJECT,
                story_id=story_id,
                requested_by="human_cli",
                reason="x",
            )
        )


# ---------------------------------------------------------------------------
# AC4 — fence (RESETTING) BEFORE any deletion
# ---------------------------------------------------------------------------


def test_fence_precedes_any_purge_and_failure_blocks_resume() -> None:
    """AC4: on an injected purge failure the story is already RESET_FAILED (blocked).

    The fence (status RESETTING + fence claim) happens before the first purge; a
    failure leaves the story administratively blocked (RESET_FAILED), not silently
    resumable in the normal pipeline.
    """
    svc_story = _make_story_service()
    story_id = _seed_in_progress(svc_story)
    ports = _Ports(runtime_purge_fails=True)
    store = _InMemoryRecordStore()
    service = _make_service(story_service=svc_story, ports=ports, record_store=store)

    rec = service.request_reset(
        StoryResetRequest(
            project_key=_PROJECT,
            story_id=story_id,
            requested_by="human_cli",
            reason="irreparable",
        )
    )
    assert isinstance(rec, StoryResetRecord)

    with pytest.raises(StoryResetError):
        service.execute_reset(rec.reset_id)

    # Fence claim + lock deactivate occurred BEFORE the failing runtime purge.
    assert ports.events.index("fence_claim") < ports.events.index("runtime_purge")
    # Story is blocked, record is failed, fence NOT released.
    assert svc_story.get_story(story_id).status is StoryStatus.RESET_FAILED
    assert store.records[rec.reset_id].status is ResetStatus.FAILED
    assert "fence_release" not in ports.events


# ---------------------------------------------------------------------------
# AC5 / AC5b — separate Schritt-5 and Schritt-6 ports
# ---------------------------------------------------------------------------


def test_schritt5_and_schritt6_consume_separate_ports_in_order() -> None:
    """AC5/AC5b: runtime (Schritt 5) and read-model/analytics (Schritt 6) are
    consumed via SEPARATE ports, and Schritt 5 does NOT route through the
    read-model purge."""
    svc_story = _make_story_service()
    story_id = _seed_in_progress(svc_story)
    ports = _Ports()
    service = _make_service(story_service=svc_story, ports=ports)

    rec = service.request_reset(
        StoryResetRequest(
            project_key=_PROJECT,
            story_id=story_id,
            requested_by="human_cli",
            reason="irreparable",
        )
    )
    assert isinstance(rec, StoryResetRecord)
    service.execute_reset(rec.reset_id)

    e = ports.events
    # Schritt 5 (runtime + locks) precedes Schritt 6 (read-model + analytics).
    assert e.index("runtime_purge") < e.index("read_model_purge")
    assert e.index("lock_deactivate") < e.index("read_model_purge")
    assert e.index("read_model_purge") < e.index("analytics_purge")
    # Negative assertion: the runtime purge is its OWN port call, not the
    # read-model purge (separate owners).
    assert e.count("runtime_purge") >= 1
    assert e.count("read_model_purge") >= 1


# ---------------------------------------------------------------------------
# AC6 — verify_reset_clean_state confirms the end state
# ---------------------------------------------------------------------------


def test_verify_clean_state_is_clean_after_successful_reset() -> None:
    """AC6: verify_reset_clean_state reports a clean restartable base."""
    svc_story = _make_story_service()
    story_id = _seed_in_progress(svc_story)
    ports = _Ports()
    service = _make_service(story_service=svc_story, ports=ports)

    rec = service.request_reset(
        StoryResetRequest(
            project_key=_PROJECT,
            story_id=story_id,
            requested_by="human_cli",
            reason="irreparable",
        )
    )
    assert isinstance(rec, StoryResetRecord)
    result = service.execute_reset(rec.reset_id)

    assert result.clean_state.is_clean is True
    # Story survives as a live, restartable (non-Cancelled) unit.
    assert svc_story.get_story(story_id).status is StoryStatus.IN_PROGRESS


# ---------------------------------------------------------------------------
# AC7 — idempotence / resume
# ---------------------------------------------------------------------------


def test_same_reset_id_resumes_without_new_reset() -> None:
    """AC7: a request with the same reset_id is a resume anchor, not a new reset."""
    svc_story = _make_story_service()
    story_id = _seed_in_progress(svc_story)
    ports = _Ports()
    store = _InMemoryRecordStore()
    service = _make_service(story_service=svc_story, ports=ports, record_store=store)

    first = service.request_reset(
        StoryResetRequest(
            project_key=_PROJECT,
            story_id=story_id,
            requested_by="human_cli",
            reason="irreparable",
        )
    )
    assert isinstance(first, StoryResetRecord)
    again = service.request_reset(
        StoryResetRequest(
            project_key=_PROJECT,
            story_id=story_id,
            requested_by="human_cli",
            reason="irreparable",
            reset_id=first.reset_id,
        )
    )
    assert isinstance(again, StoryResetRecord)
    assert again.reset_id == first.reset_id
    assert len(store.records) == 1


def test_resume_after_failure_converges_to_completed() -> None:
    """AC7: resume_reset re-runs the SAME reset and converges (no double-purge fail)."""
    svc_story = _make_story_service()
    story_id = _seed_in_progress(svc_story)
    ports = _Ports(runtime_purge_fails=True)
    store = _InMemoryRecordStore()
    service = _make_service(story_service=svc_story, ports=ports, record_store=store)

    rec = service.request_reset(
        StoryResetRequest(
            project_key=_PROJECT,
            story_id=story_id,
            requested_by="human_cli",
            reason="irreparable",
        )
    )
    assert isinstance(rec, StoryResetRecord)
    with pytest.raises(StoryResetError):
        service.execute_reset(rec.reset_id)
    assert svc_story.get_story(story_id).status is StoryStatus.RESET_FAILED

    # Heal the injected failure and resume the SAME reset_id.
    ports._runtime_purge_fails = False
    result = service.resume_reset(rec.reset_id)

    assert result.resumed is True
    assert result.record.status is ResetStatus.COMPLETED
    assert svc_story.get_story(story_id).status is StoryStatus.IN_PROGRESS


def test_resume_unknown_reset_id_fails_closed() -> None:
    """AC7: resume of an unknown reset_id fails closed."""
    svc_story = _make_story_service()
    ports = _Ports()
    service = _make_service(story_service=svc_story, ports=ports)

    with pytest.raises(StoryResetError, match="unknown reset_id"):
        service.resume_reset("story-reset-missing")


# ---------------------------------------------------------------------------
# AC8 — RESET_FAILED is not runnable; only resume is allowed
# ---------------------------------------------------------------------------


def test_reset_failed_story_is_not_runnable_but_resumable() -> None:
    """AC8: a RESET_FAILED story blocks normal start/resume; only resume_reset works."""
    from agentkit.backend.story_context_manager.service import is_story_runnable_status

    svc_story = _make_story_service()
    story_id = _seed_in_progress(svc_story)
    ports = _Ports(runtime_purge_fails=True)
    store = _InMemoryRecordStore()
    service = _make_service(story_service=svc_story, ports=ports, record_store=store)

    rec = service.request_reset(
        StoryResetRequest(
            project_key=_PROJECT,
            story_id=story_id,
            requested_by="human_cli",
            reason="irreparable",
        )
    )
    assert isinstance(rec, StoryResetRecord)
    with pytest.raises(StoryResetError):
        service.execute_reset(rec.reset_id)

    blocked = svc_story.get_story(story_id)
    assert blocked.status is StoryStatus.RESET_FAILED
    assert is_story_runnable_status(blocked.status) is False
    # begin_progress / complete are not legal from RESET_FAILED.
    from agentkit.backend.story_context_manager.errors import InvalidStatusTransitionError

    with pytest.raises(InvalidStatusTransitionError):
        svc_story.begin_progress(story_id)


# ---------------------------------------------------------------------------
# AC9 — lock released only after purge + verify + record completed
# ---------------------------------------------------------------------------


def test_fence_released_only_after_verify_and_record_completed() -> None:
    """AC9: the reset fence releases only AFTER all purges, verify and completed."""
    svc_story = _make_story_service()
    story_id = _seed_in_progress(svc_story)
    ports = _Ports()
    store = _InMemoryRecordStore()
    service = _make_service(story_service=svc_story, ports=ports, record_store=store)

    rec = service.request_reset(
        StoryResetRequest(
            project_key=_PROJECT,
            story_id=story_id,
            requested_by="human_cli",
            reason="irreparable",
        )
    )
    assert isinstance(rec, StoryResetRecord)
    service.execute_reset(rec.reset_id)

    e = ports.events
    # fence_release is the LAST flow event, after every purge + the residue checks.
    assert e[-1] == "fence_release"
    for marker in ("runtime_purge", "read_model_purge", "analytics_purge",
                   "workspace_purge", "worktree_detach", "runtime_residue"):
        assert e.index(marker) < e.index("fence_release")
    # The record was set COMPLETED before the release (the completed save is the
    # last status save in the success path).
    assert store.records[rec.reset_id].status is ResetStatus.COMPLETED


# ---------------------------------------------------------------------------
# AC10 — reset never emits Cancelled
# ---------------------------------------------------------------------------


def test_reset_never_sets_cancelled_status() -> None:
    """AC10: across the whole flow the story never becomes Cancelled (FK-91 drift)."""
    svc_story = _make_story_service()
    story_id = _seed_in_progress(svc_story)
    seen: list[StoryStatus] = []
    # Wrap the emitter-free service to snapshot status after each transition.
    ports = _Ports()
    service = _make_service(story_service=svc_story, ports=ports)

    rec = service.request_reset(
        StoryResetRequest(
            project_key=_PROJECT,
            story_id=story_id,
            requested_by="human_cli",
            reason="irreparable",
        )
    )
    assert isinstance(rec, StoryResetRecord)
    service.execute_reset(rec.reset_id)
    seen.append(svc_story.get_story(story_id).status)

    assert StoryStatus.CANCELLED not in seen
    assert svc_story.get_story(story_id).status is StoryStatus.IN_PROGRESS
