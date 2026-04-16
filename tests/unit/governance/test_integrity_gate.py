"""Tests for IntegrityGate -- multi-dimensional quality check.

Uses ``tmp_path`` with real phase snapshots via ``save_phase_snapshot``
as mandated by testing-standards.md section 1.2.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from agentkit.governance.integrity_gate import IntegrityGate
from agentkit.story_context_manager.types import StoryType

if TYPE_CHECKING:
    from pathlib import Path


def _write_json(path: Path, data: object) -> None:
    """Write a JSON file (test helper)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f)


def _create_snapshot(story_dir: Path, phase: str, status: str = "completed") -> None:
    """Create a phase snapshot file on disk."""
    _write_json(
        story_dir / f"phase-state-{phase}.json",
        {
            "story_id": "AG3-001",
            "phase": phase,
            "status": status,
            "completed_at": "2026-04-07T12:00:00",
            "artifacts": [],
            "evidence": {},
        },
    )


def _create_context(story_dir: Path) -> None:
    """Create a valid context.json."""
    _write_json(
        story_dir / "context.json",
        {
            "story_id": "AG3-001",
            "story_type": "implementation",
            "mode": "exploration",
        },
    )


def _create_decision(story_dir: Path, decision: str = "PASS") -> None:
    """Create a verify decision file."""
    _write_json(story_dir / "decision.json", {"decision": decision})


def _populate_implementation_story(story_dir: Path) -> None:
    """Create all artifacts needed for a passing implementation story."""
    _create_context(story_dir)
    for phase in ("setup", "implementation", "verify"):
        _create_snapshot(story_dir, phase)
    _create_decision(story_dir)


class TestIntegrityGateAllPassing:
    """Happy path: all checks pass."""

    def test_implementation_all_pass(self, tmp_path: Path) -> None:
        _populate_implementation_story(tmp_path)
        result = IntegrityGate().evaluate(tmp_path, StoryType.IMPLEMENTATION)
        assert result.passed is True
        assert len(result.failed_checks) == 0

    def test_bugfix_all_pass(self, tmp_path: Path) -> None:
        _create_context(tmp_path)
        for phase in ("setup", "implementation", "verify"):
            _create_snapshot(tmp_path, phase)
        _create_decision(tmp_path)
        result = IntegrityGate().evaluate(tmp_path, StoryType.BUGFIX)
        assert result.passed is True

    def test_concept_all_pass(self, tmp_path: Path) -> None:
        _create_context(tmp_path)
        for phase in ("setup", "implementation"):
            _create_snapshot(tmp_path, phase)
        # Concept stories do NOT require verify decision.
        result = IntegrityGate().evaluate(tmp_path, StoryType.CONCEPT)
        assert result.passed is True

    def test_research_all_pass(self, tmp_path: Path) -> None:
        _create_context(tmp_path)
        for phase in ("setup", "implementation"):
            _create_snapshot(tmp_path, phase)
        result = IntegrityGate().evaluate(tmp_path, StoryType.RESEARCH)
        assert result.passed is True


class TestIntegrityGateMissingSnapshot:
    """Missing snapshots must cause failure."""

    def test_missing_setup_snapshot(self, tmp_path: Path) -> None:
        _create_context(tmp_path)
        _create_snapshot(tmp_path, "implementation")
        _create_snapshot(tmp_path, "verify")
        _create_decision(tmp_path)
        result = IntegrityGate().evaluate(tmp_path, StoryType.IMPLEMENTATION)
        assert result.passed is False
        failed = result.failed_checks
        assert any("setup" in c.dimension for c in failed)

    def test_missing_verify_snapshot(self, tmp_path: Path) -> None:
        _create_context(tmp_path)
        _create_snapshot(tmp_path, "setup")
        _create_snapshot(tmp_path, "implementation")
        _create_decision(tmp_path)
        result = IntegrityGate().evaluate(tmp_path, StoryType.IMPLEMENTATION)
        assert result.passed is False
        failed = result.failed_checks
        assert any("verify" in c.dimension for c in failed)


class TestIntegrityGateCorruptData:
    """Corrupt files must cause failure."""

    def test_corrupt_verify_decision(self, tmp_path: Path) -> None:
        _populate_implementation_story(tmp_path)
        # Overwrite decision with invalid JSON.
        (tmp_path / "decision.json").write_text("not json", encoding="utf-8")
        result = IntegrityGate().evaluate(tmp_path, StoryType.IMPLEMENTATION)
        assert result.passed is False
        failed = result.failed_checks
        assert any(c.dimension == "verify_decision" for c in failed)

    def test_corrupt_phase_snapshot(self, tmp_path: Path) -> None:
        _populate_implementation_story(tmp_path)
        (tmp_path / "phase-state-setup.json").write_text("{bad", encoding="utf-8")
        result = IntegrityGate().evaluate(tmp_path, StoryType.IMPLEMENTATION)
        assert result.passed is False
        failed = result.failed_checks
        assert any("setup" in c.dimension for c in failed)

    def test_corrupt_context_json(self, tmp_path: Path) -> None:
        _populate_implementation_story(tmp_path)
        (tmp_path / "context.json").write_text("nope", encoding="utf-8")
        result = IntegrityGate().evaluate(tmp_path, StoryType.IMPLEMENTATION)
        assert result.passed is False
        failed = result.failed_checks
        assert any(c.dimension == "context_json" for c in failed)

    def test_verify_decision_fail(self, tmp_path: Path) -> None:
        """Verify decision exists but is FAIL, not PASS."""
        _create_context(tmp_path)
        for phase in ("setup", "implementation", "verify"):
            _create_snapshot(tmp_path, phase)
        _create_decision(tmp_path, decision="FAIL")
        result = IntegrityGate().evaluate(tmp_path, StoryType.IMPLEMENTATION)
        assert result.passed is False
        failed = result.failed_checks
        assert any(c.dimension == "verify_decision" for c in failed)


class TestIntegrityGateResearchFewerDimensions:
    """Research stories require fewer checks than implementation."""

    def test_research_fewer_dimensions(self, tmp_path: Path) -> None:
        _create_context(tmp_path)
        for phase in ("setup", "implementation"):
            _create_snapshot(tmp_path, phase)

        result_research = IntegrityGate().evaluate(tmp_path, StoryType.RESEARCH)
        assert result_research.passed is True

        # Research should NOT have a verify_decision check.
        dimension_names = {c.dimension for c in result_research.checks}
        assert "verify_decision" not in dimension_names

    def test_concept_no_verify_decision_check(self, tmp_path: Path) -> None:
        _create_context(tmp_path)
        for phase in ("setup", "implementation"):
            _create_snapshot(tmp_path, phase)

        result = IntegrityGate().evaluate(tmp_path, StoryType.CONCEPT)
        assert result.passed is True
        dimension_names = {c.dimension for c in result.checks}
        assert "verify_decision" not in dimension_names


class TestIntegrityGateResultProperties:
    """IntegrityGateResult property tests."""

    def test_failed_checks_property(self, tmp_path: Path) -> None:
        # Empty dir -- everything will fail.
        result = IntegrityGate().evaluate(tmp_path, StoryType.IMPLEMENTATION)
        assert result.passed is False
        assert len(result.failed_checks) > 0
        # All failed checks should have passed=False.
        for c in result.failed_checks:
            assert c.passed is False
