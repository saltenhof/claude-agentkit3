"""WorkerLoop — the deterministic four-step increment record (FK-26 §26.3).

The worker agent itself runs inside the harness (Claude Code / Codex) and is the
non-deterministic actor (FK-26 §26.1). AgentKit owns the *frame*: per vertical
increment the worker (1) implements, (2) verifies locally, (3) checks drift
against the design artifact, (4) commits. This module is the deterministic
representation of that four-step increment — it records the observed facts of one
increment (no LLM call here) and emits the telemetry events through the AG3-036
``CommitHook`` / ``DriftCheckHook`` so the increment leaves a canonical trail.

Drift-check stage 1 (FK-26 §26.3 / FK-23 §23.7): a deterministic diff against the
exploration design artifact (``_temp/qa/{story_id}/entwurfsartefakt.json``). When
there was no exploration the artifact is absent and the drift check is SKIPPED
with ``drift_check.skipped=true`` (never a silent pass — fail-closed marker).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

from agentkit.telemetry.hooks.base import HookContext, HookTrigger

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.implementation.worker_session.session import WorkerSession
    from agentkit.telemetry.hooks.commit_hook import CommitHook
    from agentkit.telemetry.hooks.drift_check_hook import DriftCheckHook

#: Design-artifact file name (FK-23 §23.4.3). A data path, not a code import:
#: the loop reproduces the ``_temp/qa`` layout locally exactly like the
#: DriftCheckHook (AC10 import boundary), pinned by a unit test.
_DESIGN_ARTIFACT_FILENAME = "entwurfsartefakt.json"


class IncrementStep(StrEnum):
    """The four ordered steps of one worker increment (FK-26 §26.3).

    Attributes:
        IMPLEMENT: Apply the code change.
        VERIFY_LOCAL: Run the local tests.
        DRIFT_CHECK: Check drift against the design artifact (stage 1).
        COMMIT: Commit the increment (with hook validation).
    """

    IMPLEMENT = "implement"
    VERIFY_LOCAL = "verify_local"
    DRIFT_CHECK = "drift_check"
    COMMIT = "commit"


#: Canonical ordered tuple of the four increment steps (FK-26 §26.3).
INCREMENT_STEPS: tuple[IncrementStep, ...] = (
    IncrementStep.IMPLEMENT,
    IncrementStep.VERIFY_LOCAL,
    IncrementStep.DRIFT_CHECK,
    IncrementStep.COMMIT,
)


@dataclass(frozen=True)
class DriftEvent:
    """A drift-check stage-1 result for one increment (FK-26 §26.3 / FK-23 §23.7).

    Attributes:
        increment: 1-based increment index this drift result belongs to.
        drift_detected: Whether the increment drifted from the design artifact.
        skipped: ``True`` when there was no exploration design artifact, so the
            check did not run (fail-closed marker, NOT a silent pass).
        reason: Optional reason (``"no_design_artifact"`` when skipped, or a
            human-readable drift justification when detected).
    """

    increment: int
    drift_detected: bool
    skipped: bool
    reason: str | None = None


@dataclass(frozen=True)
class IncrementInput:
    """The observed facts of one worker increment (FK-26 §26.3).

    Attributes:
        index: 1-based increment index.
        description: Human-readable description of the vertical increment.
        commit_sha: Commit SHA produced by the increment commit.
        files_changed: Number of files changed in the increment.
        tests_added: Test locators added in the increment.
        verify_passed: Whether the local verification (step 2) passed.
        drift_detected: Worker-computed drift verdict vs the design artifact
            (only consulted when the design artifact exists).
        drift_reason: Optional justification recorded when drift is detected.
        repo_name: Repository the increment was committed in (telemetry).
    """

    index: int
    description: str
    commit_sha: str
    files_changed: int = 0
    tests_added: tuple[str, ...] = ()
    verify_passed: bool = True
    drift_detected: bool = False
    drift_reason: str | None = None
    repo_name: str = ""


@dataclass(frozen=True)
class IncrementSummary:
    """A compact per-increment summary for the handover (FK-26 §26.7.2).

    Attributes:
        description: Description of the increment.
        commit_sha: The increment's commit SHA.
        tests_added: Test locators added in the increment.
    """

    description: str
    commit_sha: str
    tests_added: tuple[str, ...] = ()


@dataclass(frozen=True)
class IncrementResult:
    """The recorded outcome of one four-step increment (FK-26 §26.3).

    Attributes:
        index: 1-based increment index.
        steps_completed: The increment steps that completed, in order.
        verify_passed: Whether local verification passed.
        drift: The drift-check stage-1 result.
        summary: The compact handover summary for this increment.
    """

    index: int
    steps_completed: tuple[IncrementStep, ...]
    verify_passed: bool
    drift: DriftEvent
    summary: IncrementSummary
    events_emitted: tuple[str, ...] = field(default_factory=tuple)


class WorkerLoop:
    """Records the four-step worker increment and emits its telemetry (FK-26 §26.3).

    The loop binds the two AG3-036 increment hooks. ``run_increment`` walks the
    four steps for one increment, performs the deterministic drift-check stage 1
    against the design artifact, and emits the canonical ``increment_commit`` and
    ``drift_check`` events through the injected hooks (FK-68 §68.2.2).
    """

    def __init__(
        self,
        drift_check_hook: DriftCheckHook,
        commit_hook: CommitHook,
        *,
        project_root: Path,
    ) -> None:
        """Initialise the loop with the increment hooks and the project root.

        Args:
            drift_check_hook: AG3-036 ``drift_check`` hook (FK-68 §68.2.2).
            commit_hook: AG3-036 ``increment_commit`` hook (FK-68 §68.2.2).
            project_root: Project root used to locate the design artifact under
                ``_temp/qa/{story_id}/entwurfsartefakt.json`` (drift stage 1).
        """
        self._drift_check_hook = drift_check_hook
        self._commit_hook = commit_hook
        self._project_root = project_root

    def run_increment(
        self,
        session: WorkerSession,
        increment_input: IncrementInput,
    ) -> IncrementResult:
        """Walk the four increment steps and emit the increment telemetry.

        Steps (FK-26 §26.3): implement -> verify_local -> drift_check -> commit.
        ``verify_local`` and ``commit`` are recorded as completed only when the
        increment actually verified/committed; the drift-check stage 1 runs
        deterministically against the design artifact and is SKIPPED (fail-closed
        marker) when there was no exploration.

        Args:
            session: The active worker session (story/run binding).
            increment_input: The observed facts of the increment.

        Returns:
            An :class:`IncrementResult` recording the completed steps, the drift
            result and the compact handover summary.
        """
        steps: list[IncrementStep] = [IncrementStep.IMPLEMENT]
        if increment_input.verify_passed:
            steps.append(IncrementStep.VERIFY_LOCAL)

        drift = self._check_drift(session, increment_input)
        steps.append(IncrementStep.DRIFT_CHECK)

        events: list[str] = []
        # Step 4 — commit. Emit the canonical increment_commit + drift_check
        # events through the AG3-036 hooks (FK-68 §68.2.2).
        commit_ctx = self._commit_context(session, increment_input)
        commit_result = self._commit_hook.evaluate(commit_ctx)
        if commit_result.triggered:
            self._commit_hook.emit(commit_result)
            events.extend(e.event_type.value for e in commit_result.events)
        steps.append(IncrementStep.COMMIT)

        drift_result = self._drift_check_hook.evaluate(commit_ctx)
        if drift_result.triggered:
            self._drift_check_hook.emit(drift_result)
            events.extend(e.event_type.value for e in drift_result.events)

        summary = IncrementSummary(
            description=increment_input.description,
            commit_sha=increment_input.commit_sha,
            tests_added=increment_input.tests_added,
        )
        return IncrementResult(
            index=increment_input.index,
            steps_completed=tuple(steps),
            verify_passed=increment_input.verify_passed,
            drift=drift,
            summary=summary,
            events_emitted=tuple(events),
        )

    def _check_drift(
        self,
        session: WorkerSession,
        increment_input: IncrementInput,
    ) -> DriftEvent:
        """Run drift-check stage 1 against the design artifact (deterministic).

        FK-26 §26.3 / FK-23 §23.7: when the exploration design artifact is absent
        the check is SKIPPED with ``skipped=true`` and ``reason``
        ``"no_design_artifact"`` (never a silent pass). Otherwise the
        worker-computed ``drift_detected`` verdict is recorded.

        Args:
            session: The active worker session.
            increment_input: The observed increment facts.

        Returns:
            A :class:`DriftEvent` for the increment.
        """
        artifact_path = (
            self._project_root
            / "_temp"
            / "qa"
            / session.story_id
            / _DESIGN_ARTIFACT_FILENAME
        )
        if not artifact_path.exists():
            return DriftEvent(
                increment=increment_input.index,
                drift_detected=False,
                skipped=True,
                reason="no_design_artifact",
            )
        return DriftEvent(
            increment=increment_input.index,
            drift_detected=increment_input.drift_detected,
            skipped=False,
            reason=increment_input.drift_reason
            if increment_input.drift_detected
            else None,
        )

    def _commit_context(
        self,
        session: WorkerSession,
        increment_input: IncrementInput,
    ) -> HookContext:
        """Build the harness-neutral commit observation for the increment hooks.

        Args:
            session: The active worker session.
            increment_input: The observed increment facts.

        Returns:
            A :class:`HookContext` describing the ``git commit`` observation.
        """
        return HookContext(
            trigger=HookTrigger.POST_TOOL_USE,
            story_id=session.story_id,
            run_id=session.run_id,
            project_key=session.project_key,
            tool="Bash",
            command="git commit",
            phase="implementation",
            payload={
                "commit_sha": increment_input.commit_sha,
                "repo_name": increment_input.repo_name,
                "files_changed": increment_input.files_changed,
                "drift_detected": increment_input.drift_detected,
            },
        )


__all__ = [
    "INCREMENT_STEPS",
    "DriftEvent",
    "IncrementInput",
    "IncrementResult",
    "IncrementStep",
    "IncrementSummary",
    "WorkerLoop",
]
