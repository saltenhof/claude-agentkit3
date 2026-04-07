"""Individual structural checks -- pure functions returning findings.

Each check examines one specific aspect. No side effects (ARCH-31).
No god-class aggregation (ARCH-05). Each function receives its inputs
explicitly and returns Finding(s) or None/empty list.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.pipeline.state import load_phase_state, load_story_context
from agentkit.qa.protocols import Finding, Severity, TrustClass

if TYPE_CHECKING:
    from pathlib import Path


def check_context_exists(story_dir: Path) -> Finding | None:
    """Check that context.json exists in story directory.

    Args:
        story_dir: Directory containing story artifacts.

    Returns:
        A CRITICAL finding if context.json is missing, otherwise ``None``.
    """
    if not (story_dir / "context.json").exists():
        return Finding(
            layer="structural",
            check="context_exists",
            severity=Severity.CRITICAL,
            trust_class=TrustClass.SYSTEM,
            message="context.json not found in story directory",
        )
    return None


def check_context_valid(story_dir: Path) -> Finding | None:
    """Check that context.json is valid and loadable.

    Attempts to load context.json via ``load_story_context``. If the
    file exists but cannot be parsed or validated, returns a CRITICAL
    finding.

    Args:
        story_dir: Directory containing story artifacts.

    Returns:
        A CRITICAL finding if context.json is corrupt, otherwise ``None``.
    """
    context_path = story_dir / "context.json"
    if not context_path.exists():
        # Existence is checked by check_context_exists; skip here.
        return None

    ctx = load_story_context(story_dir)
    if ctx is None:
        return Finding(
            layer="structural",
            check="context_valid",
            severity=Severity.CRITICAL,
            trust_class=TrustClass.SYSTEM,
            message="context.json exists but is corrupt or invalid",
            file_path=str(context_path),
        )
    return None


def check_phase_snapshots(
    story_dir: Path,
    required_phases: list[str],
) -> list[Finding]:
    """Check that required phase snapshots exist.

    For each required phase, checks that the corresponding
    ``phase-state-{phase}.json`` file exists.

    Args:
        story_dir: Directory containing story artifacts.
        required_phases: List of phase names that must have snapshots.

    Returns:
        List of HIGH findings, one per missing phase snapshot.
    """
    findings: list[Finding] = []
    for phase in required_phases:
        snapshot_path = story_dir / f"phase-state-{phase}.json"
        if not snapshot_path.exists():
            findings.append(
                Finding(
                    layer="structural",
                    check="phase_snapshots",
                    severity=Severity.HIGH,
                    trust_class=TrustClass.SYSTEM,
                    message=f"Phase snapshot missing for phase '{phase}'",
                    file_path=str(snapshot_path),
                    suggestion=f"Ensure phase '{phase}' completed before verify.",
                ),
            )
    return findings


def check_artifacts_present(
    story_dir: Path,
    required_artifacts: list[str],
) -> list[Finding]:
    """Check that required artifacts exist.

    Args:
        story_dir: Directory containing story artifacts.
        required_artifacts: List of artifact filenames that must exist.

    Returns:
        List of HIGH findings, one per missing artifact.
    """
    findings: list[Finding] = []
    for artifact in required_artifacts:
        artifact_path = story_dir / artifact
        if not artifact_path.exists():
            findings.append(
                Finding(
                    layer="structural",
                    check="artifacts_present",
                    severity=Severity.HIGH,
                    trust_class=TrustClass.SYSTEM,
                    message=f"Required artifact missing: '{artifact}'",
                    file_path=str(artifact_path),
                ),
            )
    return findings


def check_no_corrupt_state(story_dir: Path) -> Finding | None:
    """Check that phase-state.json is valid if it exists.

    If phase-state.json does not exist, this check passes (it is
    optional). If it exists but cannot be loaded, returns a finding.

    Args:
        story_dir: Directory containing story artifacts.

    Returns:
        A HIGH finding if phase-state.json is corrupt, otherwise ``None``.
    """
    state_path = story_dir / "phase-state.json"
    if not state_path.exists():
        return None

    state = load_phase_state(story_dir)
    if state is None:
        return Finding(
            layer="structural",
            check="no_corrupt_state",
            severity=Severity.HIGH,
            trust_class=TrustClass.SYSTEM,
            message="phase-state.json exists but is corrupt or invalid",
            file_path=str(state_path),
        )
    return None
