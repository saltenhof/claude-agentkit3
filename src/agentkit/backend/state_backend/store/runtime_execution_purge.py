"""Coordinating Runtime-Execution-Purge port (AG3-109, FK-53 §53.7.5).

This module hosts the *coordinating* purge boundary for the Runtime-Execution
persistence subdomain. It lives under the **registered** boundary
``agentkit.backend.state_backend.store`` (an adapter that may import component groups —
``architecture-conformance/entities.md``), NOT under the unregistered physical
path ``agentkit.backend.phase_state_store``.

Design (PO decision D3, story §2.1.2, AK 5):

* The per-owner purge is executed by the owner APIs in
  :mod:`agentkit.backend.state_backend owner modules` (SQL lives in the driver helper
  ``sqlite_store`` / ``postgres_store``). This port only *orchestrates* those
  owner operations bundled from ``(project_key, story_id, run_id)``. It issues
  **no** cross-BC SQL of its own — there is no God-Purge.
* The result type is runtime-specific (:class:`RuntimeExecutionPurgeResult`):
  a ``domain -> deleted rows`` map. The projection-specific
  ``telemetry.projection_accessor.PurgeResult`` (FK-69 ``ProjectionKind``) is
  deliberately NOT reused (story HIGH-1).

Physical §1.3 mapping (code is ground truth; the FK-18/FK-53 naming drift —
``attempt_records`` -> ``attempts``, ``node_executions`` ->
``node_execution_ledgers``, ``artifact_records`` -> ``artifact_envelopes`` — is a
**doc-only** follow-up owned by FK-18-Doc, NOT renamed here, and phantom tables
are NEVER created/referenced):

================================  =========================  ============================
§53.6.2 entity                    Runtime-purge domain       Real table
================================  =========================  ============================
FlowExecution                     ``flow_executions``        ``flow_executions``
NodeExecution(Ledger)             ``node_execution_ledgers`` ``node_execution_ledgers``
AttemptRecord                     ``attempts``               ``attempts``
OverrideRecord                    ``override_records``       ``override_records``
GuardDecision                     ``guard_decisions``        ``guard_decisions``
VerifyDecision (governance rt.)   ``decision_records``       ``decision_records`` (story-keyed)
canonical PhaseState              ``phase_states``           ``phase_states`` (runtime)
PhaseState snapshot (per phase)   ``phase_snapshots``        ``phase_snapshots`` (story-keyed)
ExecutionEvent                    ``execution_events``       ``execution_events``
run-bound ArtifactRecord          ``artifact_envelopes``     ``artifact_envelopes`` (run-bound)
================================  =========================  ============================

Second-QA closure (review 2026-06-12, FK-53 §53.7.5 rule): ``phase_snapshots``
and ``decision_records`` are the in-code persistence companions of the §53.6.2
``PhaseState`` / governance-runtime entities and are written by THIS owner facade
(``save_phase_snapshot`` / ``record_verify_decision``). Both are story-keyed
(no ``run_id`` column in the canonical SQLite schema) and are read story-keyed by
guard/gate paths (``backend_has_completed_snapshot`` feeds Integrity-Gate Dim 2;
``load_latest_verify_decision`` picks ``MAX(attempt_nr)`` story-wide — on
Postgres with an explicit story-wide fallback). Leaving them behind would let a
purged run's objects influence a later restart/resume/guard decision — exactly
what the §53.7.5 rule forbids — so they are part of the runtime purge surface.

The read-model ``phase_state_projection`` is OUT OF SCOPE (it already has its own
``purge_run`` and belongs to the read-model/analytics purge domain, story §2.2).

Idempotency (FK-53 §53.9.1): each owner purge is convergent (delete-if-present,
ignore-if-gone). A second call with the same ``(project_key, story_id, run_id)``
deletes zero additional rows without error. A hard error is raised only on real
infra/permission problems (propagated from the driver) — and fail-closed on a
missing ``project_key`` / ``story_id`` / ``run_id`` scope.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.backend.state_backend.artifact_catalog_store import purge_run_bound_artifact_envelopes
from agentkit.backend.state_backend.governance_runtime_store import purge_guard_decisions
from agentkit.backend.state_backend.pipeline_runtime_store import (
    count_runtime_execution_residue,
    purge_attempts,
    purge_flow_executions,
    purge_node_execution_ledgers,
    purge_override_records,
    purge_phase_snapshots,
    purge_phase_states,
)
from agentkit.backend.state_backend.telemetry_event_store import purge_execution_events
from agentkit.backend.state_backend.verify_artifact_store import purge_decision_records

if TYPE_CHECKING:
    from pathlib import Path


# Stable order of the Runtime-Execution purge domains. The keys are the real
# table names (code is ground truth, §1.3), used verbatim as result-map keys.
RUNTIME_EXECUTION_PURGE_DOMAINS: tuple[str, ...] = (
    "flow_executions",
    "node_execution_ledgers",
    "attempts",
    "override_records",
    "guard_decisions",
    "decision_records",
    "phase_states",
    "phase_snapshots",
    "execution_events",
    "artifact_envelopes",
)


@dataclass(frozen=True)
class RuntimeExecutionPurgeResult:
    """Result of a coordinated Runtime-Execution purge (story §2.1.2).

    Runtime-specific result type — deliberately distinct from the FK-69
    projection ``PurgeResult`` (``ProjectionKind``-keyed). The map is keyed by
    the real Runtime-Execution table name (``flow_executions``, ``attempts``,
    canonical ``phase_states``, run-bound ``artifact_envelopes`` …, §1.3).

    Attributes:
        purged_rows: Number of deleted rows per Runtime-Execution domain. Every
            domain in :data:`RUNTIME_EXECUTION_PURGE_DOMAINS` is present (zero
            when nothing was deleted — idempotent re-run / never-written). The
            field is required so the documented every-domain-present invariant
            cannot be silently bypassed by a defaulted empty map.
    """

    purged_rows: dict[str, int]

    @property
    def total_purged(self) -> int:
        """Sum of all deleted rows across the Runtime-Execution domains."""

        return sum(self.purged_rows.values())


@dataclass(frozen=True)
class RuntimeExecutionResidueResult:
    """Result of a Runtime-Residue check (story §2.1.4, building block).

    Attributes:
        residue_rows: Remaining rows per Runtime-Execution domain after a purge.
        is_clean: ``True`` iff no Runtime-Execution residue remains for the run.
    """

    residue_rows: dict[str, int]

    @property
    def is_clean(self) -> bool:
        """Whether the run is free of Runtime-Execution residue (fail-closed)."""

        return all(count == 0 for count in self.residue_rows.values())


def _validate_scope(project_key: str, story_id: str, run_id: str) -> None:
    """Fail closed on an incomplete purge scope (story §3 negative path)."""

    missing = [
        name
        for name, value in (
            ("project_key", project_key),
            ("story_id", story_id),
            ("run_id", run_id),
        )
        if not value
    ]
    if missing:
        raise ValueError(
            "Runtime-Execution purge requires a complete scope; missing/empty: "
            + ", ".join(missing),
        )


class RuntimeExecutionPurgePort:
    """Coordinating port that bundles the per-owner Runtime-Execution purges.

    The consumer is ``story-lifecycle`` (``StoryResetService``, AG3-071, §53.7.5)
    — NOT built here. This port is constructed via the production composition
    root (``bootstrap.composition_root.build_runtime_execution_purge_port``) so a
    real caller can drive it through the canonical ``state_backend.store``
    assembly.

    Args:
        store_dir: State-backend base directory (the story dir for SQLite;
            ignored by the Postgres backend, which resolves the global store).
    """

    def __init__(self, store_dir: Path) -> None:
        self._store_dir = store_dir

    def purge_run(
        self,
        project_key: str,
        story_id: str,
        run_id: str,
    ) -> RuntimeExecutionPurgeResult:
        """Purge all Runtime-Execution domains for one run, bundled per owner.

        Calls the owner-purge APIs in a fixed order and aggregates the
        per-domain deleted row counts. Idempotent (FK-53 §53.9.1): a repeated
        call returns zero additional deletions without error.

        Args:
            project_key: Tenant/project scope (validated; ``attempts``,
                ``phase_states``, ``phase_snapshots``, ``decision_records`` and
                ``artifact_envelopes`` carry no ``project_key`` purge predicate,
                so the scope is enforced here, not as a column predicate).
            story_id: Story display id.
            run_id: Run correlation id being reset.

        Returns:
            :class:`RuntimeExecutionPurgeResult` with one entry per
            :data:`RUNTIME_EXECUTION_PURGE_DOMAINS` domain.

        Raises:
            ValueError: When the purge scope is incomplete (fail-closed).
        """
        _validate_scope(project_key, story_id, run_id)
        store_dir = self._store_dir
        purged: dict[str, int] = {
            "flow_executions": purge_flow_executions(
                store_dir, project_key, story_id, run_id
            ),
            "node_execution_ledgers": purge_node_execution_ledgers(
                store_dir, project_key, story_id, run_id
            ),
            "attempts": purge_attempts(store_dir, story_id, run_id),
            "override_records": purge_override_records(
                store_dir, project_key, story_id, run_id
            ),
            "guard_decisions": purge_guard_decisions(
                store_dir, project_key, story_id, run_id
            ),
            "decision_records": purge_decision_records(store_dir, story_id),
            "phase_states": purge_phase_states(store_dir, story_id),
            "phase_snapshots": purge_phase_snapshots(store_dir, story_id),
            "execution_events": purge_execution_events(
                store_dir, project_key, story_id, run_id
            ),
            "artifact_envelopes": purge_run_bound_artifact_envelopes(
                store_dir, story_id, run_id
            ),
        }
        return RuntimeExecutionPurgeResult(purged_rows=purged)


class RuntimeExecutionResidueProbe:
    """Fail-closed Runtime-Residue verify building block (story §2.1.4).

    Confirms that NO Runtime-Execution residue of the listed entities remains for
    a ``run_id`` (FK-53 §53.7.5 rule: no leftover object may influence a later
    restart/resume/guard decision). This is the **Runtime-Residue** fragment only
    — AG3-071 composes it into the full ``verify_reset_clean_state`` (which also
    covers read-models, analytics, locks, workspace; §53.8/§53.10, MED-7).

    Args:
        store_dir: State-backend base directory (story dir for SQLite).
    """

    def __init__(self, store_dir: Path) -> None:
        self._store_dir = store_dir

    def check_run(
        self,
        project_key: str,
        story_id: str,
        run_id: str,
    ) -> RuntimeExecutionResidueResult:
        """Return the residue result for the run scope (fail-closed on scope).

        Args:
            project_key: Tenant/project scope (validated).
            story_id: Story display id.
            run_id: Run correlation id.

        Returns:
            :class:`RuntimeExecutionResidueResult`; ``is_clean`` is ``True`` only
            when every Runtime-Execution domain has zero remaining rows.

        Raises:
            ValueError: When the scope is incomplete (fail-closed).
        """
        _validate_scope(project_key, story_id, run_id)
        residue = count_runtime_execution_residue(
            self._store_dir, project_key, story_id, run_id
        )
        return RuntimeExecutionResidueResult(residue_rows=residue)


__all__ = [
    "RUNTIME_EXECUTION_PURGE_DOMAINS",
    "RuntimeExecutionPurgePort",
    "RuntimeExecutionPurgeResult",
    "RuntimeExecutionResidueProbe",
    "RuntimeExecutionResidueResult",
]
