"""Build & test checks (FK-27 §27.4.2 / FK-33 §33.3.2-§33.3.3).

``build.compile`` and ``build.test_execution`` are BLOCKING; ``test.count``
and ``test.coverage`` are MAJOR (FK-27 §27.4.2). The build/test execution is
NOT run inline here: a deterministic Layer-1 check is a pure function and
must not shell out from inside the QA aggregation. Instead it consumes a
:class:`BuildTestEvidencePort` (injected into ``StructuralChecker``; the same
shape as the closure Sanity-Gate's test runner, FK-24 §24.3.4) that reports
the commit-bound build/test/coverage evidence.

FAIL-CLOSED (NO ERROR BYPASSING): when no port is wired the evidence is
unconfirmable, so ``build.compile`` / ``build.test_execution`` FAIL (BLOCKING)
and ``test.count`` / ``test.coverage`` FAIL (MAJOR) — never a silent PASS.
The build/test commands themselves are pyproject-conformant (FK-33 §33.3.3
Python stack: build ``ruff check .``, test ``pytest``); the productive port
adapter owns the subprocess, keeping unit tests subprocess-free.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from agentkit.backend.verify_system.protocols import Finding, TrustClass

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.core_types import Severity
    from agentkit.backend.story_context_manager.models import StoryContext

__all__ = [
    "ABSENT_BUILD_TEST_PORT",
    "BuildTestEvidence",
    "BuildTestEvidencePort",
    "check_build_compile",
    "check_build_test_execution",
    "check_test_coverage",
    "check_test_count",
]

_TEST_COVERAGE_CHECK = "test.coverage"


@dataclass(frozen=True)
class BuildTestEvidence:
    """Commit-bound build/test/coverage evidence (FK-33 §33.3.2-§33.3.3).

    Attributes:
        build_ok: Whether the build command (``ruff check .`` for Python)
            succeeded.
        tests_green: Whether the test command (``pytest``) passed.
        test_file_count: Number of test files in the changeset (FK-27
            ``test.count``).
        coverage_report_present: Whether a coverage report exists.
        coverage_meets_threshold: Whether coverage meets the configured
            threshold (FK-27 ``test.coverage``).
        detail: Optional machine-readable detail for findings.
    """

    build_ok: bool
    tests_green: bool
    test_file_count: int
    coverage_report_present: bool
    coverage_meets_threshold: bool
    detail: str | None = None


@runtime_checkable
class BuildTestEvidencePort(Protocol):
    """Read-port returning commit-bound build/test/coverage evidence.

    The productive adapter (wired via the composition root) runs the
    pyproject-conformant build/test commands as a subprocess; unit tests pass
    a recording double. ``None`` means the evidence is unconfirmable (the
    checks fail closed).
    """

    def evaluate(self, story_dir: Path) -> BuildTestEvidence | None:
        """Return the build/test evidence for ``story_dir`` (``None`` = unknown)."""
        ...


@dataclass(frozen=True)
class _AbsentBuildTestPort:
    """Default port: evidence is always unconfirmable (fail-closed)."""

    def evaluate(self, story_dir: Path) -> BuildTestEvidence | None:
        """Return ``None`` -- no build/test evidence available."""
        del story_dir
        return None


#: Default fail-closed port (no live build/test runner wired).
ABSENT_BUILD_TEST_PORT: BuildTestEvidencePort = _AbsentBuildTestPort()


def _finding(check: str, severity: Severity, message: str) -> Finding:
    return Finding(
        layer="structural",
        check=check,
        severity=severity,
        message=message,
        trust_class=TrustClass.SYSTEM,
    )


def check_build_compile(
    ctx: StoryContext,
    story_dir: Path,
    *,
    severity: Severity,
    port: BuildTestEvidencePort,
) -> Finding | None:
    """FK-27 §27.4.2 ``build.compile``: the build compiles successfully.

    Args:
        ctx: Story context (unused; uniform signature).
        story_dir: Story working directory.
        severity: Registry-resolved severity (FK-27 §27.4.2: BLOCKING).
        port: Build/test evidence port.

    Returns:
        ``None`` on PASS; a finding when the build failed or is unconfirmable.
    """
    del ctx
    evidence = port.evaluate(story_dir)
    if evidence is None:
        return _finding(
            "build.compile", severity,
            "no build/test runner wired; build status unconfirmable -> "
            "fail-closed (FK-27 §27.4.2, NO ERROR BYPASSING)",
        )
    if not evidence.build_ok:
        return _finding(
            "build.compile", severity,
            f"build failed (FK-27 §27.4.2): {evidence.detail or 'build not green'}",
        )
    return None


def check_build_test_execution(
    ctx: StoryContext,
    story_dir: Path,
    *,
    severity: Severity,
    port: BuildTestEvidencePort,
) -> Finding | None:
    """FK-27 §27.4.2 ``build.test_execution``: tests pass.

    Args:
        ctx: Story context (unused; uniform signature).
        story_dir: Story working directory.
        severity: Registry-resolved severity (FK-27 §27.4.2: BLOCKING).
        port: Build/test evidence port.

    Returns:
        ``None`` on PASS; a finding when tests are red or unconfirmable.
    """
    del ctx
    evidence = port.evaluate(story_dir)
    if evidence is None:
        return _finding(
            "build.test_execution", severity,
            "no build/test runner wired; test status unconfirmable -> "
            "fail-closed (FK-27 §27.4.2, NO ERROR BYPASSING)",
        )
    if not evidence.tests_green:
        return _finding(
            "build.test_execution", severity,
            f"tests not green (FK-27 §27.4.2): {evidence.detail or 'tests red'}",
        )
    return None


def check_test_count(
    ctx: StoryContext,
    story_dir: Path,
    *,
    severity: Severity,
    port: BuildTestEvidencePort,
) -> Finding | None:
    """FK-27 §27.4.2 ``test.count``: at least one test file in the changeset.

    Args:
        ctx: Story context (unused; uniform signature).
        story_dir: Story working directory.
        severity: Registry-resolved severity (FK-27 §27.4.2: MAJOR).
        port: Build/test evidence port.

    Returns:
        ``None`` on PASS; a MAJOR finding when no test file is present /
        unconfirmable.
    """
    del ctx
    evidence = port.evaluate(story_dir)
    if evidence is None:
        return _finding(
            "test.count", severity,
            "no build/test runner wired; test-file count unconfirmable -> "
            "fail-closed (FK-27 §27.4.2)",
        )
    if evidence.test_file_count < 1:
        return _finding(
            "test.count", severity,
            "no test file in the changeset (FK-27 §27.4.2 test.count)",
        )
    return None


def check_test_coverage(
    ctx: StoryContext,
    story_dir: Path,
    *,
    severity: Severity,
    port: BuildTestEvidencePort,
) -> Finding | None:
    """FK-27 §27.4.2 ``test.coverage``: coverage report exists, threshold met.

    Args:
        ctx: Story context (unused; uniform signature).
        story_dir: Story working directory.
        severity: Registry-resolved severity (FK-27 §27.4.2: MAJOR).
        port: Build/test evidence port.

    Returns:
        ``None`` on PASS; a MAJOR finding when the report is missing or the
        threshold is not met / unconfirmable.
    """
    del ctx
    evidence = port.evaluate(story_dir)
    if evidence is None:
        return _finding(
            _TEST_COVERAGE_CHECK, severity,
            "no build/test runner wired; coverage unconfirmable -> "
            "fail-closed (FK-27 §27.4.2)",
        )
    if not evidence.coverage_report_present:
        return _finding(
            _TEST_COVERAGE_CHECK, severity,
            "coverage report missing (FK-27 §27.4.2 test.coverage)",
        )
    if not evidence.coverage_meets_threshold:
        return _finding(
            _TEST_COVERAGE_CHECK, severity,
            "coverage below threshold (FK-27 §27.4.2 test.coverage)",
        )
    return None
