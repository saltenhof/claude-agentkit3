"""Integrity gate -- multi-dimensional quality check before closure.

The integrity gate verifies that all required QA evidence exists
and is consistent before allowing a story to close.  It performs
read-only file-system inspection -- no mutation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.story_context_manager.types import StoryType

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True)
class IntegrityCheckResult:
    """Result of a single integrity dimension check.

    Attributes:
        dimension: Name of the dimension being checked.
        passed: Whether this dimension's requirements are met.
        message: Human-readable explanation.
    """

    dimension: str
    passed: bool
    message: str


@dataclass(frozen=True)
class IntegrityGateResult:
    """Aggregated result of all integrity checks.

    Attributes:
        passed: ``True`` only if every individual check passed.
        checks: Tuple of all individual check results.
    """

    passed: bool
    checks: tuple[IntegrityCheckResult, ...]

    @property
    def failed_checks(self) -> tuple[IntegrityCheckResult, ...]:
        """Return only the checks that did not pass."""
        return tuple(c for c in self.checks if not c.passed)


# Phases required per story type for snapshot checks.
_REQUIRED_PHASES: dict[StoryType, tuple[str, ...]] = {
    StoryType.IMPLEMENTATION: ("setup", "implementation", "verify"),
    StoryType.BUGFIX: ("setup", "implementation", "verify"),
    StoryType.CONCEPT: ("setup", "implementation"),
    StoryType.RESEARCH: ("setup", "implementation"),
}


class IntegrityGate:
    """Multi-dimensional integrity gate.

    Checks before closure:

    1. All required phase snapshots exist and show COMPLETED status.
    2. For code stories: verify decision exists and is PASS.
    3. ``context.json`` exists and is valid JSON.
    4. No corrupt state files (``phase-state.json`` readable if present).
    """

    def evaluate(
        self, story_dir: Path, story_type: StoryType,
    ) -> IntegrityGateResult:
        """Run all integrity checks.

        Args:
            story_dir: Root directory containing story artifacts.
            story_type: Determines which phases/checks are required.

        Returns:
            An ``IntegrityGateResult`` aggregating all dimension checks.
        """
        checks: list[IntegrityCheckResult] = []

        checks.extend(self._check_phase_snapshots(story_dir, story_type))

        if story_type in (StoryType.IMPLEMENTATION, StoryType.BUGFIX):
            checks.append(self._check_verify_decision(story_dir))

        checks.append(self._check_context_json(story_dir))
        checks.append(self._check_state_file(story_dir))

        passed = all(c.passed for c in checks)
        return IntegrityGateResult(passed=passed, checks=tuple(checks))

    # ------------------------------------------------------------------
    # Private dimension checkers
    # ------------------------------------------------------------------

    @staticmethod
    def _check_phase_snapshots(
        story_dir: Path, story_type: StoryType,
    ) -> list[IntegrityCheckResult]:
        """Verify that all required phase snapshots exist and are COMPLETED."""
        required = _REQUIRED_PHASES.get(story_type, ())
        results: list[IntegrityCheckResult] = []

        for phase in required:
            snapshot_path = story_dir / f"phase-state-{phase}.json"
            dim_name = f"phase_snapshot_{phase}"

            if not snapshot_path.exists():
                results.append(IntegrityCheckResult(
                    dimension=dim_name,
                    passed=False,
                    message=f"Missing phase snapshot: {snapshot_path.name}",
                ))
                continue

            try:
                with snapshot_path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError):
                results.append(IntegrityCheckResult(
                    dimension=dim_name,
                    passed=False,
                    message=f"Corrupt phase snapshot: {snapshot_path.name}",
                ))
                continue

            status = data.get("status") if isinstance(data, dict) else None
            if status != "completed":
                results.append(IntegrityCheckResult(
                    dimension=dim_name,
                    passed=False,
                    message=(
                        f"Phase {phase!r} status is {status!r}, "
                        f"expected 'completed'"
                    ),
                ))
            else:
                results.append(IntegrityCheckResult(
                    dimension=dim_name,
                    passed=True,
                    message=f"Phase {phase!r} snapshot OK",
                ))

        return results

    @staticmethod
    def _check_verify_decision(story_dir: Path) -> IntegrityCheckResult:
        """Verify that the verify decision exists and is PASS."""
        canonical_path = story_dir / "verify-decision.json"
        legacy_path = story_dir / "decision.json"
        dim_name = "verify_decision"

        decision_path = canonical_path if canonical_path.exists() else legacy_path
        if not decision_path.exists():
            return IntegrityCheckResult(
                dimension=dim_name,
                passed=False,
                message="Missing verify decision: verify-decision.json",
            )

        try:
            with decision_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return IntegrityCheckResult(
                dimension=dim_name,
                passed=False,
                message=f"Corrupt verify decision: {decision_path.name}",
            )

        if not isinstance(data, dict):
            return IntegrityCheckResult(
                dimension=dim_name,
                passed=False,
                message="Verify decision is not a JSON object",
            )

        decision = data.get("decision")
        status = data.get("status")
        if status is not None:
            passed = bool(data.get("passed")) and status in (
                "PASS",
                "PASS_WITH_WARNINGS",
            )
        else:
            passed = decision in ("PASS", "PASS_WITH_WARNINGS")
        decision_label = status if status is not None else decision
        if not passed:
            return IntegrityCheckResult(
                dimension=dim_name,
                passed=False,
                message=(
                    f"Verify decision is {decision_label!r}, "
                    "expected PASS/PASS_WITH_WARNINGS"
                ),
            )

        return IntegrityCheckResult(
            dimension=dim_name,
            passed=True,
            message=f"Verify decision OK via {decision_path.name}",
        )

    @staticmethod
    def _check_context_json(story_dir: Path) -> IntegrityCheckResult:
        """Verify that context.json exists and is valid JSON."""
        context_path = story_dir / "context.json"
        dim_name = "context_json"

        if not context_path.exists():
            return IntegrityCheckResult(
                dimension=dim_name,
                passed=False,
                message="Missing context.json",
            )

        try:
            with context_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return IntegrityCheckResult(
                dimension=dim_name,
                passed=False,
                message="Corrupt context.json",
            )

        if not isinstance(data, dict):
            return IntegrityCheckResult(
                dimension=dim_name,
                passed=False,
                message="context.json is not a JSON object",
            )

        return IntegrityCheckResult(
            dimension=dim_name,
            passed=True,
            message="context.json is valid",
        )

    @staticmethod
    def _check_state_file(story_dir: Path) -> IntegrityCheckResult:
        """Verify that phase-state.json is readable if present."""
        state_path = story_dir / "phase-state.json"
        dim_name = "state_file"

        if not state_path.exists():
            # Not present is fine -- might already be cleaned up.
            return IntegrityCheckResult(
                dimension=dim_name,
                passed=True,
                message="phase-state.json not present (acceptable)",
            )

        try:
            with state_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return IntegrityCheckResult(
                dimension=dim_name,
                passed=False,
                message="Corrupt phase-state.json",
            )

        if not isinstance(data, dict):
            return IntegrityCheckResult(
                dimension=dim_name,
                passed=False,
                message="phase-state.json is not a JSON object",
            )

        return IntegrityCheckResult(
            dimension=dim_name,
            passed=True,
            message="phase-state.json is valid",
        )
