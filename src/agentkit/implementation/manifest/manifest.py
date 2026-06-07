"""WorkerManifest — the worker's technical end-of-implementation declaration.

FK-26 §26.8.2: the worker ends the implementation with exactly one of three
status values. ``BLOCKED`` is the professional-escalation exit (FK-26 §26.11.2,
REF-042) and carries mandatory blocker fields. This module is the typed,
fail-closed model + a deterministic validator that enforces the BLOCKED
required-field contract — the SINGLE source of truth for the manifest schema.

The validator enforces the three orchestrator-facing BLOCKED fields the
ImplementationPhaseHandler needs to escalate (``blocking_category``,
``blocking_issue``, ``recommended_next_action``; AG3-044 §2.1.4). The richer
FK-26 §26.8.2 BLOCKED payload (``attempted_remediations``,
``partial_work_summary``, ``safe_to_snapshot_commit``) is accepted as optional
typed fields so a fuller manifest round-trips without a second truth.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agentkit.core_types import BlockingCategory


class WorkerManifestStatus(StrEnum):
    """The three worker end-of-implementation status values (FK-26 §26.8.2).

    Attributes:
        COMPLETED: All ACs addressed, build and tests green.
        COMPLETED_WITH_ISSUES: ACs addressed with documented known limitations.
        BLOCKED: Unresolvable constraint collision — the worker escalates
            instead of looping (FK-26 §26.11.2, REF-042). Requires the
            mandatory blocker fields (validated below).
    """

    COMPLETED = "completed"
    COMPLETED_WITH_ISSUES = "completed_with_issues"
    BLOCKED = "blocked"


class AttemptedRemediation(BaseModel):
    """One worker remediation attempt recorded on a BLOCKED manifest.

    FK-26 §26.8.2: ``attempted_remediations`` is an array of ``{approach,
    result}`` documenting what the worker tried and why it failed.

    Attributes:
        approach: What the worker tried.
        result: Why it did not resolve the blocker.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    approach: str = Field(min_length=1)
    result: str = Field(min_length=1)


class WorkerManifest(BaseModel):
    """Typed worker-manifest (FK-26 §26.8.2), persisted as ``worker-manifest.json``.

    Frozen + ``extra="forbid"``: an unknown key or a missing BLOCKED field is a
    fail-closed schema violation, never silently tolerated (CLAUDE.md
    FAIL-CLOSED). The BLOCKED required-field rule is enforced in the model
    validator so an invalid BLOCKED manifest can never be constructed.

    Attributes:
        story_id: Story display id (e.g. ``AG3-044``).
        run_id: Run correlation id.
        status: One of the three :class:`WorkerManifestStatus` values.
        completed_at: UTC-aware completion timestamp.
        commit_sha: HEAD commit of the worker's work (when committed).
        files_changed: Declared changed files (Structural manifest-claims check
            consumes this; FK-27 §27.4.1).
        tests_added: Declared added tests.
        acceptance_criteria_status: Per-AC status, one of the canonical
            ``ACStatus`` values (FK-26 §26.8.2). Mandatory for the COMPLETED
            states.
        blocking_category: BLOCKED only — the blocker classification.
        blocking_issue: BLOCKED only — human-readable blocker description.
        recommended_next_action: BLOCKED only — recommendation to the orchestrator.
        attempted_remediations: BLOCKED only — what was tried (>= 1 entry,
            FK-26 §26.8.2).
        partial_work_summary: BLOCKED only — what was already finished.
        safe_to_snapshot_commit: BLOCKED only — whether the worktree can be
            snapshot-committed.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    story_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    status: WorkerManifestStatus
    completed_at: datetime
    commit_sha: str | None = None
    files_changed: list[str] = Field(default_factory=list)
    tests_added: list[str] = Field(default_factory=list)
    acceptance_criteria_status: dict[str, str] = Field(default_factory=dict)
    # BLOCKED-only fields (FK-26 §26.8.2). Optional at the type level; the model
    # validator enforces the BLOCKED required-set (fail-closed).
    blocking_category: BlockingCategory | None = None
    blocking_issue: str | None = None
    recommended_next_action: str | None = None
    attempted_remediations: list[AttemptedRemediation] = Field(default_factory=list)
    partial_work_summary: str | None = None
    safe_to_snapshot_commit: bool | None = None

    @model_validator(mode="after")
    def _validate_blocked_required_fields(self) -> WorkerManifest:
        """Enforce the BLOCKED required-field contract (AG3-044 §2.1.4, fail-closed).

        FK-26 §26.8.2 / AG3-044 §2.1.4: a ``BLOCKED`` manifest MUST carry
        ``blocking_category``, ``blocking_issue`` and ``recommended_next_action``.
        The ImplementationPhaseHandler escalates using exactly these fields, so a
        BLOCKED manifest missing any of them is a hard error (never a silent
        degrade to a resumable in-progress state — invariant
        ``worker_blocked_escalates``).

        Returns:
            ``self`` when valid.

        Raises:
            ValueError: When ``status == BLOCKED`` and any required blocker field
                is unset / blank.
        """
        if self.status is not WorkerManifestStatus.BLOCKED:
            return self
        missing: list[str] = []
        if self.blocking_category is None:
            missing.append("blocking_category")
        if not (self.blocking_issue and self.blocking_issue.strip()):
            missing.append("blocking_issue")
        if not (
            self.recommended_next_action and self.recommended_next_action.strip()
        ):
            missing.append("recommended_next_action")
        if missing:
            raise ValueError(
                "BLOCKED worker-manifest requires non-empty "
                f"{missing} (FK-26 §26.8.2 / AG3-044 §2.1.4); "
                "a BLOCKED worker MUST escalate with blocker details "
                "(invariant worker_blocked_escalates)",
            )
        return self


__all__ = [
    "AttemptedRemediation",
    "WorkerManifest",
    "WorkerManifestStatus",
]
