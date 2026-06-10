from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from integration import implementation_evidence_support as support


def _git(args: list[str], cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _init_outer_repo(root: Path) -> str:
    root.mkdir(parents=True)
    _git(["init", "-b", "main"], root)
    _git(["config", "user.email", "t@example.com"], root)
    _git(["config", "user.name", "Test"], root)
    (root / ".gitignore").write_text("tmp/\n", encoding="utf-8")
    (root / "README.md").write_text("outer repo\n", encoding="utf-8")
    _git(["add", "."], root)
    _git(["commit", "-m", "base"], root)
    return _git(["rev-parse", "HEAD"], root)


def test_write_preconditions_keeps_nested_tmp_story_commit_out_of_outer_repo(
    tmp_path: Path,
) -> None:
    outer_repo = tmp_path / "outer"
    outer_head = _init_outer_repo(outer_repo)
    story_dir = (
        outer_repo
        / "tmp"
        / "pytest-temproot"
        / "case"
        / "stories"
        / "TEST-001"
    )

    support.write_implementation_qa_preconditions(
        story_dir,
        story_id="TEST-001",
        run_id="run-test-001",
        project_root=tmp_path,
    )

    assert _git(["rev-parse", "HEAD"], outer_repo) == outer_head
    assert _git(["status", "--porcelain"], outer_repo) == ""
    assert Path(_git(["rev-parse", "--show-toplevel"], story_dir)) == story_dir
    assert (
        _git(["log", "--format=%s", "-1"], story_dir)
        == "test fixture implementation change"
    )


def test_write_preconditions_refuses_configured_ak3_repo_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outer_repo = tmp_path / "outer"
    _init_outer_repo(outer_repo)
    monkeypatch.setattr(support, "_AK3_REPO_ROOT", outer_repo.resolve())

    with pytest.raises(RuntimeError, match=support._AK3_COMMIT_REFUSAL):
        support.write_implementation_qa_preconditions(
            outer_repo,
            story_id="TEST-001",
            run_id="run-test-001",
            project_root=tmp_path,
        )
