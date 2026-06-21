from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from agentkit.backend.core_types.qa_artifact_names import (
    HANDOVER_FILE,
    PROTOCOL_FILE,
    WORKER_MANIFEST_FILE,
)
from agentkit.backend.implementation.manifest import WorkerManifest, WorkerManifestStatus
from agentkit.backend.state_backend.store import save_story_context
from agentkit.backend.story_context_manager.models import StoryContext
from agentkit.backend.story_context_manager.types import StoryMode, StoryType
from agentkit.backend.verify_system.protocols import RunScope
from agentkit.backend.verify_system.structural.system_evidence import ChangeEvidence

if TYPE_CHECKING:
    from agentkit.backend.verify_system.system import VerifySystem


_AK3_REPO_ROOT = Path(__file__).resolve().parents[2]
_AK3_COMMIT_REFUSAL = (
    "integration fixture refused to git-commit into the AK3 repository"
)


class GitDiffChangeEvidencePort:
    """Test port that reads independent git diff evidence from the story worktree."""

    def collect(self, story_dir: Path) -> ChangeEvidence:
        story_toplevel = _isolated_story_toplevel(story_dir)
        if story_toplevel is None:
            return ChangeEvidence(available=False)
        result = subprocess.run(
            ["git", "diff", "--name-only", "origin/main..HEAD"],
            cwd=story_toplevel,
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
        files_changed=["src/agentkit/backend/fixture_impl.py"],
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
    _refuse_ak3_story_dir(story_dir)
    existing_toplevel = _git_toplevel(story_dir)
    if existing_toplevel is not None and _same_path(existing_toplevel, story_dir):
        _refuse_ak3_git_toplevel(existing_toplevel)
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
    initialized_toplevel = _git_toplevel(story_dir)
    if initialized_toplevel is None or not _same_path(initialized_toplevel, story_dir):
        msg = f"integration fixture failed to initialize isolated git repo at {story_dir}"
        raise RuntimeError(msg)
    _refuse_ak3_git_toplevel(initialized_toplevel)


def _ensure_git_implementation_change(story_dir: Path) -> None:
    """Commit one implementation file when the fixture repo has no impl diff."""
    init_git_story_worktree(story_dir)
    story_toplevel = _require_isolated_story_toplevel(story_dir)
    existing = _git_output(["diff", "--name-only", "origin/main..HEAD"], story_toplevel)
    if existing is None:
        msg = "integration fixture story git repo has no origin/main baseline"
        raise RuntimeError(msg)
    if any(_counts_as_implementation_path(line) for line in existing.splitlines()):
        return
    source = story_toplevel / "src" / "agentkit" / "fixture_impl.py"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("FIXTURE_IMPL = True\n", encoding="utf-8")
    commit_toplevel = _require_isolated_story_toplevel(story_dir)
    _refuse_ak3_git_toplevel(commit_toplevel)
    subprocess.run(
        ["git", "add", "-f", source.relative_to(commit_toplevel).as_posix()],
        cwd=commit_toplevel,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "test fixture implementation change"],
        cwd=commit_toplevel,
        check=True,
        capture_output=True,
        text=True,
    )


def _isolated_story_toplevel(story_dir: Path) -> Path | None:
    toplevel = _git_toplevel(story_dir)
    if toplevel is None:
        return None
    _refuse_ak3_git_toplevel(toplevel)
    if not _same_path(toplevel, story_dir):
        return None
    return toplevel


def _require_isolated_story_toplevel(story_dir: Path) -> Path:
    toplevel = _git_toplevel(story_dir)
    if toplevel is None:
        msg = f"integration fixture story directory is not a git worktree: {story_dir}"
        raise RuntimeError(msg)
    _refuse_ak3_git_toplevel(toplevel)
    if not _same_path(toplevel, story_dir):
        msg = f"integration fixture git toplevel is not story_dir: {toplevel}"
        raise RuntimeError(msg)
    return toplevel


def _git_toplevel(story_dir: Path) -> Path | None:
    if not story_dir.exists():
        return None
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=story_dir,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return Path(result.stdout.strip()).resolve()


def _refuse_ak3_story_dir(story_dir: Path) -> None:
    if _same_path(story_dir, _AK3_REPO_ROOT):
        raise RuntimeError(_AK3_COMMIT_REFUSAL)


def _refuse_ak3_git_toplevel(toplevel: Path) -> None:
    if _same_path(toplevel, _AK3_REPO_ROOT):
        raise RuntimeError(_AK3_COMMIT_REFUSAL)


def _same_path(left: Path, right: Path) -> bool:
    return left.resolve() == right.resolve()


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
