"""Bugfix Red-Green-Suite structural check tests (AG3-064)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.story_context_manager.models import StoryContext
from agentkit.story_context_manager.types import StoryMode, StoryType
from agentkit.verify_system.protocols import Severity, TrustClass
from agentkit.verify_system.stage_registry import StageRegistry
from agentkit.verify_system.structural.checker import StructuralChecker
from agentkit.verify_system.structural.checks import (
    ABSENT_BUGFIX_EVIDENCE_PORT,
    BugfixEvidence,
    check_bugfix_green_evidence,
    check_bugfix_red_evidence,
    check_bugfix_red_green_consistency,
    check_bugfix_reproducer_manifest,
    check_bugfix_suite_evidence,
)

if TYPE_CHECKING:
    from pathlib import Path


def _ctx(story_type: StoryType = StoryType.BUGFIX) -> StoryContext:
    return StoryContext(
        project_key="test-project",
        story_id="BUG-001",
        story_type=story_type,
        execution_route=StoryMode.EXECUTION,
    )


def _evidence(**overrides: object) -> BugfixEvidence:
    values: dict[str, object] = {
        "reproducer_manifest": {
            "bug_description": "timeout does not close connection",
            "stack": "pytest",
            "test_locator": {"nodeid": "tests/test_bug.py::test_reproducer"},
            "expected_failure": "AssertionError",
        },
        "red_exit_code": 1,
        "green_exit_code": 0,
        "suite_exit_code": 0,
        "red_command": "pytest tests/test_bug.py::test_reproducer",
        "green_command": "pytest tests/test_bug.py::test_reproducer",
        "red_commit_sha": "a" * 40,
        "green_commit_sha": "b" * 40,
    }
    values.update(overrides)
    return BugfixEvidence(**values)  # type: ignore[arg-type]


class _Port:
    def __init__(self, evidence: BugfixEvidence | None) -> None:
        self._evidence = evidence

    def evaluate(self, story_dir: Path) -> BugfixEvidence | None:
        del story_dir
        return self._evidence


def _assert_blocking(finding: object, check: str) -> None:
    assert finding is not None
    assert finding.check == check
    assert finding.severity is Severity.BLOCKING
    assert finding.trust_class is TrustClass.SYSTEM
    assert finding.layer == "structural"


def test_bugfix_checks_pass_with_valid_evidence(tmp_path: Path) -> None:
    port = _Port(_evidence())
    ctx = _ctx()
    checks = (
        check_bugfix_reproducer_manifest,
        check_bugfix_red_evidence,
        check_bugfix_green_evidence,
        check_bugfix_suite_evidence,
        check_bugfix_red_green_consistency,
    )
    for check in checks:
        assert check(ctx, tmp_path, severity=Severity.BLOCKING, port=port) is None


def test_bugfix_checks_fail_closed_without_port(tmp_path: Path) -> None:
    ctx = _ctx()
    checks = {
        "bugfix.reproducer_manifest": check_bugfix_reproducer_manifest,
        "bugfix.red_evidence": check_bugfix_red_evidence,
        "bugfix.green_evidence": check_bugfix_green_evidence,
        "bugfix.suite_evidence": check_bugfix_suite_evidence,
        "bugfix.red_green_consistency": check_bugfix_red_green_consistency,
    }
    for check_id, check in checks.items():
        finding = check(
            ctx, tmp_path, severity=Severity.BLOCKING, port=ABSENT_BUGFIX_EVIDENCE_PORT
        )
        _assert_blocking(finding, check_id)


def test_bugfix_negative_paths_are_blocking(tmp_path: Path) -> None:
    ctx = _ctx()
    cases = (
        (
            "bugfix.reproducer_manifest",
            check_bugfix_reproducer_manifest,
            _evidence(reproducer_manifest={"stack": "pytest"}),
        ),
        ("bugfix.red_evidence", check_bugfix_red_evidence, _evidence(red_exit_code=0)),
        (
            "bugfix.green_evidence",
            check_bugfix_green_evidence,
            _evidence(green_exit_code=1),
        ),
        (
            "bugfix.suite_evidence",
            check_bugfix_suite_evidence,
            _evidence(suite_exit_code=1),
        ),
        (
            "bugfix.red_green_consistency",
            check_bugfix_red_green_consistency,
            _evidence(green_commit_sha="a" * 40),
        ),
        (
            "bugfix.red_green_consistency",
            check_bugfix_red_green_consistency,
            _evidence(green_command="pytest other.py::test_reproducer"),
        ),
    )
    for check_id, check, evidence in cases:
        finding = check(
            ctx, tmp_path, severity=Severity.BLOCKING, port=_Port(evidence)
        )
        _assert_blocking(finding, check_id)


def test_structural_checker_dispatches_bugfix_stages_end_to_end(tmp_path: Path) -> None:
    result = StructuralChecker(registry=StageRegistry()).evaluate(_ctx(), tmp_path)
    checks = {finding.check for finding in result.findings}
    assert {
        "bugfix.reproducer_manifest",
        "bugfix.red_evidence",
        "bugfix.green_evidence",
        "bugfix.suite_evidence",
        "bugfix.red_green_consistency",
    }.issubset(checks)


def test_implementation_story_does_not_run_bugfix_checks(tmp_path: Path) -> None:
    result = StructuralChecker(registry=StageRegistry()).evaluate(
        _ctx(StoryType.IMPLEMENTATION), tmp_path
    )
    assert not any(finding.check.startswith("bugfix.") for finding in result.findings)
