from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentkit.core_types.qa_artifact_names import (
    HANDOVER_FILE,
    PROTOCOL_FILE,
    WORKER_MANIFEST_FILE,
)
from agentkit.implementation.manifest import WorkerManifest, WorkerManifestStatus
from agentkit.state_backend.store import save_story_context
from agentkit.story_context_manager.models import StoryContext
from agentkit.story_context_manager.types import StoryMode, StoryType
from agentkit.verify_system.protocols import RunScope
from agentkit.verify_system.structural.system_evidence import ChangeEvidence

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.verify_system.system import VerifySystem


class GitDiffChangeEvidencePort:
    """Test port that reads independent git diff evidence from the story worktree."""

    def collect(self, story_dir: Path) -> ChangeEvidence:
        result = subprocess.run(
            ["git", "diff", "--name-only", "origin/main..HEAD"],
            cwd=story_dir,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return ChangeEvidence(available=False)
        return ChangeEvidence(
            available=True,
            changed_files=tuple(
                line.strip() for line in result.stdout.splitlines() if line.strip()
            ),
        )


class StaticStoryContextPort:
    """Test port returning the valid StoryContext produced by the fixture."""

    def __init__(self, ctx: StoryContext, *, run_id: str) -> None:
        self._ctx = ctx
        self._run_id = run_id

    def load(self, story_dir: Path) -> StoryContext:
        del story_dir
        return self._ctx

    def resolve_run_scope(self, story_dir: Path) -> RunScope:
        del story_dir
        return RunScope(
            run_id=self._run_id,
            story_id=self._ctx.story_id,
            attempt=1,
        )


def bind_implementation_qa_preconditions(
    system: VerifySystem,
    story_dir: Path,
    *,
    story_id: str,
    run_id: str,
    project_root: Path | None = None,
) -> VerifySystem:
    """Persist the real implementation QA preconditions and wire read ports."""
    ctx = write_implementation_qa_preconditions(
        story_dir,
        story_id=story_id,
        run_id=run_id,
        project_root=project_root,
    )
    return replace(
        system,
        story_context_port=StaticStoryContextPort(ctx, run_id=run_id),
        implementation_change_evidence_port=GitDiffChangeEvidencePort(),
    )


def write_implementation_qa_preconditions(
    story_dir: Path,
    *,
    story_id: str,
    run_id: str,
    project_root: Path | None = None,
) -> StoryContext:
    """Create the StoryContext and worker delivery artifacts required by AG3-058."""
    story_dir.mkdir(parents=True, exist_ok=True)
    _ensure_git_implementation_change(story_dir)
    ctx = StoryContext(
        project_key="test-project",
        story_id=story_id,
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXECUTION,
        project_root=project_root or story_dir,
    )
    save_story_context(
        story_dir,
        ctx,
    )
    (story_dir / HANDOVER_FILE).write_text(
        json.dumps(
            {
                "changes_summary": "implemented integration test fixture change",
                "increments": [
                    {
                        "description": "test fixture implementation change",
                        "commit_sha": "fixture",
                        "tests_added": ["tests/test_fixture.py"],
                    }
                ],
                "assumptions": [],
                "existing_tests": ["tests/test_fixture.py::test_fixture"],
                "risks_for_qa": [],
                "drift_log": [],
                "acceptance_criteria_status": {"AC-1": "ADDRESSED"},
            }
        ),
        encoding="utf-8",
    )
    (story_dir / PROTOCOL_FILE).write_text(
        "Implementation QA fixture protocol.\n" * 4,
        encoding="utf-8",
    )
    manifest = WorkerManifest(
        story_id=story_id,
        run_id=run_id,
        status=WorkerManifestStatus.COMPLETED,
        completed_at=datetime(2026, 6, 1, tzinfo=UTC),
        commit_sha="fixture",
        files_changed=["src/agentkit/fixture_impl.py"],
        tests_added=["tests/test_fixture.py"],
        acceptance_criteria_status={"AC-1": "ADDRESSED"},
    )
    (story_dir / WORKER_MANIFEST_FILE).write_text(
        manifest.model_dump_json(),
        encoding="utf-8",
    )
    return ctx


def init_git_story_worktree(story_dir: Path) -> None:
    """Initialize a minimal story git worktree with an origin/main baseline."""
    story_dir.mkdir(parents=True, exist_ok=True)
    if _is_git_worktree(story_dir):
        return
    (story_dir / ".ak3-baseline").write_text("baseline\n", encoding="utf-8")
    for args in (
        ["init", "-b", "main"],
        ["config", "user.email", "t@example.com"],
        ["config", "user.name", "Test"],
        ["add", "-f", "."],
        ["commit", "-m", "base"],
        ["update-ref", "refs/remotes/origin/main", "HEAD"],
        ["checkout", "-b", "story-branch"],
    ):
        subprocess.run(
            ["git", *args],
            cwd=story_dir,
            check=True,
            capture_output=True,
            text=True,
        )


def _ensure_git_implementation_change(story_dir: Path) -> None:
    """Commit one implementation file when the fixture repo has no impl diff."""
    if not _is_git_worktree(story_dir):
        return
    existing = _git_output(["diff", "--name-only", "origin/main..HEAD"], story_dir)
    if existing is None:
        return
    if any(_counts_as_implementation_path(line) for line in existing.splitlines()):
        return
    source = story_dir / "src" / "agentkit" / "fixture_impl.py"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("FIXTURE_IMPL = True\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "-f", source.relative_to(story_dir).as_posix()],
        cwd=story_dir,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "test fixture implementation change"],
        cwd=story_dir,
        check=True,
        capture_output=True,
        text=True,
    )


def _is_git_worktree(story_dir: Path) -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=story_dir,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def _git_output(args: list[str], story_dir: Path) -> str | None:
    result = subprocess.run(
        ["git", *args],
        cwd=story_dir,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout


def _counts_as_implementation_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return normalized.startswith("src/") or normalized.endswith(".py")
