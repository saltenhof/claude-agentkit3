"""Bugfix Red-Green-Suite checks (FK-26 §26.9 / FK-33 §33.3.2)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from agentkit.backend.verify_system.protocols import Finding, TrustClass

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.core_types import Severity
    from agentkit.backend.story_context_manager.models import StoryContext

__all__ = [
    "ABSENT_BUGFIX_EVIDENCE_PORT",
    "BugfixEvidence",
    "BugfixEvidencePort",
    "check_bugfix_green_evidence",
    "check_bugfix_red_evidence",
    "check_bugfix_red_green_consistency",
    "check_bugfix_reproducer_manifest",
    "check_bugfix_suite_evidence",
]

_REPRODUCER_CHECK = "bugfix.reproducer_manifest"
_RED_CHECK = "bugfix.red_evidence"
_GREEN_CHECK = "bugfix.green_evidence"
_SUITE_CHECK = "bugfix.suite_evidence"
_CONSISTENCY_CHECK = "bugfix.red_green_consistency"


@dataclass(frozen=True)
class BugfixEvidence:
    """Commit-bound evidence for the bugfix Red-Green-Suite.

    Attributes:
        reproducer_manifest: Parsed ``bugfix-reproducer.json`` payload.
        red_exit_code: Exit code of the reproducer before the fix.
        green_exit_code: Exit code of the reproducer after the fix.
        suite_exit_code: Exit code of the complete test suite after the fix.
        red_command: Command used for the red reproducer run.
        green_command: Command used for the green reproducer run.
        red_commit_sha: Commit SHA for the red run.
        green_commit_sha: Commit SHA for the green run.
        detail: Optional diagnostic detail for findings.
    """

    reproducer_manifest: dict[str, object] | None
    red_exit_code: int | None
    green_exit_code: int | None
    suite_exit_code: int | None
    red_command: str | None
    green_command: str | None
    red_commit_sha: str | None
    green_commit_sha: str | None
    detail: str | None = None


@runtime_checkable
class BugfixEvidencePort(Protocol):
    """Read-port returning Red-Green-Suite evidence for a bugfix story."""

    def evaluate(self, story_dir: Path) -> BugfixEvidence | None:
        """Return the bugfix evidence for ``story_dir`` (``None`` = unknown)."""
        ...


@dataclass(frozen=True)
class _AbsentBugfixEvidencePort:
    """Default port: bugfix evidence is unconfirmable (fail-closed)."""

    def evaluate(self, story_dir: Path) -> BugfixEvidence | None:
        """Return ``None`` -- no bugfix evidence is available."""
        del story_dir
        return None


ABSENT_BUGFIX_EVIDENCE_PORT: BugfixEvidencePort = _AbsentBugfixEvidencePort()


def _finding(check: str, severity: Severity, message: str) -> Finding:
    return Finding(
        layer="structural",
        check=check,
        severity=severity,
        message=message,
        trust_class=TrustClass.SYSTEM,
    )


def _evidence_or_finding(
    port: BugfixEvidencePort,
    story_dir: Path,
    *,
    check: str,
    severity: Severity,
) -> tuple[BugfixEvidence | None, Finding | None]:
    evidence = port.evaluate(story_dir)
    if evidence is None:
        return None, _finding(
            check,
            severity,
            "no bugfix Red-Green-Suite evidence wired; status unconfirmable -> "
            "fail-closed (FK-26 §26.9, NO ERROR BYPASSING)",
        )
    return evidence, None


def check_bugfix_reproducer_manifest(
    ctx: StoryContext,
    story_dir: Path,
    *,
    severity: Severity,
    port: BugfixEvidencePort,
) -> Finding | None:
    """Validate the mandatory ``bugfix-reproducer.json`` fields."""
    del ctx
    evidence, absent = _evidence_or_finding(
        port, story_dir, check=_REPRODUCER_CHECK, severity=severity
    )
    if absent is not None:
        return absent
    assert evidence is not None
    manifest = evidence.reproducer_manifest
    if manifest is None:
        return _finding(
            _REPRODUCER_CHECK,
            severity,
            "bugfix reproducer manifest is missing (FK-26 §26.9.2)",
        )
    missing = _missing_manifest_fields(manifest)
    if missing:
        return _finding(
            _REPRODUCER_CHECK,
            severity,
            f"bugfix reproducer manifest missing required field(s): "
            f"{', '.join(missing)} (FK-26 §26.9.2)",
        )
    return None


def check_bugfix_red_evidence(
    ctx: StoryContext,
    story_dir: Path,
    *,
    severity: Severity,
    port: BugfixEvidencePort,
) -> Finding | None:
    """Validate that the reproducer failed before the fix (exit != 0)."""
    del ctx
    evidence, absent = _evidence_or_finding(
        port, story_dir, check=_RED_CHECK, severity=severity
    )
    if absent is not None:
        return absent
    assert evidence is not None
    if evidence.red_exit_code is None:
        return _finding(_RED_CHECK, severity, "red-phase exit code is missing")
    if evidence.red_exit_code == 0:
        return _finding(
            _RED_CHECK,
            severity,
            "red phase did not fail; reproducer must exit != 0 before the fix "
            "(FK-26 §26.9.1)",
        )
    return None


def check_bugfix_green_evidence(
    ctx: StoryContext,
    story_dir: Path,
    *,
    severity: Severity,
    port: BugfixEvidencePort,
) -> Finding | None:
    """Validate that the reproducer passes after the fix (exit == 0)."""
    del ctx
    evidence, absent = _evidence_or_finding(
        port, story_dir, check=_GREEN_CHECK, severity=severity
    )
    if absent is not None:
        return absent
    assert evidence is not None
    if evidence.green_exit_code != 0:
        return _finding(
            _GREEN_CHECK,
            severity,
            "green phase is not green; reproducer must exit == 0 after the fix "
            "(FK-26 §26.9.1)",
        )
    return None


def check_bugfix_suite_evidence(
    ctx: StoryContext,
    story_dir: Path,
    *,
    severity: Severity,
    port: BugfixEvidencePort,
) -> Finding | None:
    """Validate that the complete suite passes after the fix (exit == 0)."""
    del ctx
    evidence, absent = _evidence_or_finding(
        port, story_dir, check=_SUITE_CHECK, severity=severity
    )
    if absent is not None:
        return absent
    assert evidence is not None
    if evidence.suite_exit_code != 0:
        return _finding(
            _SUITE_CHECK,
            severity,
            "suite phase is not green; complete suite must exit == 0 "
            "(FK-26 §26.9.1)",
        )
    return None


def check_bugfix_red_green_consistency(
    ctx: StoryContext,
    story_dir: Path,
    *,
    severity: Severity,
    port: BugfixEvidencePort,
) -> Finding | None:
    """Validate same command and different commits for red/green runs."""
    del ctx
    evidence, absent = _evidence_or_finding(
        port, story_dir, check=_CONSISTENCY_CHECK, severity=severity
    )
    if absent is not None:
        return absent
    assert evidence is not None
    if not evidence.red_command or not evidence.green_command:
        return _finding(
            _CONSISTENCY_CHECK,
            severity,
            "red/green commands are missing; consistency unconfirmable",
        )
    if evidence.red_command != evidence.green_command:
        return _finding(
            _CONSISTENCY_CHECK,
            severity,
            "red and green phases must use the same reproducer command "
            "(FK-26 §26.9.2)",
        )
    if not evidence.red_commit_sha or not evidence.green_commit_sha:
        return _finding(
            _CONSISTENCY_CHECK,
            severity,
            "red/green commit SHAs are missing; consistency unconfirmable",
        )
    if evidence.red_commit_sha == evidence.green_commit_sha:
        return _finding(
            _CONSISTENCY_CHECK,
            severity,
            "red and green phases must run on different commit SHAs "
            "(FK-26 §26.9.2)",
        )
    return None


def _missing_manifest_fields(manifest: dict[str, object]) -> list[str]:
    missing: list[str] = []
    for key in ("bug_description", "stack", "expected_failure"):
        if not isinstance(manifest.get(key), str) or not str(
            manifest.get(key)
        ).strip():
            missing.append(key)
    locator = manifest.get("test_locator")
    if (
        not isinstance(locator, dict)
        or not isinstance(locator.get("nodeid"), str)
        or not locator["nodeid"].strip()
    ):
        missing.append("test_locator.nodeid")
    return missing
