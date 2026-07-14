"""Integration proof for W4 git-adapter and CLI range wiring."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def test_cli_range_exits_one_for_normative_change_without_record(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    concept = repo / "concept" / "technical-design"
    concept.mkdir(parents=True)
    _git(repo, "init")
    _git(repo, "config", "user.name", "W4 Integration")
    _git(repo, "config", "user.email", "w4@example.invalid")
    document = concept / "example.md"
    document.write_text("---\nconcept_id: FK-99\n---\nThe retry is optional.\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "Initial concept")
    base = _git(repo, "rev-parse", "HEAD")
    document.write_text("---\nconcept_id: FK-99\n---\nThe worker must retry.\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "Change retry policy")

    completed = subprocess.run(
        [
            sys.executable,
            str(Path.cwd() / "scripts/ci/check_concept_decision_record.py"),
            "--repo-root",
            str(repo),
            "--base",
            base,
            "--head",
            "HEAD",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 1
    assert "MISSING_DECISION_RECORD" in completed.stdout

    rename_base = _git(repo, "rev-parse", "HEAD")
    decisions = repo / "concept" / "_meta" / "decisions"
    decisions.mkdir(parents=True)
    _git(
        repo,
        "mv",
        "concept/technical-design/example.md",
        "concept/_meta/decisions/2026-07-14-renamed-policy.md",
    )
    _git(repo, "commit", "-m", "Move policy into records")
    renamed = subprocess.run(
        [
            sys.executable,
            str(Path.cwd() / "scripts/ci/check_concept_decision_record.py"),
            "--repo-root",
            str(repo),
            "--base",
            rename_base,
            "--head",
            "HEAD",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert renamed.returncode == 1
    assert "MISSING_DECISION_RECORD" in renamed.stdout
