"""ProjectionAccessor: central DB owner of all FK-69 read models.

Central write and read boundary for projection data (FK-69 §69.3-§69.4).
All FK-69 write sites MUST go through this accessor; no BC may write
directly into the FK-69 tables (ZERO DEBT, SINGLE SOURCE OF TRUTH).

Architecture Conformance (AC#7):
- ProjectionAccessor imports NO concrete implementations from
  ``agentkit.backend.state_backend owner modules`` or ``state_backend.store.*``.
- It depends exclusively on injected repository protocols
  (``ProjectionRepositories`` via Dependency Injection).
- Wired up in ``agentkit.backend.bootstrap.composition_root.build_projection_accessor``.

Sources:
- FK-69 §69.3 -- table scope (exactly 7 tables)
- FK-69 §69.4 -- write ownership
- FK-69 §69.10.1 -- reset-purge rule (run_id-scoped)
- FK-69 §69.11.5 -- consistency rule: no FK-69 state after reset
- FK-29 §29.6 -- story_metrics: PostMergeFinalization is schema owner + writer
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

from agentkit.backend.telemetry.errors import (
    FCIncidentWriteViaDedicatedMethodError,
    ProjectionKindNotAccessorOwnedError,
    ProjectionRecordTypeMismatchError,
)
from agentkit.backend.verify_system.stage_registry.records import (
    QACheckOutcomeRecord,
    QAFindingRecord,
    QAStageResultRecord,
)

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

    from agentkit.backend.failure_corpus.incident import IncidentDraft
    from agentkit.backend.failure_corpus.types import IncidentId
    from agentkit.backend.state_backend.store.telemetry_projection_repository_common import (
        ProjectionRepositories,
    )
    from agentkit.backend.task_management.models import Task, TaskLink, TaskListFilter, TaskTargetKind
    from agentkit.backend.telemetry.projection_records import ProjectionRecord
    from agentkit.backend.telemetry.risk_window.normalized_event import NormalizedEvent
    from agentkit.backend.verify_system.protocols import LayerResult


# ---------------------------------------------------------------------------
# ProjectionKind (FK-69 §69.3 — exactly 7 tables)
# ---------------------------------------------------------------------------


class ProjectionKind(StrEnum):
    """Canonical enum values for all FK-69 tables.

    FK-69 §69.3/§69.4 authorizes 8 tables (7 original + qa_check_outcomes
    added in AG3-108). WORKFLOW_METRICS is an FK-68 table (telemetry/eventing),
    not an FK-69 read model, and does not belong here.
    """

    QA_STAGE_RESULTS = "qa_stage_results"
    QA_FINDINGS = "qa_findings"
    QA_CHECK_OUTCOMES = "qa_check_outcomes"
    STORY_METRICS = "story_metrics"
    PHASE_STATE_PROJECTION = "phase_state_projection"
    FC_INCIDENTS = "fc_incidents"
    FC_PATTERNS = "fc_patterns"
    FC_CHECK_PROPOSALS = "fc_check_proposals"


# ---------------------------------------------------------------------------
# Write/read ownership (FK-69 §69.4) — explicit contract instead of dead enum values
# ---------------------------------------------------------------------------
#
# FK-69 §69.3 requires all 7 table names in ``ProjectionKind``. The
# write/read ownership (§69.4), however, does NOT lie entirely with the accessor:
# the accessor owns the QA, story_metrics and (since AG3-028) FC_INCIDENTS
# kinds. The remaining kinds are deliberately published (FK-69 §69.3) but
# externally owned. The accessor rejects them fail-closed with
# ``ProjectionKindNotAccessorOwnedError`` and names the owner — not a
# ``NotImplementedError`` as "half built".

_ACCESSOR_OWNED_KINDS: frozenset[ProjectionKind] = frozenset(
    {
        ProjectionKind.QA_STAGE_RESULTS,
        ProjectionKind.QA_FINDINGS,
        # AG3-108: qa_check_outcomes is a verify-system-owned FK-69 read model;
        # the accessor is its DB owner (FK-69 §69.15).
        ProjectionKind.QA_CHECK_OUTCOMES,
        ProjectionKind.STORY_METRICS,
        # AG3-028 CONFLICT-2: fc_incidents is accessor-owned after this story
        # (FK-69 §69.9/§69.14 route fc_* explicitly via write_projection). The
        # fc_incidents repo adapter is injected on the accessor side.
        ProjectionKind.FC_INCIDENTS,
        # AG3-078 (FK-41 §41.5/§41.6): FC_PATTERNS and FC_CHECK_PROPOSALS ownership
        # wired. PatternPromotion/CheckFactory are the producer stories.
        # Read/write enabled; purge_run NOT extended (FK-41 §41.3.3/FK-69 §69.9).
        ProjectionKind.FC_PATTERNS,
        ProjectionKind.FC_CHECK_PROPOSALS,
    }
)

# Externally owned kinds: published in ProjectionKind (FK-69 §69.3), but the
# data path belongs by design to another writer / another story.
_EXTERNALLY_OWNED_KINDS: dict[ProjectionKind, str] = {
    ProjectionKind.PHASE_STATE_PROJECTION: ("pipeline_engine.PhaseExecutor (FK-69 §69.4 Write-Ownership)"),
}


# ---------------------------------------------------------------------------
# ProjectionFilter
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProjectionFilter:
    """Optional filter parameters for ``read_projection``.

    All fields are optional. Only set fields are applied as WHERE conditions.
    At least ``story_id`` or ``run_id`` is expected for meaningful queries
    (FAIL-CLOSED is NOT checked on filter completeness; that is the caller's
    responsibility).

    Attributes:
        project_key: Project key (mandatory on all FK-69 tables).
        story_id: Story-ID filter.
        run_id: Run-ID filter (recommended for run-scoped queries).
        attempt_no: Attempt number (only relevant for QA tables).
        stage_id: Stage-ID (only relevant for QA tables).
        check_id: Exact-match filter on the executed-check identifier
            (only relevant for ``qa_check_outcomes``; AG3-108).
        since_days: UTC window filter: ``occurred_at >= now - since_days``
            days. Only relevant for ``qa_check_outcomes``; 0 means today
            only; negative values are treated as 0 (AG3-108).
            Callers that need reproducible tests MUST inject ``_now`` via
            the ``QACheckOutcomesRepository.read`` time parameter instead
            of relying on ``since_days`` alone.
        check_proposal_ref: Exact-match filter on the FC-check proposal reference
            (``CHK-NNNN``); only relevant for ``qa_check_outcomes``; added in
            AG3-078.
    """

    project_key: str | None = None
    story_id: str | None = None
    run_id: str | None = None
    attempt_no: int | None = None
    stage_id: str | None = None
    check_id: str | None = None
    since_days: int | None = None
    check_proposal_ref: str | None = None


# ---------------------------------------------------------------------------
# PurgeResult
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PurgeResult:
    """Result of a ``purge_run`` operation.

    Attributes:
        purged_rows: Number of deleted rows per ``ProjectionKind``.
            Only tables with an active write path are counted
            (fc_incidents included since AG3-028; fc_patterns/fc_check_proposals
            follow with their producer stories).
        errors: Error messages on partial failures. ONLY the best-effort purge
            of ``phase_state_projection`` (documented legacy-schema special case)
            collects here; mandatory tables (qa_stage_results, qa_findings,
            story_metrics, fc_incidents) escalate their purge errors hard
            (Codex-r1, FK-69 §69.11.5). An empty list means: phase_state_projection
            was also purged successfully.
        purged_guard_counters: Number of ``guard_invocation_counters`` rows drained
            by the full Story-Reset (AG3-081, FK-61 §61.4.3 Trigger 4). The counter
            scratchpad is owned by the KPI fact-store and keyed by
            ``(project_key, story_id, ...)`` without a ``run_id`` column, so it is
            tracked separately from the run-scoped FK-69 ``purged_rows`` map.
    """

    purged_rows: dict[ProjectionKind, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    purged_guard_counters: int = 0


# ---------------------------------------------------------------------------
# ProjectionAccessor
# ---------------------------------------------------------------------------


def _build_kind_to_record_type() -> dict[ProjectionKind, type]:
    """Build the mapping ProjectionKind -> allowed record type (FK-69 §69.4).

    Lazy initialization: avoids circular imports between telemetry and
    closure during package init. StoryMetricsRecord is imported only on first
    call via the exposed closure top-surface (AC001: no direct access to the
    internal submodule post_merge_finalization.records).

    AG3-028 CONFLICT-2: ``Incident`` is the fc_incidents record type. It lives
    in the leaf module ``failure_corpus.incident`` (imports only core_types +
    failure_corpus.types, NOT telemetry) — analogous to
    ``verify_system.stage_registry.records``. This produces no cycle
    ``failure_corpus`` <-> ``telemetry``.

    AG3-078: FC_PATTERNS -> FailurePatternRecord, FC_CHECK_PROPOSALS -> CheckProposalRecord.
    Both live in failure_corpus.pattern / failure_corpus.check_proposal (leaf modules,
    import only core_types — no import cycle with telemetry).
    """
    from agentkit.backend.closure import StoryMetricsRecord as _StoryMetricsRecord
    from agentkit.backend.failure_corpus.check_proposal import CheckProposalRecord as _CheckProposalRecord
    from agentkit.backend.failure_corpus.incident import Incident as _Incident
    from agentkit.backend.failure_corpus.pattern import FailurePatternRecord as _FailurePatternRecord

    return {
        ProjectionKind.QA_STAGE_RESULTS: QAStageResultRecord,
        ProjectionKind.QA_FINDINGS: QAFindingRecord,
        ProjectionKind.QA_CHECK_OUTCOMES: QACheckOutcomeRecord,
        ProjectionKind.STORY_METRICS: _StoryMetricsRecord,
        ProjectionKind.FC_INCIDENTS: _Incident,
        # AG3-078: FC_PATTERNS and FC_CHECK_PROPOSALS now owned by the accessor.
        ProjectionKind.FC_PATTERNS: _FailurePatternRecord,
        ProjectionKind.FC_CHECK_PROPOSALS: _CheckProposalRecord,
        # PHASE_STATE_PROJECTION has no BC-owned record type;
        # write owner is pipeline_engine.PhaseExecutor (not via the accessor).
    }


# Mapping: ProjectionKind -> allowed record type (FK-69 §69.4)
# Lazy via _build_kind_to_record_type() on first access (anti-circular-import).
_KIND_TO_RECORD_TYPE: dict[ProjectionKind, type] | None = None


def _get_kind_to_record_type() -> dict[ProjectionKind, type]:
    """Return the mapping; initialize it on first call."""
    global _KIND_TO_RECORD_TYPE  # noqa: PLW0603
    if _KIND_TO_RECORD_TYPE is None:
        _KIND_TO_RECORD_TYPE = _build_kind_to_record_type()
    return _KIND_TO_RECORD_TYPE


class ProjectionAccessor:
    """DB owner of all FK-69 read models and fc_* tables (FK-69 §69.3).

    Central write and read boundary for projection data. All FK-69 writers
    MUST go through ``write_projection``; no BC writes directly into
    FK-69 tables.

    Dependency Injection via the ``ProjectionRepositories`` dataclass: the
    accessor imports NO concrete repository implementations (AC#7).

    Args:
        repositories: Bundle of all FK-69 repository adapters.
    """

    def __init__(self, repositories: ProjectionRepositories) -> None:
        self._repos = repositories

    @staticmethod
    def is_accessor_owned(projection_kind: ProjectionKind) -> bool:
        """True if the accessor owns the write/read path for ``projection_kind``.

        Explicit FK-69 §69.4 contract: QA, story_metrics, FC_INCIDENTS (AG3-028),
        FC_PATTERNS and FC_CHECK_PROPOSALS (AG3-078) are accessor-owned. Only
        PHASE_STATE_PROJECTION is externally owned (PIPELINE_ENGINE.PhaseExecutor)
        and is rejected by ``write_projection``/``read_projection`` fail-closed with
        ``ProjectionKindNotAccessorOwnedError``.

        Args:
            projection_kind: The FK-69 table family to check.

        Returns:
            ``True`` for accessor-owned kinds, otherwise ``False``.
        """
        return projection_kind in _ACCESSOR_OWNED_KINDS

    def write_projection(
        self,
        projection_kind: ProjectionKind,
        record: ProjectionRecord,
    ) -> None:
        """Persist a projection record via the responsible repository adapter.

        Validates: record type must match ``projection_kind``.
        FAIL-CLOSED: wrong record type -> ``ProjectionRecordTypeMismatchError``.

        Args:
            projection_kind: The FK-69 table family.
            record: The record to persist. Type must match ``projection_kind``
                (FK-69 §69.4).

        Raises:
            ProjectionKindNotAccessorOwnedError: For externally owned
                ProjectionKinds (PHASE_STATE_PROJECTION). Subclass of
                ``NotImplementedError``; names the owner (FK-69 §69.4).
            ProjectionRecordTypeMismatchError: When ``type(record)`` does not
                match the expected type for ``projection_kind``.
        """
        if projection_kind not in _ACCESSOR_OWNED_KINDS:
            raise ProjectionKindNotAccessorOwnedError(
                kind=projection_kind,
                owner=_EXTERNALLY_OWNED_KINDS.get(projection_kind, "unknown (no FK-69 owner registered)"),
            )

        # AG3-028 Codex-r1: fc_incidents is written via the dedicated
        # record_fc_incident method (FK-41 §41.3.1 allocates the
        # FC-YYYY-NNNN id in the transaction and MUST return it). The
        # generic write_projection API (-> None) cannot return the id.
        if projection_kind is ProjectionKind.FC_INCIDENTS:
            raise FCIncidentWriteViaDedicatedMethodError

        kind_map = _get_kind_to_record_type()
        expected_type = kind_map[projection_kind]

        if not isinstance(record, expected_type):
            raise ProjectionRecordTypeMismatchError(
                kind=projection_kind,
                expected=expected_type,
                received=type(record),
            )

        if projection_kind is ProjectionKind.QA_STAGE_RESULTS:
            assert isinstance(record, QAStageResultRecord)
            self._repos.qa_stage_results.write(record)
        elif projection_kind is ProjectionKind.QA_FINDINGS:
            assert isinstance(record, QAFindingRecord)
            self._repos.qa_findings.write(record)
        elif projection_kind is ProjectionKind.QA_CHECK_OUTCOMES:
            assert isinstance(record, QACheckOutcomeRecord)
            self._repos.qa_check_outcomes.write(record)
        elif projection_kind is ProjectionKind.STORY_METRICS:
            # StoryMetricsRecord is runtime-lazy loaded (anti-circular-import).
            # The isinstance check ran above via _get_kind_to_record_type();
            # the Any-cast sidesteps mypy narrowing without requiring a runtime import.
            self._repos.story_metrics.write(record)  # type: ignore[arg-type]
        elif projection_kind is ProjectionKind.FC_PATTERNS:
            # AG3-078: FC_PATTERNS now accessor-owned (FK-41 §41.5/§41.6).
            # FailurePatternRecord is lazy-loaded (anti-circular-import).
            self._repos.fc_patterns.save(record)  # type: ignore[arg-type]
        elif projection_kind is ProjectionKind.FC_CHECK_PROPOSALS:
            # AG3-078: FC_CHECK_PROPOSALS now accessor-owned (FK-41 §41.5/§41.6).
            # CheckProposalRecord is lazy-loaded (anti-circular-import).
            self._repos.fc_check_proposals.save(record)  # type: ignore[arg-type]
        else:
            # FC_INCIDENTS is redirected fail-closed to record_fc_incident
            # above; all remaining kinds are covered by the
            # _KIND_TO_RECORD_TYPE check above.
            raise NotImplementedError(f"Unhandled ProjectionKind: {projection_kind!r}")

    def record_fc_incident(self, draft: IncidentDraft) -> IncidentId:
        """Persist an incident and return the allocated ``IncidentId``.

        Dedicated fc_incidents write path (FK-41 §41.3.1, AG3-028 Codex-r1):
        the ``FC-YYYY-NNNN`` id is allocated DB-side globally unique, gap-free
        per year inside the write transaction (analogous to the story_number
        allocator, AG3-050) and returned to the caller. Append-only.

        Args:
            draft: Normalized, not-yet-persisted incident (without id).

        Returns:
            The allocated ``IncidentId`` (``FC-YYYY-NNNN``).
        """
        return self._repos.fc_incidents.record_incident(draft)

    def record_task(self, task: Task) -> None:
        """Persist one task-management ``Task`` through the dedicated FK-77 port.

        This path is intentionally not a ``ProjectionKind``. FK-69 keeps the
        seven-value enum strict; task-management uses its own typed repository
        boundary while still being written through the accessor-owned state
        backend port.
        """
        from agentkit.backend.task_management.models import Task as _Task

        if not isinstance(task, _Task):
            raise ProjectionRecordTypeMismatchError(
                kind="tm_tasks",
                expected=_Task,
                received=type(task),
            )
        self._repos.tasks.write_task(task)

    def get_task(self, project_key: str, task_id: str) -> Task | None:
        """Load one task by project-scoped identity."""
        return self._repos.tasks.get_task(project_key, task_id)

    def list_tasks(
        self,
        project_key: str,
        *,
        filter: TaskListFilter | None = None,  # noqa: A002
    ) -> list[Task]:
        """List tasks within one explicit project partition."""
        return self._repos.tasks.list_tasks(project_key, filter=filter)

    def record_task_link(self, link: TaskLink) -> None:
        """Persist one task-management ``TaskLink`` through the dedicated FK-77 port."""
        from agentkit.backend.task_management.models import TaskLink as _TaskLink

        if not isinstance(link, _TaskLink):
            raise ProjectionRecordTypeMismatchError(
                kind="tm_task_links",
                expected=_TaskLink,
                received=type(link),
            )
        self._repos.tasks.write_task_link(link)

    def delete_task_link(self, link: TaskLink) -> bool:
        """Delete one task-management link through the dedicated FK-77 port."""
        from agentkit.backend.task_management.models import TaskLink as _TaskLink

        if not isinstance(link, _TaskLink):
            raise ProjectionRecordTypeMismatchError(
                kind="tm_task_links",
                expected=_TaskLink,
                received=type(link),
            )
        return self._repos.tasks.delete_task_link(link)

    def list_tasks_for_target(
        self,
        project_key: str,
        target_kind: TaskTargetKind,
        target_id: str,
    ) -> list[Task]:
        """List tasks linked to one target inside the explicit project partition."""
        return self._repos.tasks.list_tasks_for_target(project_key, target_kind, target_id)

    def list_task_links(self, project_key: str) -> list[TaskLink]:
        """List all task links within one explicit project partition (AG3-105/AC4)."""
        return self._repos.tasks.list_task_links(project_key)

    def story_target_exists(self, project_key: str, story_id: str) -> bool:
        """Return whether a project-scoped story target exists."""
        return self._repos.tasks.story_target_exists(project_key, story_id)

    @staticmethod
    def _require_project_key(project_key: str | None, *, kind_label: str, fk_ref: str) -> str:
        """Return the project key or raise (FAIL-CLOSED: project-bound reads).

        Hoisted out of :meth:`read_projection` so each project-bound branch is a
        single flat guard call instead of a nested ``if`` (keeps the dispatch
        below the cognitive-complexity ceiling, Sonar S3776).

        Raises:
            ValueError: If ``project_key`` is missing/empty.
        """
        if not project_key:
            raise ValueError(f"read_projection({kind_label}) requires ProjectionFilter.project_key ({fk_ref})")
        return project_key

    def read_projection(
        self,
        projection_kind: ProjectionKind,
        filter: ProjectionFilter,  # noqa: A002
        *,
        _now: datetime | None = None,
    ) -> list[ProjectionRecord]:
        """Read projection records, filtered, from the state backend.

        Args:
            projection_kind: The FK-69 table family.
            filter: Optional filter parameters (project_key, story_id, run_id, ...).
            _now: Optional injectable UTC clock for the ``since_days`` window
                (only relevant for ``QA_CHECK_OUTCOMES``). When ``None`` the
                repository defaults to ``datetime.now(UTC)``. Use this seam in
                tests to make the UTC boundary deterministic without reaching
                into private repository internals (AG3-108 ERROR 4).

        Returns:
            List of ``ProjectionRecord`` instances (empty when no matches).

        Raises:
            ProjectionKindNotAccessorOwnedError: For externally owned
                ProjectionKinds (PHASE_STATE_PROJECTION). Subclass of
                ``NotImplementedError``; names the owner (FK-69 §69.4).
        """
        if projection_kind is ProjectionKind.QA_STAGE_RESULTS:
            return list(
                self._repos.qa_stage_results.read(
                    project_key=filter.project_key,
                    story_id=filter.story_id,
                    run_id=filter.run_id,
                    attempt_no=filter.attempt_no,
                    stage_id=filter.stage_id,
                )
            )
        elif projection_kind is ProjectionKind.QA_FINDINGS:
            return list(
                self._repos.qa_findings.read(
                    project_key=filter.project_key,
                    story_id=filter.story_id,
                    run_id=filter.run_id,
                    attempt_no=filter.attempt_no,
                    stage_id=filter.stage_id,
                )
            )
        elif projection_kind is ProjectionKind.QA_CHECK_OUTCOMES:
            # AG3-108: project_key is mandatory for qa_check_outcomes
            # (FK-69 §69.2 rule 2 / §69.15.6 rule 7 fail-closed).
            project_key = self._require_project_key(
                filter.project_key,
                kind_label="QA_CHECK_OUTCOMES",
                fk_ref="FK-69 §69.15.6 rule 7: missing project_key is a hard error",
            )
            return list(
                self._repos.qa_check_outcomes.read(
                    project_key=project_key,
                    story_id=filter.story_id,
                    run_id=filter.run_id,
                    attempt_no=filter.attempt_no,
                    stage_id=filter.stage_id,
                    check_id=filter.check_id,
                    since_days=filter.since_days,
                    check_proposal_ref=filter.check_proposal_ref,
                    _now=_now,
                )
            )
        elif projection_kind is ProjectionKind.STORY_METRICS:
            return list(
                self._repos.story_metrics.read(
                    project_key=filter.project_key,
                    story_id=filter.story_id,
                    run_id=filter.run_id,
                )
            )
        elif projection_kind is ProjectionKind.FC_INCIDENTS:
            # AG3-028 CONFLICT-2: fc_incidents is accessor-owned. FK-41 §41.3.1:
            # queries are always project-bound -> project_key is mandatory
            # (FAIL-CLOSED; Codex-r1). If project_key is missing, the repo read
            # fails with ValueError instead of silently returning all projects.
            project_key = self._require_project_key(
                filter.project_key,
                kind_label="FC_INCIDENTS",
                fk_ref="FK-41 §41.3.1: queries are always project-bound",
            )
            return list(
                self._repos.fc_incidents.read(
                    project_key=project_key,
                    story_id=filter.story_id,
                    run_id=filter.run_id,
                )
            )
        elif projection_kind is ProjectionKind.FC_PATTERNS:
            # AG3-078: FC_PATTERNS now accessor-owned (FK-41 §41.5, read/write wired).
            # project_key is mandatory (FAIL-CLOSED, analogous to FC_INCIDENTS).
            project_key = self._require_project_key(
                filter.project_key,
                kind_label="FC_PATTERNS",
                fk_ref="FK-41 §41.3.2: queries are always project-bound",
            )
            return list(self._repos.fc_patterns.list_for_project(project_key))
        elif projection_kind is ProjectionKind.FC_CHECK_PROPOSALS:
            # AG3-078: FC_CHECK_PROPOSALS now accessor-owned (FK-41 §41.6, read/write wired).
            # project_key is mandatory (FAIL-CLOSED, analogous to FC_INCIDENTS).
            project_key = self._require_project_key(
                filter.project_key,
                kind_label="FC_CHECK_PROPOSALS",
                fk_ref="FK-41 §41.3.3: queries are always project-bound",
            )
            # List proposals for the project.
            # If pattern_ref filter provided (via story_id field), scope to that pattern.
            if filter.story_id is not None:
                return list(self._repos.fc_check_proposals.list_for_pattern(filter.story_id))
            # Single-query project scan — symmetric with fc_patterns (list_for_project).
            return list(self._repos.fc_check_proposals.list_for_project(project_key))
        # Externally owned kinds (PHASE_STATE_PROJECTION): fail-closed with owner naming.
        # phase_state reads run directly via facade.load_phase_state.
        raise ProjectionKindNotAccessorOwnedError(
            kind=projection_kind,
            owner=_EXTERNALLY_OWNED_KINDS.get(projection_kind, "unknown (no FK-69 owner registered)"),
        )

    def purge_run(
        self,
        project_key: str,
        story_id: str,
        run_id: str,
    ) -> PurgeResult:
        """Reset-purge: removes all FK-69 projection data for (project_key, story_id, run_id).

        FK-69 §69.10.1 reset rule: a full reset removes ALL FK-69 rows of the
        affected run_id. A filter trick in queries is invalid (FK-69 §69.10.1:
        "filtering out later in queries is not permitted").

        Reset-purge is run_id-scoped (FK-69 §69.10.1), not merely story_id-scoped.
        Signature: ``purge_run(project_key, story_id, run_id)``.
        Story AG3-035 §2.1.3/AK1/AK5 is aligned to this signature.

        AG3-028 CONFLICT-2 (FK-41 §41.3 / FK-69 §69.9): the full reset of a
        ``run_id`` now also actively removes all ``fc_incidents`` rows of that
        run (no filter trick). fc_patterns/fc_check_proposals follow with their
        producer stories (as long as those tables do not exist, there is nothing
        to purge there).

        Purge covers the tables whose repos/write paths exist:
        qa_stage_results, qa_findings, story_metrics, phase_state_projection,
        fc_incidents.

        AG3-081 (FK-61 §61.4.3 Trigger 4): a full Story-Reset additionally purges
        the story's ``guard_invocation_counters`` scratchpad through this ONE reset
        path (surfaced as ``PurgeResult.purged_guard_counters``). The counters are
        KPI-owned and keyed without a ``run_id`` column, so they are purged
        story-scoped (the ``fact_guard_period`` recompute is AG3-082).

        Args:
            project_key: Project key.
            story_id: Story-ID of the run being reset.
            run_id: Run-ID whose FK-69 rows are all actively deleted.

        Returns:
            ``PurgeResult`` with ``purged_rows`` (count per table) and
            ``errors`` (empty when all OK).
        """
        purged_rows: dict[ProjectionKind, int] = {}
        errors: list[str] = []

        # Mandatory tables (Codex-r1, AG3-028): qa_stage_results, qa_findings,
        # story_metrics and fc_incidents have a productive write path and a
        # bootstrapped schema. A purge error here is a real reset defect and must
        # NOT vanish in the blanket catch (FK-69 §69.10.1/§69.11.5: no FK-69
        # state after reset; no productive reset caller gates on errors==[]).
        # These errors escalate hard.
        purged_rows[ProjectionKind.QA_STAGE_RESULTS] = self._repos.qa_stage_results.purge_run(project_key, story_id, run_id)
        purged_rows[ProjectionKind.QA_FINDINGS] = self._repos.qa_findings.purge_run(project_key, story_id, run_id)
        # AG3-108: qa_check_outcomes is a mandatory FK-69 table; purge on reset.
        purged_rows[ProjectionKind.QA_CHECK_OUTCOMES] = self._repos.qa_check_outcomes.purge_run(project_key, story_id, run_id)
        purged_rows[ProjectionKind.STORY_METRICS] = self._repos.story_metrics.purge_run(project_key, story_id, run_id)
        purged_rows[ProjectionKind.FC_INCIDENTS] = self._repos.fc_incidents.purge_run(project_key, story_id, run_id)
        # AG3-037 (FK-68 §68.8): the run's risk-window rows are part of a full
        # reset. risk_window is an FK-68 telemetry read-model (NOT an FK-69
        # ProjectionKind, FK-69 §69.3), so it is purged here but not counted in
        # the FK-69 ProjectionKind-keyed purged_rows map.
        self._repos.risk_window.purge_run(project_key, story_id, run_id)

        # AG3-081 (FK-61 §61.4.3 Trigger 4): a full Story-Reset also purges the
        # story's guard-invocation counter scratchpad through the ONE reset path
        # (no parallel purge service). The counters are KPI-owned and keyed by
        # (project_key, story_id, ...) WITHOUT a run_id column, so the purge is
        # story-scoped. This is part of the mandatory reset (FK-69 §69.11.5: no
        # state may survive a full reset; the already-aggregated fact_guard_period
        # contributions are re-computed by AG3-082), so a failure escalates hard
        # like the mandatory FK-69 tables rather than degrading into errors[].
        purged_guard_counters = self._repos.guard_counter_purge.purge_story(project_key, story_id)

        # Best-effort ONLY for phase_state_projection: its legacy-schema variants
        # (missing project_key/run_id columns, not-guaranteed-bootstrapped table
        # in BC-isolated persistence views) are a documented special case
        # (FacadePhaseStateProjectionRepository._sqlite_purge). The error is
        # collected separately here instead of blocking the reset of the mandatory
        # tables — write owner is pipeline_engine.PhaseExecutor.
        try:
            purged_rows[ProjectionKind.PHASE_STATE_PROJECTION] = self._repos.phase_state_projection.purge_run(
                project_key, story_id, run_id
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"purge_run {ProjectionKind.PHASE_STATE_PROJECTION!r}: {type(exc).__name__}: {exc}")

        return PurgeResult(
            purged_rows=purged_rows,
            errors=errors,
            purged_guard_counters=purged_guard_counters,
        )

    def record_qa_layer_artifacts(
        self,
        story_dir: Path,
        *,
        layer_results: tuple[LayerResult, ...],
        attempt_nr: int,
        owner_session_id: str,
        expected_ownership_epoch: int,
        projection_dir: Path | None = None,
    ) -> tuple[str, ...]:
        """Business write entry point for the QA-layer batch (FK-69 §69.4, AK4).

        The ProjectionAccessor is the ONE business write boundary for the
        FK-69 QA read models (``qa_stage_results``, ``qa_findings``). The
        productive QA subflow (implementation/verify) MUST call this method
        instead of the ``state_backend`` facade directly -- otherwise a second
        operative truth arises past the accessor (SINGLE SOURCE OF TRUTH, AG3-035 #5).

        Atomicity: the transaction (qa_stage_results + qa_findings +
        artifact_records in ONE driver transaction incl. placeholder
        artifact_id replacement) stays encapsulated in the driver (FK-69 §69.4,
        finding D option i). The accessor delegates to the injected
        batch port (``ProjectionRepositories.qa_layer_batch``) and does not split
        the transaction. The port encapsulates the joint write of
        FK-69 QA rows and source artifact -- the accessor itself knows no
        ``artifact_records`` details (AC#7: no facade import in telemetry).

        Args:
            story_dir: Story working directory.
            layer_results: QA-layer results of this attempt.
            attempt_nr: Attempt number.
            owner_session_id: (AG3-144, FK-91 §91.1a Rule 15) The caller's
                early-captured active ``run_ownership_records.owner_session_id``
                snapshot (mirrors the AG3-142 regime-commit pattern);
                re-verified at commit time under ``SELECT ... FOR UPDATE``.
            expected_ownership_epoch: The caller's early-captured
                ``ownership_epoch`` snapshot, re-verified the same way.
            projection_dir: Optional projection directory (export).

        Returns:
            Tuple of the written artifact IDs (from the driver batch).

        Raises:
            OwnershipFenceViolationError: (AG3-142 reuse) When the story's
                active ownership record no longer admits this exact snapshot
                at commit time -- nothing written.
        """
        return self._repos.qa_layer_batch.persist_layer_artifacts(
            story_dir,
            layer_results=layer_results,
            attempt_nr=attempt_nr,
            owner_session_id=owner_session_id,
            expected_ownership_epoch=expected_ownership_epoch,
            projection_dir=projection_dir,
        )

    def record_risk_window_event(self, event: NormalizedEvent) -> None:
        """Persist one ``NormalizedEvent`` into the FK-68 §68.8 risk window.

        Dedicated risk-window write path (FK-68 §68.8.0: the sensor layer writes
        ``NormalizedEvent``s via the accessor). The Risk-Window is an FK-68
        telemetry-owned rolling-window read-model — NOT one of the seven FK-69
        ``ProjectionKind`` tables (FK-69 §69.3) — so it uses a dedicated method,
        analogous to ``record_fc_incident`` / ``record_qa_layer_artifacts``,
        instead of the generic ``write_projection``. Append-only.

        Args:
            event: The normalized risk-window event to append.
        """
        self._repos.risk_window.record(event)


__all__ = [
    "ProjectionAccessor",
    "ProjectionFilter",
    "ProjectionKind",
    "PurgeResult",
]
