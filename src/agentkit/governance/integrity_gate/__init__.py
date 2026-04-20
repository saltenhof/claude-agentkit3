"""Integrity gate -- canonical pre-closure quality checks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.exceptions import CorruptStateError
from agentkit.state_backend import (
    CONTEXT_EXPORT_FILE,
    PHASE_STATE_EXPORT_FILE,
    VERIFY_DECISION_FILE,
    backend_has_completed_snapshot,
    backend_has_structural_artifact,
    backend_has_structural_artifact_for_scope,
    backend_has_valid_context,
    backend_has_valid_phase_state,
    load_latest_verify_decision,
    load_latest_verify_decision_for_scope,
    read_phase_state_record,
    resolve_runtime_scope,
)
from agentkit.state_backend.exports import verify_decision_passed
from agentkit.story_context_manager.types import StoryType

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.state_backend.scope import RuntimeStateScope


@dataclass(frozen=True)
class IntegrityCheckResult:
    """Result of one integrity dimension."""

    dimension: str
    passed: bool
    message: str


@dataclass(frozen=True)
class IntegrityGateResult:
    """Aggregated integrity outcome."""

    passed: bool
    checks: tuple[IntegrityCheckResult, ...]

    @property
    def failed_checks(self) -> tuple[IntegrityCheckResult, ...]:
        return tuple(check for check in self.checks if not check.passed)


_REQUIRED_PHASES: dict[StoryType, tuple[str, ...]] = {
    StoryType.IMPLEMENTATION: ("setup", "implementation", "verify"),
    StoryType.BUGFIX: ("setup", "implementation", "verify"),
    StoryType.CONCEPT: ("setup", "implementation"),
    StoryType.RESEARCH: ("setup", "implementation"),
}


class IntegrityGate:
    """Run canonical integrity checks before closure."""

    def evaluate(self, story_dir: Path, story_type: StoryType) -> IntegrityGateResult:
        checks: list[IntegrityCheckResult] = []
        try:
            runtime_scope: RuntimeStateScope | None = resolve_runtime_scope(story_dir)
        except CorruptStateError:
            runtime_scope = None
        checks.extend(self._check_phase_snapshots(story_dir, story_type))

        if story_type in (StoryType.IMPLEMENTATION, StoryType.BUGFIX):
            checks.append(self._check_structural_artifact(story_dir, runtime_scope))
            checks.append(self._check_verify_decision(story_dir, runtime_scope))

        checks.append(self._check_context_record(story_dir))
        checks.append(self._check_phase_state_record(story_dir))
        return IntegrityGateResult(
            passed=all(check.passed for check in checks),
            checks=tuple(checks),
        )

    @staticmethod
    def _check_phase_snapshots(
        story_dir: Path,
        story_type: StoryType,
    ) -> list[IntegrityCheckResult]:
        results: list[IntegrityCheckResult] = []
        for phase in _REQUIRED_PHASES.get(story_type, ()):
            dim_name = f"phase_snapshot_{phase}"
            try:
                completed = backend_has_completed_snapshot(story_dir, phase)
            except CorruptStateError:
                completed = False
            if completed:
                results.append(
                    IntegrityCheckResult(
                        dimension=dim_name,
                        passed=True,
                        message=f"Phase {phase!r} snapshot OK",
                    )
                )
                continue
            results.append(
                IntegrityCheckResult(
                    dimension=dim_name,
                    passed=False,
                    message=(
                        "Missing or invalid canonical snapshot "
                        f"for phase {phase!r}"
                    ),
                )
            )
        return results

    @staticmethod
    def _check_structural_artifact(
        story_dir: Path,
        runtime_scope: RuntimeStateScope | None,
    ) -> IntegrityCheckResult:
        try:
            if runtime_scope is not None and runtime_scope.run_id is not None:
                present = backend_has_structural_artifact_for_scope(runtime_scope)
            else:
                present = backend_has_structural_artifact(story_dir)
        except CorruptStateError:
            present = False
        if present:
            return IntegrityCheckResult(
                dimension="structural_artifact",
                passed=True,
                message="Canonical structural QA artifact exists",
            )
        return IntegrityCheckResult(
            dimension="structural_artifact",
            passed=False,
            message="Missing canonical structural QA artifact record",
        )

    @staticmethod
    def _check_verify_decision(
        story_dir: Path,
        runtime_scope: RuntimeStateScope | None,
    ) -> IntegrityCheckResult:
        try:
            if runtime_scope is not None and runtime_scope.run_id is not None:
                payload = load_latest_verify_decision_for_scope(runtime_scope)
            else:
                payload = load_latest_verify_decision(story_dir)
        except CorruptStateError:
            payload = None
        if payload is None:
            return IntegrityCheckResult(
                dimension="verify_decision",
                passed=False,
                message=(
                    "Missing canonical verify decision record "
                    f"for {VERIFY_DECISION_FILE}"
                ),
            )
        if not verify_decision_passed(payload):
            label = payload.get("status", payload.get("decision"))
            return IntegrityCheckResult(
                dimension="verify_decision",
                passed=False,
                message=(
                    f"Verify decision is {label!r}, expected PASS/PASS_WITH_WARNINGS"
                ),
            )
        return IntegrityCheckResult(
            dimension="verify_decision",
            passed=True,
            message="Canonical verify decision record passed",
        )

    @staticmethod
    def _check_context_record(story_dir: Path) -> IntegrityCheckResult:
        try:
            valid = backend_has_valid_context(story_dir)
        except CorruptStateError:
            valid = False
        if valid:
            return IntegrityCheckResult(
                dimension="context_record",
                passed=True,
                message=(
                    "Canonical story context exists; "
                    f"{CONTEXT_EXPORT_FILE} is projection-only"
                ),
            )
        return IntegrityCheckResult(
            dimension="context_record",
            passed=False,
            message="Missing or invalid canonical story context record",
        )

    @staticmethod
    def _check_phase_state_record(story_dir: Path) -> IntegrityCheckResult:
        try:
            state = read_phase_state_record(story_dir)
        except CorruptStateError:
            return IntegrityCheckResult(
                dimension="phase_state_record",
                passed=False,
                message="Canonical phase state record is corrupt or invalid",
            )
        if state is None:
            return IntegrityCheckResult(
                dimension="phase_state_record",
                passed=True,
                message=(
                    "Canonical phase state record absent "
                    "after cleanup (acceptable)"
                ),
            )
        if backend_has_valid_phase_state(story_dir):
            return IntegrityCheckResult(
                dimension="phase_state_record",
                passed=True,
                message=(
                    "Canonical phase state exists; "
                    f"{PHASE_STATE_EXPORT_FILE} is projection-only"
                ),
            )
        return IntegrityCheckResult(
            dimension="phase_state_record",
            passed=False,
            message="Missing or invalid canonical phase state record",
        )
