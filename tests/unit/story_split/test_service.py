"""End-to-end tests for StorySplitService over REAL production code (AG3-072).

The source story's ``StoryService`` is the real authoritative service backed by
the production in-memory repositories; the administrative split-cancel path, the
Story-Creation contract and the status transitions are exercised for real. Only
the genuine storage/transport seams (control-plane repo, dependency repo,
story.md export, superseded reindex) are in-memory stand-ins — never a stubbed
production producer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.control_plane.records import ControlPlaneOperationRecord
from agentkit.backend.control_plane.repository import ControlPlaneRuntimeRepository
from agentkit.backend.core_types import StoryDependencyKind
from agentkit.backend.core_types.freeze import FreezeKind
from agentkit.backend.execution_planning.entities import StoryDependency
from agentkit.backend.execution_planning.errors import (
    StoryDependencyConflictError,
    StoryDependencyNotFoundError,
)
from agentkit.backend.governance.principal_capabilities.principals import Principal
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
from agentkit.backend.story_creation.story_md_export import (
    StoryMdExportResult,
    export_story_md,
)
from agentkit.backend.story_split import (
    SplitPlan,
    SplitSourceState,
    StorySplitError,
    StorySplitRequest,
    StorySplitSagaGuard,
    StorySplitService,
    compute_plan_ref,
    derive_split_id,
)

if TYPE_CHECKING:
    from collections.abc import Callable

NOW = datetime(2026, 6, 12, 12, 0, tzinfo=UTC)
HARD = StoryDependencyKind.HARD_STORY_DEPENDENCY
SOFT = StoryDependencyKind.SOFT_STORY_DEPENDENCY


# ---------------------------------------------------------------------------
# Real-component fixtures
# ---------------------------------------------------------------------------


class _InMemoryProjectRepository:
    def __init__(self) -> None:
        self._projects: dict[str, Project] = {
            "ak3": Project(
                key="ak3",
                name="AgentKit 3",
                story_id_prefix="AK3",
                configuration=ProjectConfiguration(
                    repo_url="",
                    default_branch="main",
                    default_worker_count=2,
                    repositories=["ak3"],
                ),
            ),
        }

    def get(self, key: str) -> Project | None:
        return self._projects.get(key)

    def list(self, *, include_archived: bool = False) -> list[Project]:
        return list(self._projects.values())

    def save(self, project: Project) -> None:
        self._projects[project.key] = project


class _InMemoryDependencyRepo:
    """Production-faithful in-memory StoryDependencyRepository (real edge models).

    Mirrors ``StateBackendStoryDependencyRepository`` EXACTLY: ``add`` raises
    ``StoryDependencyConflictError`` on a duplicate edge and ``remove`` raises
    ``StoryDependencyNotFoundError`` on a missing edge — the split's idempotent
    apply must therefore check presence first, like against the real store
    (a forgiving fake here would hide a production crash, second-QA finding F1).
    """

    def __init__(self) -> None:
        self.edges: list[StoryDependency] = []

    def list_for_project(self, project_key: str) -> list[StoryDependency]:
        del project_key
        return list(self.edges)

    def add(self, edge: StoryDependency, *, project_key: str) -> None:
        del project_key
        if any(
            e.story_id == edge.story_id
            and e.depends_on_story_id == edge.depends_on_story_id
            and e.kind == edge.kind
            for e in self.edges
        ):
            raise StoryDependencyConflictError("Story dependency already exists")
        self.edges.append(edge)

    def remove(self, story_id: str, depends_on_story_id: str, kind: object) -> None:
        remaining = [
            e
            for e in self.edges
            if not (
                e.story_id == story_id
                and e.depends_on_story_id == depends_on_story_id
                and e.kind == kind
            )
        ]
        if len(remaining) == len(self.edges):
            raise StoryDependencyNotFoundError("Story dependency not found")
        self.edges = remaining


class _RecordingExport:
    def __init__(self) -> None:
        self.exported: list[str] = []

    def export(self, *, story_id: str, story_dir: Path) -> object:
        del story_dir
        self.exported.append(story_id)
        return SimpleResult(success=True)


class _RecordingSuperseded:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def mark_superseded(self, *, story_id: str, superseded_by: tuple[str, ...]) -> int:
        self.calls.append((story_id, superseded_by))
        return 1


@dataclass
class SimpleResult:
    success: bool


class _PhaseStateQuiesce:
    def __init__(self) -> None:
        self.purged: list[tuple[str, str, str]] = []

    def purge_run(self, project_key: str, story_id: str, run_id: str) -> int:
        self.purged.append((project_key, story_id, run_id))
        return 3


class _Governance:
    def __init__(self) -> None:
        self.deactivated: list[str] = []

    def deactivate_locks(self, story_id: str) -> object:
        self.deactivated.append(story_id)
        return SimpleResult(success=True)


class _CpState:
    def __init__(self) -> None:
        self.operations: dict[str, ControlPlaneOperationRecord] = {}
        self.commits: list[str] = []


@dataclass(frozen=True)
class _FreezeRecord:
    freeze_reason: str


class _FreezeStore:
    def __init__(self) -> None:
        self.records: dict[tuple[str, FreezeKind], _FreezeRecord] = {}
        self.entries: list[tuple[str, FreezeKind, str]] = []
        self.clears: list[tuple[str, FreezeKind]] = []

    def set_freeze(
        self,
        story_id: str,
        *,
        frozen_at: str,
        freeze_reason: str,
        freeze_version: int,
        kind: FreezeKind = FreezeKind.CONFLICT_FREEZE,
    ) -> object:
        del frozen_at, freeze_version
        record = _FreezeRecord(freeze_reason=freeze_reason)
        self.records[(story_id, kind)] = record
        self.entries.append((story_id, kind, freeze_reason))
        return record

    def read_freeze(
        self,
        story_id: str,
        kind: FreezeKind = FreezeKind.CONFLICT_FREEZE,
    ) -> object | None:
        return self.records.get((story_id, kind))

    def clear_freeze(
        self,
        story_id: str,
        kind: FreezeKind = FreezeKind.CONFLICT_FREEZE,
    ) -> int:
        if self.records.pop((story_id, kind), None) is None:
            return 0
        self.clears.append((story_id, kind))
        return 1


class _ClaimStore:
    def __init__(self) -> None:
        self.held: dict[tuple[str, str, str], str] = {}
        self.acquired: list[tuple[str, str]] = []
        self.released: list[tuple[str, str]] = []

    def acquire_claim(
        self,
        *,
        project_key: str,
        serialization_scope: str,
        scope_key: str,
        op_id: str,
        backend_instance_id: str,
        instance_incarnation: int,
        acquired_at: datetime,
    ) -> bool:
        del backend_instance_id, instance_incarnation, acquired_at
        key = (project_key, serialization_scope, scope_key)
        if key in self.held:
            return False
        self.held[key] = op_id
        self.acquired.append((scope_key, op_id))
        return True

    def release_claim(
        self,
        project_key: str,
        serialization_scope: str,
        scope_key: str,
        op_id: str,
    ) -> bool:
        key = (project_key, serialization_scope, scope_key)
        if self.held.get(key) != op_id:
            return False
        del self.held[key]
        self.released.append((scope_key, op_id))
        return True


def _cp_repo(state: _CpState) -> ControlPlaneRuntimeRepository:
    def _commit(
        record: ControlPlaneOperationRecord,
        *,
        binding_to_save: object,
        binding_to_delete: object,
        locks: tuple[object, ...],
        events: tuple[object, ...],
        command_id: str | None = None,
        **_kwargs: object,
    ) -> None:
        del binding_to_save, binding_to_delete, locks, events, command_id
        state.operations[record.op_id] = record
        state.commits.append(record.operation_kind)

    return ControlPlaneRuntimeRepository(
        load_operation=state.operations.get,
        commit_operation_with_side_effects=_commit,
        load_active_ownership=lambda _project_key, _story_id: None,
        has_committed_operation_for_run=lambda pk, sid, rid: any(
            op.status == "committed"
            and op.project_key == pk
            and op.story_id == sid
            and op.run_id == rid
            for op in state.operations.values()
        ),
        has_committed_story_exit_operation_for_run=lambda pk, sid, rid: any(
            op.operation_kind == "story_exit"
            and op.project_key == pk
            and op.story_id == sid
            and op.run_id == rid
            for op in state.operations.values()
        ),
    )


@dataclass
class _Harness:
    story_service: StoryService
    split_service: StorySplitService
    dependency_repo: _InMemoryDependencyRepo
    export: _RecordingExport
    superseded: _RecordingSuperseded
    quiesce: _PhaseStateQuiesce
    governance: _Governance
    cp_state: _CpState
    freeze_store: _FreezeStore
    claim_store: _ClaimStore
    closure_calls: list[str]


def _good_source_state(_request: object) -> SplitSourceState:
    return SplitSourceState(
        scope_explosion_established=True,
        paused_with_scope_explosion=True,
        competing_admin_operation_active=False,
    )


def _build_harness(
    *,
    source_state_loader: Callable[[object], SplitSourceState] | None = None,
    seed_in_progress: bool = True,
) -> _Harness:
    story_repo = InMemoryStoryRepository()
    project_repo = _InMemoryProjectRepository()
    story_service = StoryService(
        story_repository=story_repo,
        project_repository=project_repo,  # type: ignore[arg-type]
        idempotency_guard=InMemoryInflightIdempotencyGuard(),
        event_emitter=lambda *a: None,
    )
    closure_calls: list[str] = []
    # Guard: the split must NEVER call complete_story (the closure->Done path).
    original_complete = story_service.complete_story

    def _tracking_complete(story_display_id: str) -> object:
        closure_calls.append(story_display_id)
        return original_complete(story_display_id)

    story_service.complete_story = _tracking_complete  # type: ignore[method-assign]

    if seed_in_progress:
        src = story_service.create_story(
            CreateStoryInput(
                project_key="ak3",
                title="Overscoped source",
                story_type=WireStoryType.IMPLEMENTATION,
                repos=["ak3"],
            ),
            op_id="op-src",
        )
        story_service.approve_story(src.story_display_id, op_id="op-src-approve")
        story_service.begin_progress(src.story_display_id)

    dependency_repo = _InMemoryDependencyRepo()
    export = _RecordingExport()
    superseded = _RecordingSuperseded()
    quiesce = _PhaseStateQuiesce()
    governance = _Governance()
    cp_state = _CpState()
    freeze_store = _FreezeStore()
    claim_store = _ClaimStore()

    split_service = StorySplitService(
        control_plane_repository=_cp_repo(cp_state),
        story_service=story_service,
        dependency_repository=dependency_repo,
        phase_state_quiesce=quiesce,
        governance=governance,
        successor_export=export,
        superseded_index=superseded,
        stories_root=Path("stories"),
        source_state_loader=source_state_loader or _good_source_state,
        saga_guard=StorySplitSagaGuard(
            freeze_store=freeze_store,
            object_claim_store=claim_store,
            backend_instance_id="unit-instance",
            instance_incarnation=1,
            now_fn=lambda: NOW,
        ),
        now_fn=lambda: NOW,
    )
    return _Harness(
        story_service=story_service,
        split_service=split_service,
        dependency_repo=dependency_repo,
        export=export,
        superseded=superseded,
        quiesce=quiesce,
        governance=governance,
        cp_state=cp_state,
        freeze_store=freeze_store,
        claim_store=claim_store,
        closure_calls=closure_calls,
    )


def _plan(*, rebinding: bool = True) -> SplitPlan:
    data: dict[str, object] = {
        "project_key": "ak3",
        "source_story_id": "AK3-001",
        "reason": "scope_explosion",
        "successors": [
            {"story_id": "AK3-107", "title": "Slice A", "scope_slice": "A"},
            {"story_id": "AK3-108", "title": "Slice B", "scope_slice": "B"},
        ],
    }
    if rebinding:
        data["dependency_rebinding"] = [
            {
                "dependent_story_id": "AK3-051",
                "old_dependency": "AK3-001",
                "new_dependencies": ["AK3-107"],
            }
        ]
    return SplitPlan.model_validate(data)


def _request(plan: SplitPlan, *, plan_text: str = "{}") -> StorySplitRequest:
    return StorySplitRequest(
        project_key="ak3",
        source_story_id="AK3-001",
        plan=plan,
        plan_text=plan_text,
        reason="scope_explosion",
        requested_by="human_cli",
        run_id="run-1",
        principal=Principal.HUMAN_CLI,
    )


# ---------------------------------------------------------------------------
# AK4/AK5/AK7/AK8: end-state + successors + lineage + administrative cancel
# ---------------------------------------------------------------------------


def test_successful_split_reaches_fk_54_5_end_state() -> None:
    h = _build_harness()
    # Seed an inbound dependency onto the source so rebinding has real work.
    h.dependency_repo.add(
        StoryDependency(
            story_id="AK3-051", depends_on_story_id="AK3-001", kind=HARD, created_at=NOW
        ),
        project_key="ak3",
    )

    result = h.split_service.split_story(_request(_plan()))

    # Source story Cancelled (backend) via administrative path.
    source = h.story_service.get_story("AK3-001")
    assert source is not None
    assert source.status is StoryStatus.CANCELLED
    assert "scope_split" in (source.blocker or "")

    # Successors created in Backlog via the Story-Creation contract + story.md.
    # The contract allocates the authoritative ids (returned on the result).
    assert len(result.successor_ids) == 2
    for created_id in result.successor_ids:
        succ = h.story_service.get_story(created_id)
        assert succ is not None and succ.status is StoryStatus.BACKLOG
    assert h.export.exported == list(result.successor_ids)

    # Runtime quiesced (phase_state_projection purge + lock deactivation).
    assert h.quiesce.purged == [("ak3", "AK3-001", "run-1")]
    assert h.governance.deactivated == ["AK3-001"]

    # Result axis CONSUMES AG3-074.
    assert result.record.exit_class is not None
    assert result.record.exit_class.value == "scope_split"
    assert result.record.terminal_state is not None
    assert result.record.terminal_state.value == "Cancelled"


def test_successors_created_via_story_creation_contract() -> None:
    h = _build_harness()
    result = h.split_service.split_story(_request(_plan(rebinding=False)))
    succ = h.story_service.get_story(result.successor_ids[0])
    assert succ is not None
    # Inherited stammdaten from the source (Story-Creation contract).
    assert succ.story_type is WireStoryType.IMPLEMENTATION
    assert succ.participating_repos == ["ak3"]
    assert succ.title == "Slice A"


def test_split_from_split_successors_lineage_and_superseded_by() -> None:
    h = _build_harness()
    result = h.split_service.split_story(_request(_plan(rebinding=False)))
    assert result.record.superseded_by == result.successor_ids
    # The cancelled source is re-indexed superseded_by (NOT deleted).
    assert h.superseded.calls == [("AK3-001", result.successor_ids)]


def test_lineage_is_materialized_on_real_stories_with_allocated_ids() -> None:
    """Finding #3: AK7 lineage uses the REAL allocated StoryService ids.

    Reads back the persisted source + successor stories from the real store and
    asserts each successor carries ``split_from = source id`` and the source
    carries ``split_successors = real successor ids`` (and superseded_by == those
    ids). The plan declares plan-local ids (AK3-107/AK3-108) which the contract
    remaps to real ids — the lineage must use the remapped ids, never the plan ids.
    """
    h = _build_harness()
    result = h.split_service.split_story(_request(_plan(rebinding=False)))

    # The real ids differ from the plan-local declaration (AK3-107/AK3-108).
    assert result.successor_ids != ("AK3-107", "AK3-108")
    assert all(sid not in ("AK3-107", "AK3-108") for sid in result.successor_ids)

    # Source carries split_successors = the REAL successor ids; superseded_by too.
    source = h.story_service.get_story("AK3-001")
    assert source is not None
    assert tuple(source.split_successors) == result.successor_ids
    assert result.record.superseded_by == result.successor_ids

    # EACH created successor carries split_from = source id (read back).
    for created_id in result.successor_ids:
        succ = h.story_service.get_story(created_id)
        assert succ is not None
        assert succ.split_from == "AK3-001"
        assert succ.split_successors == []


def test_final_source_state_is_cancelled_with_superseded_by() -> None:
    """Finding #4: the FINAL indexed source state is Cancelled WITH superseded_by.

    The administrative split-cancel sets Cancelled, and the superseded reindex is
    ordered AFTER the cancel — so when ``mark_superseded`` is invoked the source
    is ALREADY Cancelled (a real export would see Cancelled, not In Progress).
    """
    h = _build_harness()
    # Record the source status at the moment mark_superseded is called.
    status_at_reindex: list[str] = []
    original = h.superseded.mark_superseded

    def _spy(*, story_id: str, superseded_by: tuple[str, ...]) -> int:
        seen = h.story_service.get_story(story_id)
        status_at_reindex.append(seen.status.value if seen else "missing")
        return original(story_id=story_id, superseded_by=superseded_by)

    h.superseded.mark_superseded = _spy  # type: ignore[method-assign]

    result = h.split_service.split_story(_request(_plan(rebinding=False)))

    source = h.story_service.get_story("AK3-001")
    assert source is not None
    assert source.status is StoryStatus.CANCELLED
    assert tuple(source.split_successors) == result.successor_ids
    # At reindex time the source was ALREADY Cancelled (order: cancel -> reindex).
    assert status_at_reindex == ["Cancelled"]


def test_administrative_split_cancel_does_not_call_closure() -> None:
    h = _build_harness()
    h.split_service.split_story(_request(_plan(rebinding=False)))
    # The closure->Done path (complete_story) is NEVER used by the split.
    assert h.closure_calls == []
    source = h.story_service.get_story("AK3-001")
    assert source is not None
    assert source.status is StoryStatus.CANCELLED
    assert source.completed_at is None  # not a Done delivery


def test_audit_telemetry_preserved_and_does_not_block_successor() -> None:
    h = _build_harness()
    result = h.split_service.split_story(_request(_plan(rebinding=False)))
    # NOT a full purge: only phase_state_projection is quiesced (steering runtime);
    # analytics/audit are untouched (no analytics purge call exists on this path).
    assert h.quiesce.purged == [("ak3", "AK3-001", "run-1")]
    # Successors start in Backlog (not blocked) regardless of source audit trail.
    succ = h.story_service.get_story(result.successor_ids[0])
    assert succ is not None
    assert succ.status is StoryStatus.BACKLOG


# ---------------------------------------------------------------------------
# AK3: entry-gate negatives (one per precondition), no partial mutation
# ---------------------------------------------------------------------------


def _assert_no_mutation(h: _Harness, *, expect_failed_record: bool = True) -> None:
    """Assert a rejected split left NO partial mutation against the real store.

    The source story stays In Progress (NOT Cancelled), no successor story exists
    beyond the seeded source, nothing was exported, no dependency edge changed.
    By default a single ``failed`` audit record IS expected (AK3 / finding #5):
    the rejection is auditable, not silent. ``expect_failed_record=False`` covers
    a reject that happens before the split_id/failed-record machinery (e.g. an
    unknown source story whose absence is itself the missing precondition).
    """
    source = h.story_service.get_story("AK3-001")
    assert source is not None
    assert source.status is StoryStatus.IN_PROGRESS
    # Only the seeded source exists; no successor was created via the contract.
    assert [s.story_display_id for s in h.story_service.list_stories("ak3")] == [
        "AK3-001"
    ]
    assert source.split_successors == []
    assert h.export.exported == []
    assert h.dependency_repo.edges == []
    if expect_failed_record:
        # A persisted status=failed audit record exists under the resume key, and
        # the ONLY committed/failed op is that failed record — no committed fence.
        assert h.cp_state.commits == ["story_split"]
        op = next(iter(h.cp_state.operations.values()))
        assert op.status == "failed"
        payload = op.response_payload
        assert isinstance(payload, dict)
        assert payload["status"] == "failed"
        assert payload["rejection_reason"]
    else:
        assert h.cp_state.commits == []


def test_entry_gate_rejects_without_scope_explosion() -> None:
    h = _build_harness(
        source_state_loader=lambda _r: SplitSourceState(
            scope_explosion_established=False,
            paused_with_scope_explosion=True,
            competing_admin_operation_active=False,
        )
    )
    with pytest.raises(StorySplitError, match="scope_explosion"):
        h.split_service.split_story(_request(_plan()))
    _assert_no_mutation(h)


def test_entry_gate_rejects_without_paused_escalation_state() -> None:
    h = _build_harness(
        source_state_loader=lambda _r: SplitSourceState(
            scope_explosion_established=True,
            paused_with_scope_explosion=False,
            competing_admin_operation_active=False,
        )
    )
    with pytest.raises(StorySplitError, match="PAUSED"):
        h.split_service.split_story(_request(_plan()))
    _assert_no_mutation(h)


def test_entry_gate_rejects_non_human_principal() -> None:
    h = _build_harness()
    request = StorySplitRequest(
        project_key="ak3",
        source_story_id="AK3-001",
        plan=_plan(),
        plan_text="{}",
        reason="scope_explosion",
        requested_by="orchestrator",
        run_id="run-1",
        principal=Principal.ORCHESTRATOR,
    )
    with pytest.raises(StorySplitError, match="HUMAN_CLI"):
        h.split_service.split_story(request)
    _assert_no_mutation(h)


def test_entry_gate_rejects_competing_admin_operation() -> None:
    h = _build_harness(
        source_state_loader=lambda _r: SplitSourceState(
            scope_explosion_established=True,
            paused_with_scope_explosion=True,
            competing_admin_operation_active=True,
        )
    )
    with pytest.raises(StorySplitError, match="competing administrative"):
        h.split_service.split_story(_request(_plan()))
    _assert_no_mutation(h)


def test_entry_gate_rejects_unknown_source_story() -> None:
    h = _build_harness(seed_in_progress=False)
    with pytest.raises(StorySplitError, match="unknown"):
        h.split_service.split_story(_request(_plan()))
    # No story exists at all; the rejection still persists a failed audit record.
    assert h.story_service.list_stories("ak3") == []
    assert h.cp_state.commits == ["story_split"]
    assert next(iter(h.cp_state.operations.values())).status == "failed"


# ---------------------------------------------------------------------------
# AK6: rebinding invariant negative (no_stale_cancelled_target) end-to-end
# ---------------------------------------------------------------------------


def test_split_fails_closed_on_stale_cancelled_target() -> None:
    h = _build_harness()
    # An unhandled inbound edge onto the source -> rebinding invariant violation.
    h.dependency_repo.add(
        StoryDependency(
            story_id="AK3-060", depends_on_story_id="AK3-001", kind=HARD, created_at=NOW
        ),
        project_key="ak3",
    )
    with pytest.raises(StorySplitError, match="rebinding invalid"):
        h.split_service.split_story(_request(_plan()))
    # FAIL-CLOSED: the rebinding-invalid plan is rejected UP-FRONT in the entry
    # gate. No successor created, nothing exported, source untouched, the inbound
    # edge is unchanged — only the seeded inbound edge remains. A failed audit
    # record is persisted.
    source = h.story_service.get_story("AK3-001")
    assert source is not None
    assert source.status is StoryStatus.IN_PROGRESS
    assert source.split_successors == []
    assert [s.story_display_id for s in h.story_service.list_stories("ak3")] == [
        "AK3-001"
    ]
    assert h.export.exported == []
    assert [(e.story_id, e.depends_on_story_id) for e in h.dependency_repo.edges] == [
        ("AK3-060", "AK3-001")
    ]
    assert h.cp_state.commits == ["story_split"]
    assert next(iter(h.cp_state.operations.values())).status == "failed"


def test_rebinding_invalid_plan_is_clean_failclosed_reject_and_reject_on_rerun() -> None:
    """Finding #1 reproduction: a rebinding-invalid plan must NEVER leave a
    half-split, and a second identical run must be a clean reject (not a bogus
    resume pointing at non-existent ids).

    Drives the REAL service. Asserts: no successors created, no exports, source
    still In Progress and NOT Cancelled, failed audit record persisted; and a
    re-run is again a clean fail-closed reject — never ``resumed=True``.
    """
    h = _build_harness()
    # Inbound edge with no rebinding entry => no_stale_cancelled_target violation.
    h.dependency_repo.add(
        StoryDependency(
            story_id="AK3-070", depends_on_story_id="AK3-001", kind=HARD, created_at=NOW
        ),
        project_key="ak3",
    )

    def _run_and_assert_clean_reject() -> None:
        with pytest.raises(StorySplitError, match="rebinding invalid"):
            h.split_service.split_story(_request(_plan()))
        source = h.story_service.get_story("AK3-001")
        assert source is not None
        # Source still In Progress and NOT Cancelled.
        assert source.status is StoryStatus.IN_PROGRESS
        assert source.split_successors == []
        # No successors created / exported.
        assert [
            s.story_display_id for s in h.story_service.list_stories("ak3")
        ] == ["AK3-001"]
        assert h.export.exported == []
        assert h.superseded.calls == []
        # No committed fence — only the failed audit record under the resume key.
        statuses = {op.status for op in h.cp_state.operations.values()}
        assert statuses == {"failed"}

    _run_and_assert_clean_reject()
    # Second identical run: STILL a clean fail-closed reject, NOT a bogus resume.
    _run_and_assert_clean_reject()


# ---------------------------------------------------------------------------
# AK11: idempotency / resume
# ---------------------------------------------------------------------------


def test_second_run_with_same_story_plan_resumes() -> None:
    h = _build_harness()
    first = h.split_service.split_story(_request(_plan(rebinding=False)))
    assert first.resumed is False
    export_after_first = list(h.export.exported)
    superseded_after_first = list(h.superseded.calls)

    second = h.split_service.split_story(_request(_plan(rebinding=False)))
    assert second.resumed is True
    assert second.split_id == first.split_id
    # No double successor creation / export / superseded reindex.
    assert h.export.exported == export_after_first
    assert h.superseded.calls == superseded_after_first


def test_split_admin_freeze_spans_saga_and_every_step_releases_its_claim() -> None:
    """AC7: the freeze is saga-scoped while claims are strictly step-scoped."""
    h = _build_harness()
    observed_freeze_during_step: list[object | None] = []
    original_export = h.export.export

    def _observe_export(*, story_id: str, story_dir: Path) -> object:
        observed_freeze_during_step.append(
            h.freeze_store.read_freeze(
                "AK3-001",
                FreezeKind.SPLIT_ADMIN_FREEZE,
            )
        )
        return original_export(story_id=story_id, story_dir=story_dir)

    h.export.export = _observe_export  # type: ignore[method-assign]
    h.split_service.split_story(_request(_plan(rebinding=False)))

    assert observed_freeze_during_step
    assert all(record is not None for record in observed_freeze_during_step)
    assert h.freeze_store.entries[0][1] is FreezeKind.SPLIT_ADMIN_FREEZE
    assert h.freeze_store.read_freeze(
        "AK3-001",
        FreezeKind.SPLIT_ADMIN_FREEZE,
    ) is None
    assert h.freeze_store.clears == [("AK3-001", FreezeKind.SPLIT_ADMIN_FREEZE)]
    assert h.claim_store.held == {}
    assert h.claim_store.acquired == h.claim_store.released
    split_id = derive_split_id("ak3", "AK3-001", compute_plan_ref("{}"))
    assert (
        "AK3-001",
        f"{split_id}:successor-create:0:AK3-107",
    ) in h.claim_store.acquired
    assert (
        "AK3-001",
        f"{split_id}:successor-create:1:AK3-108",
    ) in h.claim_store.acquired


def test_successor_creation_rejects_before_mutation_when_source_claim_conflicts() -> (
    None
):
    """AC7: a foreign source claim rejects before successor creation mutates."""
    h = _build_harness()
    original_release = h.claim_store.release_claim

    def _hold_foreign_claim_after_quiesce(
        project_key: str,
        serialization_scope: str,
        scope_key: str,
        op_id: str,
    ) -> bool:
        released = original_release(
            project_key,
            serialization_scope,
            scope_key,
            op_id,
        )
        if op_id.endswith(":quiesce"):
            acquired = h.claim_store.acquire_claim(
                project_key=project_key,
                serialization_scope=serialization_scope,
                scope_key=scope_key,
                op_id="foreign-story-mutation",
                backend_instance_id="foreign-instance",
                instance_incarnation=1,
                acquired_at=NOW,
            )
            assert acquired is True
        return released

    h.claim_store.release_claim = (  # type: ignore[method-assign]
        _hold_foreign_claim_after_quiesce
    )
    split_id = derive_split_id("ak3", "AK3-001", compute_plan_ref("{}"))

    with pytest.raises(
        StorySplitError,
        match=rf"claim for 'AK3-001'.*{split_id}:successor-create:0:AK3-107",
    ):
        h.split_service.split_story(_request(_plan(rebinding=False)))

    assert [
        story.story_display_id for story in h.story_service.list_stories("ak3")
    ] == ["AK3-001"]
    assert h.export.exported == []
    assert h.claim_store.held == {
        ("ak3", "story", "AK3-001"): "foreign-story-mutation"
    }


def test_resume_after_abort_between_subcommits_with_active_admin_freeze_has_no_double_execution() -> None:
    """AC8: abort after source-cancel, then resume the real saga lineage."""
    h = _build_harness()
    h.dependency_repo.add(
        StoryDependency(
            story_id="AK3-051",
            depends_on_story_id="AK3-001",
            kind=HARD,
            created_at=NOW,
        ),
        project_key="ak3",
    )
    original_reindex = h.superseded.mark_superseded
    state = {"raised": False}

    def _abort_between_steps(
        *,
        story_id: str,
        superseded_by: tuple[str, ...],
    ) -> int:
        if not state["raised"]:
            state["raised"] = True
            raise RuntimeError("abort between source-cancel and source-reindex")
        return original_reindex(story_id=story_id, superseded_by=superseded_by)

    h.superseded.mark_superseded = _abort_between_steps  # type: ignore[method-assign]
    plan = _plan()
    with pytest.raises(RuntimeError, match="abort between source-cancel"):
        h.split_service.split_story(_request(plan))

    source = h.story_service.get_story("AK3-001")
    assert source is not None and source.status is StoryStatus.CANCELLED
    assert h.freeze_store.read_freeze(
        "AK3-001",
        FreezeKind.SPLIT_ADMIN_FREEZE,
    ) is not None
    assert h.claim_store.held == {}
    stories_before_resume = tuple(
        story.story_display_id for story in h.story_service.list_stories("ak3")
    )
    edges_before_resume = tuple(
        (edge.story_id, edge.depends_on_story_id, edge.kind)
        for edge in h.dependency_repo.edges
    )
    blocker_before_resume = source.blocker

    result = h.split_service.split_story(_request(plan))

    assert result.resumed is True
    assert tuple(
        story.story_display_id for story in h.story_service.list_stories("ak3")
    ) == stories_before_resume
    assert tuple(
        (edge.story_id, edge.depends_on_story_id, edge.kind)
        for edge in h.dependency_repo.edges
    ) == edges_before_resume
    source = h.story_service.get_story("AK3-001")
    assert source is not None
    assert source.status is StoryStatus.CANCELLED
    assert source.blocker == blocker_before_resume
    assert h.freeze_store.read_freeze(
        "AK3-001",
        FreezeKind.SPLIT_ADMIN_FREEZE,
    ) is None
    assert h.claim_store.held == {}


def test_failed_record_is_overwritten_by_a_later_successful_split() -> None:
    """Finding #1/#5: a rejected run persists a failed audit record under the
    resume key; a later run whose preconditions now hold OVERWRITES that failed
    record with a real committed split (the failed record never blocks the
    official path as a foreign collision)."""
    state = {"competing": True}
    h = _build_harness(
        source_state_loader=lambda _r: SplitSourceState(
            scope_explosion_established=True,
            paused_with_scope_explosion=True,
            competing_admin_operation_active=state["competing"],
        )
    )
    # First run: a competing admin op blocks it -> failed audit record.
    with pytest.raises(StorySplitError, match="competing administrative"):
        h.split_service.split_story(_request(_plan(rebinding=False)))
    op = next(iter(h.cp_state.operations.values()))
    assert op.status == "failed"

    # The competing op clears; the SAME --story/--plan now succeeds and the
    # failed record converges into a committed split (same split_id resume key).
    state["competing"] = False
    result = h.split_service.split_story(_request(_plan(rebinding=False)))
    assert result.resumed is False
    assert result.record.status.value == "committed"
    assert h.cp_state.operations[result.split_id].status == "committed"
    source = h.story_service.get_story("AK3-001")
    assert source is not None and source.status is StoryStatus.CANCELLED


def test_resume_rejects_foreign_committed_fence() -> None:
    h = _build_harness()
    h.split_service.split_story(_request(_plan(rebinding=False)))
    # Re-point the committed op at a different story -> resume must fail closed.
    op = next(iter(h.cp_state.operations.values()))
    h.cp_state.operations[op.op_id] = ControlPlaneOperationRecord(
        op_id=op.op_id,
        project_key=op.project_key,
        story_id="AK3-999",
        run_id=op.run_id,
        session_id=None,
        operation_kind="story_split",
        phase=None,
        status="committed",
        response_payload={},
        created_at=NOW,
        updated_at=NOW,
    )
    with pytest.raises(StorySplitError, match="different story"):
        h.split_service.split_story(_request(_plan(rebinding=False)))


def test_resume_converges_after_real_post_create_export_fault() -> None:
    """CRUX (Codex r2 gap): a REAL fault AFTER a successor is created
    (``create_story`` succeeds) but BEFORE ``_finalize_fence`` must converge on
    rerun, not strand a half-split.

    The fault is injected by a thin test seam around the REAL production export
    call (``_export_successor`` -> ``export``): the FIRST export raises, after at
    least one successor has been created and the real id checkpointed onto the
    durable fence. The first run therefore fails with the fence committed but NOT
    finalized. A SECOND identical run (same --story/--plan) RESUMES via the same
    split_id and CONVERGES to the full §54.5 end-state — exactly once.
    """
    h = _build_harness()
    # Seed an inbound dependency so rebinding does real work on convergence too.
    h.dependency_repo.add(
        StoryDependency(
            story_id="AK3-051", depends_on_story_id="AK3-001", kind=HARD, created_at=NOW
        ),
        project_key="ak3",
    )

    # Thin fault seam around the REAL export call: raise on the first export, then
    # behave normally. By the time it raises, create_story for the first successor
    # has already succeeded and the real id is checkpointed on the fence.
    real_export = h.export.export
    state = {"raised": False}

    def _faulty_export(*, story_id: str, story_dir: Path) -> object:
        if not state["raised"]:
            state["raised"] = True
            raise RuntimeError("injected post-create export fault")
        return real_export(story_id=story_id, story_dir=story_dir)

    h.export.export = _faulty_export  # type: ignore[method-assign]

    plan = _plan()  # includes a rebinding entry AK3-051 -> AK3-107
    # First run: the real export fault aborts the split mid-sequence.
    with pytest.raises(RuntimeError, match="injected post-create export fault"):
        h.split_service.split_story(_request(plan))

    # The fence is committed but NOT finalized (no successor_ids); a real id was
    # checkpointed under successor_map. Source still In Progress, NOT Cancelled.
    split_id = derive_split_id("ak3", "AK3-001", compute_plan_ref("{}"))
    fence = h.cp_state.operations[split_id]
    assert fence.status == "committed"
    assert "successor_ids" not in fence.response_payload
    assert isinstance(fence.response_payload.get("successor_map"), dict)
    source = h.story_service.get_story("AK3-001")
    assert source is not None and source.status is StoryStatus.IN_PROGRESS

    # Second identical run RESUMES and CONVERGES to the full §54.5 end-state.
    result = h.split_service.split_story(_request(plan))
    assert result.resumed is True

    # Source Cancelled + superseded_by = the REAL ids; no second cancel anomaly.
    source = h.story_service.get_story("AK3-001")
    assert source is not None
    assert source.status is StoryStatus.CANCELLED
    assert "scope_split" in (source.blocker or "")
    assert tuple(source.split_successors) == result.successor_ids
    assert result.record.superseded_by == result.successor_ids
    assert h.closure_calls == []  # never via closure

    # Successors exist EXACTLY ONCE (no duplicates), in Backlog, with REAL ids.
    stories = [s.story_display_id for s in h.story_service.list_stories("ak3")]
    assert stories.count("AK3-001") == 1
    assert len(result.successor_ids) == 2
    assert all(sid not in ("AK3-107", "AK3-108") for sid in result.successor_ids)
    assert len(set(result.successor_ids)) == 2
    # Exactly source + 2 successors, no third/duplicate successor leaked.
    assert len(stories) == 3
    for created_id in result.successor_ids:
        succ = h.story_service.get_story(created_id)
        assert succ is not None
        assert succ.status is StoryStatus.BACKLOG
        assert succ.split_from == "AK3-001"

    # Both successors exported (the convergent run completed every export).
    assert sorted(set(h.export.exported)) == sorted(result.successor_ids)
    # Rebinding applied exactly once: the inbound edge was rebound onto AK3-107's
    # real id, and no stale edge onto the cancelled source remains.
    real_107 = result.successor_ids[0]
    edges = [(e.story_id, e.depends_on_story_id) for e in h.dependency_repo.edges]
    assert ("AK3-051", real_107) in edges
    assert ("AK3-051", "AK3-001") not in edges
    # Superseded reindex reflects the real ids exactly once at the end.
    assert h.superseded.calls[-1] == ("AK3-001", result.successor_ids)


def test_resume_converges_from_unfinalized_fence_before_any_successor() -> None:
    """A committed fence with NO checkpoint and NO created successors (a prior run
    that crashed right after the fence commit, before step 4) is a CONVERGENT
    resume: it re-runs the whole §54.8 sequence cleanly to the end-state — it does
    NOT dead-end and NEVER fabricates plan-local ids (the real ids are allocated
    fresh by the deterministic Story-Creation contract)."""
    h = _build_harness()
    plan = _plan(rebinding=False)
    plan_text = "{}"
    plan_ref = compute_plan_ref(plan_text)
    split_id = derive_split_id("ak3", "AK3-001", plan_ref)
    # Half-done prior run: fence committed, empty payload (no successor_map, no
    # successor_ids), nothing created yet.
    h.cp_state.operations[split_id] = ControlPlaneOperationRecord(
        op_id=split_id,
        project_key="ak3",
        story_id="AK3-001",
        run_id="run-1",
        session_id=None,
        operation_kind="story_split",
        phase=None,
        status="committed",
        response_payload={"status": "committed", "op_id": split_id},
        created_at=NOW,
        updated_at=NOW,
    )
    result = h.split_service.split_story(_request(plan, plan_text=plan_text))
    assert result.resumed is True
    # Converged to the full end-state: source Cancelled, two real successors.
    source = h.story_service.get_story("AK3-001")
    assert source is not None and source.status is StoryStatus.CANCELLED
    assert len(result.successor_ids) == 2
    assert all(sid not in ("AK3-107", "AK3-108") for sid in result.successor_ids)
    for created_id in result.successor_ids:
        succ = h.story_service.get_story(created_id)
        assert succ is not None and succ.status is StoryStatus.BACKLOG
    assert tuple(source.split_successors) == result.successor_ids


def _two_dependent_plan() -> SplitPlan:
    """A plan with TWO rebinding entries (two real dependents onto the source)."""
    return SplitPlan.model_validate(
        {
            "project_key": "ak3",
            "source_story_id": "AK3-001",
            "reason": "scope_explosion",
            "successors": [
                {"story_id": "AK3-107", "title": "Slice A", "scope_slice": "A"},
                {"story_id": "AK3-108", "title": "Slice B", "scope_slice": "B"},
            ],
            "dependency_rebinding": [
                {
                    "dependent_story_id": "AK3-051",
                    "old_dependency": "AK3-001",
                    "new_dependencies": ["AK3-107"],
                },
                {
                    "dependent_story_id": "AK3-052",
                    "old_dependency": "AK3-001",
                    "new_dependencies": ["AK3-108"],
                },
            ],
        }
    )


def test_resume_converges_after_real_mid_rebinding_fault() -> None:
    """Second-QA finding F1: a crash IN THE MIDDLE of the rebinding apply (after
    a real edge removal persisted, before the rest of the plan applied) must be a
    CONVERGENT resume — not a permanent ``no_silent_drop`` dead-end.

    Drives the REAL service against the production-faithful dependency repo
    (raises on duplicate add / missing remove, exactly like
    ``StateBackendStoryDependencyRepository``). The first run crashes after the
    FIRST removal is durably applied; the partially-rebound graph (old edge of
    dependent #1 gone, no additions yet, dependent #2 untouched) must converge on
    rerun to the full §54.5 end-state with no duplicate edges.
    """
    h = _build_harness()
    h.dependency_repo.add(
        StoryDependency(
            story_id="AK3-051", depends_on_story_id="AK3-001", kind=HARD, created_at=NOW
        ),
        project_key="ak3",
    )
    h.dependency_repo.add(
        StoryDependency(
            story_id="AK3-052", depends_on_story_id="AK3-001", kind=HARD, created_at=NOW
        ),
        project_key="ak3",
    )
    plan = _two_dependent_plan()

    # Crash semantics: the FIRST removal is durably applied, THEN the process
    # dies (raise after the real mutation).
    original_remove = h.dependency_repo.remove
    state = {"removals": 0, "armed": True}

    def _faulty_remove(story_id: str, depends_on_story_id: str, kind: object) -> None:
        original_remove(story_id, depends_on_story_id, kind)
        state["removals"] += 1
        if state["armed"] and state["removals"] == 1:
            raise RuntimeError("injected mid-rebinding fault")

    h.dependency_repo.remove = _faulty_remove  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="mid-rebinding fault"):
        h.split_service.split_story(_request(plan))

    # Partially-rebound graph: dependent #1's old edge is GONE, no additions yet,
    # dependent #2 still points at the source. Source NOT cancelled.
    edges = [(e.story_id, e.depends_on_story_id) for e in h.dependency_repo.edges]
    assert ("AK3-051", "AK3-001") not in edges
    assert ("AK3-052", "AK3-001") in edges
    source = h.story_service.get_story("AK3-001")
    assert source is not None and source.status is StoryStatus.IN_PROGRESS

    # Rerun (no fault): the resume must CONVERGE, not dead-end on no_silent_drop.
    state["armed"] = False
    result = h.split_service.split_story(_request(plan))
    assert result.resumed is True

    source = h.story_service.get_story("AK3-001")
    assert source is not None and source.status is StoryStatus.CANCELLED
    real_107, real_108 = result.successor_ids
    edges = [(e.story_id, e.depends_on_story_id) for e in h.dependency_repo.edges]
    # Both old edges gone, both rebound edges present EXACTLY once.
    assert ("AK3-051", "AK3-001") not in edges
    assert ("AK3-052", "AK3-001") not in edges
    assert edges.count(("AK3-051", real_107)) == 1
    assert edges.count(("AK3-052", real_108)) == 1
    assert len(edges) == 2
    # A THIRD run is a pure no-op replay (finalized fence).
    again = h.split_service.split_story(_request(plan))
    assert again.resumed is True
    assert [(e.story_id, e.depends_on_story_id) for e in h.dependency_repo.edges] == edges


def _one_dependent_multikind_plan() -> SplitPlan:
    """A plan with ONE rebinding entry for a dependent that holds TWO old edges
    onto the source of DIFFERENT kinds (hard + soft), both rebound onto the same
    successor. The full dependency identity is ``(dependent, target, kind)``, so
    the resolved plan carries TWO removals and TWO additions preserving each
    kind (``rebinding.py`` emits one removal/addition per source edge)."""
    return SplitPlan.model_validate(
        {
            "project_key": "ak3",
            "source_story_id": "AK3-001",
            "reason": "scope_explosion",
            "successors": [
                {"story_id": "AK3-107", "title": "Slice A", "scope_slice": "A"},
                {"story_id": "AK3-108", "title": "Slice B", "scope_slice": "B"},
            ],
            "dependency_rebinding": [
                {
                    "dependent_story_id": "AK3-051",
                    "old_dependency": "AK3-001",
                    "new_dependencies": ["AK3-107"],
                },
            ],
        }
    )


def test_resume_converges_after_multikind_mid_rebinding_fault() -> None:
    """r6 Blocker (Codex r5): a dependent with TWO old edges onto the source of
    DIFFERENT kinds (hard + soft) rebinds to BOTH kinds on the successor. A crash
    AFTER all removals AND AFTER the FIRST addition but BEFORE the second must be
    a CONVERGENT resume that restores BOTH kinds exactly once — not a finalize
    that silently drops the second kind.

    The pre-fix kind-blind ``_rebinding_already_applied`` short-circuit saw "no
    inbound source edge AND one successor edge of some kind" and declared the
    rebinding done, finalising the split with the second kind missing. The fix
    makes the kind-aware durable checkpoint the single convergence gate, so the
    second (soft) addition is replayed on resume.

    Drives the REAL service against the production-faithful dependency repo
    (raises on duplicate add / missing remove).
    """
    h = _build_harness()
    # ONE dependent, TWO old edges onto the source of DIFFERENT kinds.
    h.dependency_repo.add(
        StoryDependency(
            story_id="AK3-051", depends_on_story_id="AK3-001", kind=HARD, created_at=NOW
        ),
        project_key="ak3",
    )
    h.dependency_repo.add(
        StoryDependency(
            story_id="AK3-051", depends_on_story_id="AK3-001", kind=SOFT, created_at=NOW
        ),
        project_key="ak3",
    )
    plan = _one_dependent_multikind_plan()

    # Crash semantics: BOTH removals are durably applied, then the FIRST addition
    # is durably applied, then the process dies BEFORE the second addition. This
    # is exactly the half-mutated graph Codex reproduced: no inbound source edge,
    # one successor edge (one kind) present, the other kind still missing.
    original_add = h.dependency_repo.add
    state = {"adds": 0, "armed": True}

    def _faulty_add(edge: StoryDependency, *, project_key: str) -> None:
        original_add(edge, project_key=project_key)
        state["adds"] += 1
        if state["armed"] and state["adds"] == 1:
            raise RuntimeError("injected multikind mid-rebinding fault")

    h.dependency_repo.add = _faulty_add  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="multikind mid-rebinding fault"):
        h.split_service.split_story(_request(plan))

    # Half-mutated graph: both old edges gone, exactly ONE successor edge present
    # (one kind), source NOT cancelled. This is the precise state that fooled the
    # kind-blind shortcut.
    triples = [
        (e.story_id, e.depends_on_story_id, e.kind) for e in h.dependency_repo.edges
    ]
    assert ("AK3-051", "AK3-001", HARD) not in triples
    assert ("AK3-051", "AK3-001", SOFT) not in triples
    successor_edges = [t for t in triples if t[0] == "AK3-051"]
    assert len(successor_edges) == 1
    source = h.story_service.get_story("AK3-001")
    assert source is not None and source.status is StoryStatus.IN_PROGRESS

    # Rerun (no fault): the resume must CONVERGE via the kind-aware checkpoint and
    # restore BOTH kinds — NOT short-circuit on "one successor edge exists".
    state["armed"] = False
    result = h.split_service.split_story(_request(plan))
    assert result.resumed is True

    source = h.story_service.get_story("AK3-001")
    assert source is not None and source.status is StoryStatus.CANCELLED
    real_107 = result.successor_ids[0]
    final = [
        (e.story_id, e.depends_on_story_id, e.kind) for e in h.dependency_repo.edges
    ]
    # Both old edges gone; BOTH kinds rebound onto the successor EXACTLY once.
    assert ("AK3-051", "AK3-001", HARD) not in final
    assert ("AK3-051", "AK3-001", SOFT) not in final
    assert final.count(("AK3-051", real_107, HARD)) == 1
    assert final.count(("AK3-051", real_107, SOFT)) == 1
    assert len(final) == 2

    # A THIRD run is a pure no-op replay (finalized fence) — kinds stay intact.
    again = h.split_service.split_story(_request(plan))
    assert again.resumed is True
    assert [
        (e.story_id, e.depends_on_story_id, e.kind) for e in h.dependency_repo.edges
    ] == final


def test_entry_gate_rejects_source_not_in_progress() -> None:
    """Second-QA finding F2: a source story that is NOT In Progress must be
    rejected AT THE GATE (§54.4 fail-closed, no partial mutation) — not stranded
    mid-flow at the administrative cancel after successors were already created.
    """
    h = _build_harness(seed_in_progress=False)
    src = h.story_service.create_story(
        CreateStoryInput(
            project_key="ak3",
            title="Overscoped source",
            story_type=WireStoryType.IMPLEMENTATION,
            repos=["ak3"],
        ),
        op_id="op-src",
    )
    h.story_service.approve_story(src.story_display_id, op_id="op-src-approve")

    with pytest.raises(StorySplitError, match="In Progress"):
        h.split_service.split_story(_request(_plan(rebinding=False)))

    # NO partial mutation: source still Approved, no successors, nothing exported,
    # only the failed audit record exists (no committed fence).
    source = h.story_service.get_story("AK3-001")
    assert source is not None
    assert source.status is StoryStatus.APPROVED
    assert [s.story_display_id for s in h.story_service.list_stories("ak3")] == [
        "AK3-001"
    ]
    assert h.export.exported == []
    assert {op.status for op in h.cp_state.operations.values()} == {"failed"}


def test_resume_requires_human_cli_principal() -> None:
    """Second-QA finding F3: the resume path must re-assert the §54.4 human
    approval BEFORE any convergent mutation — a non-human principal must not be
    able to drive a crashed split forward just because a committed fence exists.
    """
    h = _build_harness()
    _seed_unfinalized_fence(h, successor_map={})
    request = StorySplitRequest(
        project_key="ak3",
        source_story_id="AK3-001",
        plan=_plan(rebinding=False),
        plan_text="{}",
        reason="scope_explosion",
        requested_by="orchestrator",
        run_id="run-1",
        principal=Principal.ORCHESTRATOR,
    )
    with pytest.raises(StorySplitError, match="HUMAN_CLI"):
        h.split_service.split_story(request)
    # NO convergent mutation happened: no successor created, nothing quiesced,
    # nothing exported, source untouched.
    assert [s.story_display_id for s in h.story_service.list_stories("ak3")] == [
        "AK3-001"
    ]
    source = h.story_service.get_story("AK3-001")
    assert source is not None and source.status is StoryStatus.IN_PROGRESS
    assert h.quiesce.purged == []
    assert h.export.exported == []


def test_resume_fails_closed_on_inconsistent_checkpoint() -> None:
    """Genuinely irrecoverable partial state still fails closed (and says why): a
    checkpoint that points at a vanished successor story / an unknown plan id is
    NOT silently converged."""
    h = _build_harness()
    plan = _plan(rebinding=False)
    plan_text = "{}"
    plan_ref = compute_plan_ref(plan_text)
    split_id = derive_split_id("ak3", "AK3-001", plan_ref)
    # Checkpoint references a real-id story that does not exist in the store.
    h.cp_state.operations[split_id] = ControlPlaneOperationRecord(
        op_id=split_id,
        project_key="ak3",
        story_id="AK3-001",
        run_id="run-1",
        session_id=None,
        operation_kind="story_split",
        phase=None,
        status="committed",
        response_payload={
            "status": "committed",
            "op_id": split_id,
            "successor_map": {"AK3-107": "AK3-9999"},
        },
        created_at=NOW,
        updated_at=NOW,
    )
    with pytest.raises(StorySplitError, match="no longer exists"):
        h.split_service.split_story(_request(plan, plan_text=plan_text))
    # The source was not mutated to Cancelled by the failed reconstruction.
    source = h.story_service.get_story("AK3-001")
    assert source is not None and source.status is StoryStatus.IN_PROGRESS


def _seed_unfinalized_fence(h: _Harness, *, successor_map: object) -> None:
    split_id = derive_split_id("ak3", "AK3-001", compute_plan_ref("{}"))
    h.cp_state.operations[split_id] = ControlPlaneOperationRecord(
        op_id=split_id,
        project_key="ak3",
        story_id="AK3-001",
        run_id="run-1",
        session_id=None,
        operation_kind="story_split",
        phase=None,
        status="committed",
        response_payload={
            "status": "committed",
            "op_id": split_id,
            "successor_map": successor_map,
        },
        created_at=NOW,
        updated_at=NOW,
    )


def test_resume_fails_closed_on_malformed_checkpoint_map() -> None:
    """A non-mapping ``successor_map`` is a corrupt checkpoint -> fail closed."""
    h = _build_harness()
    _seed_unfinalized_fence(h, successor_map="not-a-mapping")
    with pytest.raises(StorySplitError, match="not a mapping"):
        h.split_service.split_story(_request(_plan(rebinding=False)))
    source = h.story_service.get_story("AK3-001")
    assert source is not None and source.status is StoryStatus.IN_PROGRESS


def test_resume_fails_closed_on_checkpoint_unknown_plan_id() -> None:
    """A checkpoint plan id the supplied --plan no longer declares is an
    inconsistent partial state -> fail closed (says why)."""
    h = _build_harness()
    _seed_unfinalized_fence(h, successor_map={"AK3-NOPE": "AK3-002"})
    with pytest.raises(StorySplitError, match="unknown plan successor"):
        h.split_service.split_story(_request(_plan(rebinding=False)))
    source = h.story_service.get_story("AK3-001")
    assert source is not None and source.status is StoryStatus.IN_PROGRESS


# ---------------------------------------------------------------------------
# AK5/AK12 (Codex r4 BLOCKER): a REAL StoryMdExportResult(success=False) from
# the production export/reindex channel must FAIL CLOSED — not be swallowed.
# ---------------------------------------------------------------------------


class _ControllableIndex:
    """A real ``StoryIndexPort`` whose indexing fault is per-story controllable.

    Wraps the REAL ``export_story_md`` indexing seam: when a story id is armed
    to fail, ``index_story`` raises a genuine ``VectorDbError`` — which makes
    the production ``export_story_md`` RETURN ``StoryMdExportResult(success=False)``
    (the exact production failure channel, NOT a parallel fake flow). Disarming
    the story makes the same real export succeed (the convergent-retry path).
    """

    def __init__(self) -> None:
        self.fail_ids: set[str] = set()
        self.fail_first_non_source: bool = False
        self.indexed: list[str] = []

    def index_story(
        self, *, story_id: str, objects: object
    ) -> int:
        from agentkit.integration_clients.vectordb import VectorDbWriteError

        del objects
        fail = story_id in self.fail_ids or (
            self.fail_first_non_source and story_id != "AK3-001"
        )
        if fail:
            raise VectorDbWriteError(f"injected Weaviate write fault for {story_id}")
        self.indexed.append(story_id)
        return 1


class _RealSuccessorExport:
    """Production-faithful successor export: drives the REAL ``export_story_md``."""

    def __init__(
        self, story_service: StoryService, index: _ControllableIndex
    ) -> None:
        self._story_service = story_service
        self._index = index
        self.results: list[StoryMdExportResult] = []

    def export(self, *, story_id: str, story_dir: Path) -> object:
        result = export_story_md(
            story_id,
            story_dir,
            story_attributes=self._story_service,  # type: ignore[arg-type]
            index=self._index,
        )
        self.results.append(result)
        return result


class _RealSupersededIndex:
    """Production-faithful source superseded reindex (mirrors composition_root).

    Re-exports the cancelled source via the REAL ``export_story_md`` and, like
    the production ``_SupersededIndex``, FAILS CLOSED on a ``success=False``
    result (raises instead of returning 0) so a real source export/reindex
    failure can never finalize the split.
    """

    def __init__(
        self,
        story_service: StoryService,
        index: _ControllableIndex,
        stories_root: Path,
    ) -> None:
        self._story_service = story_service
        self._index = index
        self._stories_root = stories_root
        self.results: list[StoryMdExportResult] = []

    def mark_superseded(
        self, *, story_id: str, superseded_by: tuple[str, ...]
    ) -> int:
        self._story_service.materialize_split_lineage(
            source_story_id=story_id,
            successor_ids=superseded_by,
        )
        result = export_story_md(
            story_id,
            self._stories_root / story_id,
            story_attributes=self._story_service,  # type: ignore[arg-type]
            index=self._index,
        )
        self.results.append(result)
        if not result.success:
            raise StorySplitError(
                f"source superseded re-export/reindex failed for {story_id!r}: "
                f"{result.error or 'no detail reported'}",
            )
        return 1


@dataclass
class _RealExportHarness:
    story_service: StoryService
    split_service: StorySplitService
    index: _ControllableIndex
    successor_export: _RealSuccessorExport
    superseded: _RealSupersededIndex
    cp_state: _CpState
    closure_calls: list[str]


def _build_real_export_harness(stories_root: Path) -> _RealExportHarness:
    """Harness wiring the REAL ``export_story_md`` for both export/reindex sites."""
    story_repo = InMemoryStoryRepository()
    project_repo = _InMemoryProjectRepository()
    story_service = StoryService(
        story_repository=story_repo,
        project_repository=project_repo,  # type: ignore[arg-type]
        idempotency_guard=InMemoryInflightIdempotencyGuard(),
        event_emitter=lambda *a: None,
    )
    closure_calls: list[str] = []
    original_complete = story_service.complete_story

    def _tracking_complete(story_display_id: str) -> object:
        closure_calls.append(story_display_id)
        return original_complete(story_display_id)

    story_service.complete_story = _tracking_complete  # type: ignore[method-assign]

    # Enrich the source so the inherited successor / re-exported source story.md
    # clears the FK-21 §21.11.5 > 500-byte validation gate and the export reaches
    # the indexing seam (the VectorDB failure channel Codex named).
    src = story_service.create_story(
        CreateStoryInput(
            project_key="ak3",
            title=(
                "Overscoped source story whose scope exploded into several "
                "distinct deliverable slices that must be split apart"
            ),
            story_type=WireStoryType.IMPLEMENTATION,
            repos=["ak3"],
            epic="EPIC-scope-explosion-recovery",
            module="story_split",
            owner="human_cli",
            labels=[
                "scope-explosion-recovery-administrative-split-candidate",
                "fk-54-section-54-8-seven-step-split-transaction",
                "ak3-072-story-split-service-fail-closed-export-reindex",
                "successor-story-md-export-vectordb-indexing-hard-blocker",
                "convergent-resume-committed-but-unfinalized-fence-checkpoint",
                "superseded-by-reindex-not-deleted-cancelled-source-state",
            ],
        ),
        op_id="op-src",
    )
    story_service.approve_story(src.story_display_id, op_id="op-src-approve")
    story_service.begin_progress(src.story_display_id)

    index = _ControllableIndex()
    successor_export = _RealSuccessorExport(story_service, index)
    superseded = _RealSupersededIndex(story_service, index, stories_root)
    cp_state = _CpState()

    split_service = StorySplitService(
        control_plane_repository=_cp_repo(cp_state),
        story_service=story_service,
        dependency_repository=_InMemoryDependencyRepo(),
        phase_state_quiesce=_PhaseStateQuiesce(),
        governance=_Governance(),
        successor_export=successor_export,
        superseded_index=superseded,
        stories_root=stories_root,
        source_state_loader=_good_source_state,
        saga_guard=StorySplitSagaGuard(
            freeze_store=_FreezeStore(),
            object_claim_store=_ClaimStore(),
            backend_instance_id="unit-instance",
            instance_incarnation=1,
            now_fn=lambda: NOW,
        ),
        now_fn=lambda: NOW,
    )
    return _RealExportHarness(
        story_service=story_service,
        split_service=split_service,
        index=index,
        successor_export=successor_export,
        superseded=superseded,
        cp_state=cp_state,
        closure_calls=closure_calls,
    )


def _real_export_split_id() -> str:
    return derive_split_id("ak3", "AK3-001", compute_plan_ref("{}"))


def test_split_fails_closed_on_real_successor_export_failure_then_converges(
    tmp_path: Path,
) -> None:
    """Codex r4 BLOCKER (crux): a REAL ``StoryMdExportResult(success=False)`` from
    the SUCCESSOR export channel must FAIL CLOSED — not be swallowed.

    Unlike the r2 crux (which injects a ``RuntimeError``), this exercises the
    production failure channel Codex named: ``export_story_md`` RETURNS
    ``success=False`` (here via a real ``VectorDbError`` at the indexing seam)
    rather than raising. The split must NOT proceed through rebinding / cancel /
    reindex / ``_finalize_fence`` on a failed export.

    First run: a successor export returns ``success=False`` -> the split fails
    closed (typed ``StorySplitError``), the fence is committed-but-UNfinalized
    (no ``successor_ids``), the source is NOT Cancelled and never falsely "done".
    Then the indexing is made to succeed and a rerun RESUMES and CONVERGES to the
    full §54.5 end-state exactly once (transient failure converges on retry).
    """
    h = _build_real_export_harness(tmp_path)
    plan = _plan(rebinding=False)

    # Any successor's REAL export hits a real VectorDbError -> the production
    # export_story_md RETURNS success=False (not a raise). Position-based so it
    # does not depend on the exact allocated successor id.
    h.index.fail_first_non_source = True

    with pytest.raises(StorySplitError, match="successor story.md export"):
        h.split_service.split_story(_request(plan))

    # The genuine production result object was success=False (real channel).
    assert h.successor_export.results
    assert h.successor_export.results[-1].success is False
    assert "Weaviate indexing failed" in h.successor_export.results[-1].error

    # FAIL CLOSED: source NOT Cancelled, no superseded reindex, fence committed
    # but NOT finalized (no successor_ids) — never a silent success.
    source = h.story_service.get_story("AK3-001")
    assert source is not None and source.status is StoryStatus.IN_PROGRESS
    assert source.split_successors == []
    assert h.superseded.results == []
    assert h.closure_calls == []
    fence = h.cp_state.operations[_real_export_split_id()]
    assert fence.status == "committed"
    assert "successor_ids" not in fence.response_payload
    # The real id was checkpointed before the crash-prone export.
    assert isinstance(fence.response_payload.get("successor_map"), dict)

    # Make the export succeed; a rerun RESUMES and CONVERGES exactly once.
    h.index.fail_first_non_source = False
    result = h.split_service.split_story(_request(plan))
    assert result.resumed is True

    source = h.story_service.get_story("AK3-001")
    assert source is not None and source.status is StoryStatus.CANCELLED
    assert tuple(source.split_successors) == result.successor_ids
    assert result.record.superseded_by == result.successor_ids
    assert h.closure_calls == []
    # Exactly source + 2 successors (no duplicate from the failed first run).
    stories = [s.story_display_id for s in h.story_service.list_stories("ak3")]
    assert len(stories) == 3
    assert stories.count("AK3-001") == 1
    for created_id in result.successor_ids:
        succ = h.story_service.get_story(created_id)
        assert succ is not None and succ.status is StoryStatus.BACKLOG
    # The source superseded reindex really succeeded on convergence.
    assert h.superseded.results and h.superseded.results[-1].success is True


def test_split_fails_closed_on_real_source_superseded_reindex_failure_then_converges(
    tmp_path: Path,
) -> None:
    """Codex r4 BLOCKER (crux): a REAL ``StoryMdExportResult(success=False)`` from
    the SOURCE superseded reindex channel must FAIL CLOSED — not return 0/success.

    The source re-export (step 7) hits a real ``VectorDbError`` -> the production
    ``export_story_md`` RETURNS ``success=False``. ``mark_superseded`` must
    propagate that real failure (raise) instead of returning 0, so the split
    never finalizes with the source left un-indexed. The fence stays
    committed-but-unfinalized; once indexing succeeds, a rerun CONVERGES.
    """
    h = _build_real_export_harness(tmp_path)
    plan = _plan(rebinding=False)

    # The SOURCE re-export at step 7 hits a real VectorDbError -> success=False.
    h.index.fail_ids.add("AK3-001")

    with pytest.raises(StorySplitError, match="source superseded re-export"):
        h.split_service.split_story(_request(plan))

    # The source reindex really returned success=False (real channel), and
    # mark_superseded propagated it (raised) instead of reporting 0/success.
    assert h.superseded.results and h.superseded.results[-1].success is False

    # FAIL CLOSED: fence committed but NOT finalized — no silent finalize even
    # though successors were created + the source was cancelled mid-sequence.
    fence = h.cp_state.operations[_real_export_split_id()]
    assert fence.status == "committed"
    assert "successor_ids" not in fence.response_payload
    assert h.closure_calls == []

    # Make the source reindex succeed; a rerun RESUMES and CONVERGES exactly once.
    h.index.fail_ids.clear()
    result = h.split_service.split_story(_request(plan))
    assert result.resumed is True
    source = h.story_service.get_story("AK3-001")
    assert source is not None and source.status is StoryStatus.CANCELLED
    assert tuple(source.split_successors) == result.successor_ids
    assert h.superseded.results[-1].success is True
    stories = [s.story_display_id for s in h.story_service.list_stories("ak3")]
    assert len(stories) == 3 and stories.count("AK3-001") == 1


def test_split_stays_fail_closed_on_persistent_real_export_failure(
    tmp_path: Path,
) -> None:
    """A PERSISTENT ``success=False`` never converges to a silent finalize.

    The successor export fails on EVERY run (the VectorDbError is never cleared):
    each rerun resumes and re-attempts the export, hits the same real
    ``success=False`` and fails closed again. The fence is never finalized, the
    source is never Cancelled — there is no silent success on rerun.
    """
    h = _build_real_export_harness(tmp_path)
    plan = _plan(rebinding=False)
    h.index.fail_first_non_source = True  # persistent: never cleared

    for _ in range(2):
        with pytest.raises(StorySplitError, match="successor story.md export"):
            h.split_service.split_story(_request(plan))
        source = h.story_service.get_story("AK3-001")
        assert source is not None and source.status is StoryStatus.IN_PROGRESS
        fence = h.cp_state.operations[_real_export_split_id()]
        assert fence.status == "committed"
        assert "successor_ids" not in fence.response_payload
        assert h.closure_calls == []
