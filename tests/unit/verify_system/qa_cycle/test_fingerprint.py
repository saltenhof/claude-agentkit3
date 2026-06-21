"""Unit tests for the deterministic evidence fingerprint (FK-27 §27.2.1).

Proves AG3-041 AC3: same code-state -> same hash; changed code -> different
hash; fail-closed when git is unavailable. A real (throwaway) git repo is
created in ``tmp_path`` so the ``git diff origin/main..HEAD`` invocation is
exercised against a genuine boundary (no subprocess mock).
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.verify_system.qa_cycle.fingerprint import (
    FingerprintComputationError,
    compute_evidence_fingerprint,
)

if TYPE_CHECKING:
    from pathlib import Path

_SHA256_HEX_LEN = 64


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _init_repo_with_branch(root: Path) -> None:
    """Init a repo, commit a baseline on ``main``, branch off, add a change.

    ``origin/main`` is faked by creating a local ``main`` ref the diff base
    can resolve via the same range syntax used in production.
    """
    _git(["init", "-b", "main"], root)
    _git(["config", "user.email", "t@example.com"], root)
    _git(["config", "user.name", "Test"], root)
    (root / "base.py").write_text("x = 1\n", encoding="utf-8")
    _git(["add", "."], root)
    _git(["commit", "-m", "base"], root)
    # Simulate origin/main as a tracking-like ref pointing at the baseline.
    _git(["update-ref", "refs/remotes/origin/main", "HEAD"], root)
    _git(["checkout", "-b", "story-branch"], root)
    (root / "feature.py").write_text("y = 2\n", encoding="utf-8")
    _git(["add", "."], root)
    _git(["commit", "-m", "feature"], root)


class TestFingerprintDeterminism:
    def test_same_code_state_same_hash(self, tmp_path: Path) -> None:
        _init_repo_with_branch(tmp_path)
        first = compute_evidence_fingerprint(tmp_path)
        second = compute_evidence_fingerprint(tmp_path)
        assert first == second
        assert len(first) == _SHA256_HEX_LEN
        assert all(c in "0123456789abcdef" for c in first)

    def test_changed_code_changes_hash(self, tmp_path: Path) -> None:
        _init_repo_with_branch(tmp_path)
        before = compute_evidence_fingerprint(tmp_path)
        (tmp_path / "feature.py").write_text("y = 999\n", encoding="utf-8")
        _git(["add", "."], tmp_path)
        _git(["commit", "-m", "change"], tmp_path)
        after = compute_evidence_fingerprint(tmp_path)
        assert before != after

    def test_handover_json_contributes(self, tmp_path: Path) -> None:
        _init_repo_with_branch(tmp_path)
        without = compute_evidence_fingerprint(tmp_path)
        (tmp_path / "handover.json").write_text('{"k": "v"}', encoding="utf-8")
        with_handover = compute_evidence_fingerprint(tmp_path)
        assert without != with_handover


class TestFingerprintCapturesWorkingTree:
    """AG3-041 E8: the fingerprint reflects the FULL current code state."""

    def test_untracked_file_changes_hash(self, tmp_path: Path) -> None:
        """An untracked (uncommitted, new) file must change the fingerprint."""
        _init_repo_with_branch(tmp_path)
        before = compute_evidence_fingerprint(tmp_path)
        (tmp_path / "scratch.py").write_text("z = 3\n", encoding="utf-8")
        after = compute_evidence_fingerprint(tmp_path)
        assert before != after

    def test_working_tree_modification_changes_hash(self, tmp_path: Path) -> None:
        """An uncommitted modification to a tracked file changes the hash."""
        _init_repo_with_branch(tmp_path)
        before = compute_evidence_fingerprint(tmp_path)
        # Modify a committed file WITHOUT committing.
        (tmp_path / "feature.py").write_text("y = 42\n", encoding="utf-8")
        after = compute_evidence_fingerprint(tmp_path)
        assert before != after

    def test_deterministic_with_untracked(self, tmp_path: Path) -> None:
        """Same working-tree state (incl. untracked) -> same hash."""
        _init_repo_with_branch(tmp_path)
        (tmp_path / "scratch.py").write_text("z = 3\n", encoding="utf-8")
        first = compute_evidence_fingerprint(tmp_path)
        second = compute_evidence_fingerprint(tmp_path)
        assert first == second

    def test_uncommitted_deletion_changes_hash(self, tmp_path: Path) -> None:
        """ER2: a working-tree deletion of a tracked file changes the hash.

        Regression for the fail-open where a deleted path dropped silently
        out of the file section (``_hash_file`` -> ``None``) so the
        fingerprint stayed unchanged and stale QA evidence appeared valid. A
        deletion MUST move the fingerprint (tombstone line, fail-closed).
        """
        _init_repo_with_branch(tmp_path)
        before = compute_evidence_fingerprint(tmp_path)
        # Delete a committed file in the working tree WITHOUT committing.
        (tmp_path / "feature.py").unlink()
        after = compute_evidence_fingerprint(tmp_path)
        assert before != after

    def test_uncommitted_deletion_is_deterministic(self, tmp_path: Path) -> None:
        """ER2: the same deletion yields the same tombstone-based hash."""
        _init_repo_with_branch(tmp_path)
        (tmp_path / "feature.py").unlink()
        first = compute_evidence_fingerprint(tmp_path)
        second = compute_evidence_fingerprint(tmp_path)
        assert first == second


class TestFingerprintFailClosed:
    def test_unresolvable_diff_base_raises(self, tmp_path: Path) -> None:
        """An unresolvable git ref -> fail-closed (no weak-signal fallback)."""
        _init_repo_with_branch(tmp_path)
        with pytest.raises(FingerprintComputationError):
            compute_evidence_fingerprint(
                tmp_path, diff_base="refs/does-not-exist-xyz"
            )
