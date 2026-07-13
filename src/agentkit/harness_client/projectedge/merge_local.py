"""Atomic edge-local closure merge executor (AG3-152, FK-29)."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING, Literal

from agentkit.backend.control_plane.models import (
    MergeLocalCommandPayload,
    MergeLocalRepoReport,
    MergeLocalReport,
)

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.config.models import ProjectConfig

FailureCode = Literal[
    "multi_repo_not_supported",
    "worktree_identity_invalid",
    "candidate_mismatch",
    "candidate_not_fast_forward",
    "cas_contention",
    "local_merge_failed",
    "rollback_failed",
    "teardown_failed",
]


def execute_merge_local(
    payload: MergeLocalCommandPayload,
    *,
    project_config: ProjectConfig,
    project_root: Path,
) -> MergeLocalReport:
    """Execute one idempotent single-repo ff+CAS+rollback+teardown sequence."""
    from agentkit.harness_client.projectedge.command_executor import (
        EdgeGitError,
        _require_git,
        _require_registered_linked_worktree,
        _run_git,
    )

    candidate_context = _load_candidate(payload, project_config, project_root)
    if isinstance(candidate_context, MergeLocalReport):
        return candidate_context
    repo_id, repo_root, worktree_path, candidate, locked_sha = candidate_context
    if not worktree_path.is_dir() or worktree_path.is_symlink():
        return _failure(
            repo_id,
            "worktree_identity_invalid",
            "the registered linked story worktree is absent or unsafe",
            locked_sha=locked_sha,
        )
    try:
        resolved_worktree = worktree_path.resolve(strict=True)
        _require_registered_linked_worktree(repo_root, resolved_worktree)
    except (OSError, RuntimeError) as exc:
        return _failure(
            repo_id, "worktree_identity_invalid", str(exc), locked_sha=locked_sha
        )
    if not _is_ancestor(repo_root, locked_sha, candidate):
        return _failure(
            repo_id,
            "candidate_not_fast_forward",
            "the gated story candidate does not contain the freshly locked main",
            locked_sha=locked_sha,
        )
    pre_merge_sha = locked_sha
    try:
        _require_git(
            _run_git(resolved_worktree, "checkout", "--detach", locked_sha),
            "checkout locked main",
        )
        _require_git(
            _run_git(resolved_worktree, "merge", "--ff-only", candidate),
            "ff-only merge gated candidate",
        )
    except EdgeGitError as exc:
        rollback_ok = _rollback(repo_root, resolved_worktree, pre_merge_sha)
        return _failure(
            repo_id,
            "local_merge_failed" if rollback_ok else "rollback_failed",
            str(exc),
            locked_sha=locked_sha,
            pre_merge_sha=pre_merge_sha,
            rolled_back=rollback_ok,
        )
    lease = f"--force-with-lease=refs/heads/{payload.base_branch}:{locked_sha}"
    refspec = f"{candidate}:refs/heads/{payload.base_branch}"
    push = _push(resolved_worktree, lease, refspec)
    if push.returncode != 0:
        rollback_ok = _rollback(repo_root, resolved_worktree, pre_merge_sha)
        return _failure(
            repo_id,
            "cas_contention" if rollback_ok else "rollback_failed",
            "atomic main-update lease was rejected; local merge was rolled back",
            locked_sha=locked_sha,
            pre_merge_sha=pre_merge_sha,
            rolled_back=rollback_ok,
        )
    try:
        _teardown_if_present(repo_root, resolved_worktree, payload.story_id)
    except EdgeGitError as exc:
        return _success(
            repo_id,
            "merged",
            candidate,
            locked_sha,
            pre_merge_sha=pre_merge_sha,
            detail=f"main merged; teardown remains retryable: {exc}",
        )
    return _success(
        repo_id, "merged", candidate, locked_sha, pre_merge_sha=pre_merge_sha
    )


def _load_candidate(
    payload: MergeLocalCommandPayload,
    project_config: ProjectConfig,
    project_root: Path,
) -> tuple[str, Path, Path, str, str] | MergeLocalReport:
    """Fetch and bind the single-repository candidate, including replay."""
    from agentkit.harness_client.projectedge.command_executor import (
        _resolve_repo_root,
        _run_git,
    )

    if len(payload.repositories) != 1:
        return _failure(
            payload.repositories[0].repo_id,
            "multi_repo_not_supported",
            "merge_local preserves the productive >=2-repository fail-closed boundary",
        )
    repo_id = payload.repositories[0].repo_id
    repo_root = _resolve_repo_root(project_config, project_root, repo_id)
    worktree_path = repo_root / "worktrees" / payload.story_id
    story_ref = f"refs/remotes/origin/story/{payload.story_id}"
    base_ref = f"refs/remotes/origin/{payload.base_branch}"
    fetch = _run_git(
        repo_root, "fetch", "origin", payload.base_branch, f"story/{payload.story_id}"
    )
    if fetch.returncode != 0:
        return _failure(repo_id, "candidate_mismatch", _git_detail(fetch))
    candidate = _read_sha(repo_root, story_ref)
    candidate_tree = _read_sha(repo_root, f"{story_ref}^{{tree}}")
    locked_sha = _read_sha(repo_root, base_ref)
    if (
        candidate != payload.expected_candidate_commit
        or candidate_tree != payload.expected_candidate_tree_hash
    ):
        return _failure(
            repo_id,
            "candidate_mismatch",
            "the pushed story ref does not match the gated candidate commit/tree",
            locked_sha=locked_sha,
        )
    if _is_ancestor(repo_root, candidate, locked_sha):
        _teardown_if_present(repo_root, worktree_path, payload.story_id)
        return _success(repo_id, "already_merged", candidate, locked_sha)
    return repo_id, repo_root, worktree_path, candidate, locked_sha


def _read_sha(repo_root: Path, ref: str) -> str:
    from agentkit.harness_client.projectedge.command_executor import _run_git

    result = _run_git(repo_root, "rev-parse", ref)
    return result.stdout.strip() if result.returncode == 0 else ""


def _is_ancestor(repo_root: Path, ancestor: str, descendant: str) -> bool:
    from agentkit.harness_client.projectedge.command_executor import _run_git

    if not ancestor or not descendant:
        return False
    return _run_git(repo_root, "merge-base", "--is-ancestor", ancestor, descendant).returncode == 0


def _rollback(repo_root: Path, worktree_path: Path, pre_merge_sha: str) -> bool:
    from agentkit.harness_client.projectedge.command_executor import (
        EdgeGitError,
        _require_registered_linked_worktree,
        _run_git,
    )

    try:
        _require_registered_linked_worktree(repo_root, worktree_path)
    except EdgeGitError:
        return False
    return _run_git(worktree_path, "reset", "--hard", pre_merge_sha).returncode == 0


def _teardown_if_present(
    repo_root: Path, worktree_path: Path, story_id: str
) -> None:
    from agentkit.harness_client.projectedge.command_executor import (
        EdgeGitError,
        _require_git,
        _require_registered_linked_worktree,
        _run_git,
    )

    if worktree_path.exists():
        resolved = worktree_path.resolve(strict=True)
        _require_registered_linked_worktree(repo_root, resolved)
        _require_git(
            _run_git(repo_root, "worktree", "remove", "--force", str(resolved)),
            "worktree remove after merge",
        )
    else:
        _run_git(repo_root, "worktree", "prune")
    branch = _run_git(repo_root, "branch", "-D", f"story/{story_id}")
    if branch.returncode not in (0, 1):
        raise EdgeGitError(_git_detail(branch))


def _push(worktree_path: Path, lease: str, refspec: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", "-C", str(worktree_path), "push", lease, "origin", refspec],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(exc.cmd, 124, "", "push timed out")


def _success(
    repo_id: str,
    outcome: Literal["merged", "already_merged"],
    merged_sha: str,
    locked_sha: str,
    *,
    pre_merge_sha: str | None = None,
    detail: str = "",
) -> MergeLocalReport:
    return MergeLocalReport(
        outcome=outcome,
        escalated=False,
        merged_main_sha=merged_sha,
        detail=detail,
        repositories=[
            MergeLocalRepoReport(
                repo_id=repo_id,
                outcome=outcome,
                pushed=True,
                merged=True,
                locked_sha=locked_sha,
                pre_merge_sha=pre_merge_sha,
                merged_main_sha=merged_sha,
            )
        ],
    )


def _failure(
    repo_id: str,
    code: FailureCode,
    detail: str,
    *,
    locked_sha: str | None = None,
    pre_merge_sha: str | None = None,
    rolled_back: bool = False,
) -> MergeLocalReport:
    return MergeLocalReport(
        outcome="escalated",
        escalated=True,
        failure_code=code,
        detail=detail,
        repositories=[
            MergeLocalRepoReport(
                repo_id=repo_id,
                outcome="rolled_back" if rolled_back else "failed",
                rolled_back=rolled_back,
                locked_sha=locked_sha,
                pre_merge_sha=pre_merge_sha,
            )
        ],
    )


def _git_detail(result: subprocess.CompletedProcess[str]) -> str:
    return result.stderr.strip() or result.stdout.strip() or f"git exited {result.returncode}"
