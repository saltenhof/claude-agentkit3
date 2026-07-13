"""Atomic edge-local closure merge executor (AG3-152, FK-29)."""

from __future__ import annotations

import stat
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
    "candidate_fetch_failed",
    "candidate_mismatch",
    "candidate_not_fast_forward",
    "cas_contention",
    "push_auth_failed",
    "push_timeout",
    "push_failed",
    "push_result_unconfirmed",
    "local_merge_failed",
    "rollback_failed",
    "teardown_failed",
]


class WorktreeIdentityError(RuntimeError):
    """A destructive merge operation could not bind the commanded story worktree."""


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
        _run_git,
    )

    candidate_context = _load_candidate(payload, project_config, project_root)
    if isinstance(candidate_context, MergeLocalReport):
        return candidate_context
    repo_id, repo_root, worktree_path, candidate, locked_sha = candidate_context
    try:
        resolved_worktree = _require_safe_story_worktree(
            repo_root, worktree_path, payload.story_id
        )
    except WorktreeIdentityError as exc:
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
    pre_execution_head = _head_state(resolved_worktree)
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
        head_moved = _head_state(resolved_worktree) != pre_execution_head
        rollback_ok = head_moved and _rollback(
            repo_root, worktree_path, payload.story_id, pre_merge_sha
        )
        return _failure(
            repo_id,
            "local_merge_failed" if rollback_ok or not head_moved else "rollback_failed",
            str(exc),
            locked_sha=locked_sha,
            pre_merge_sha=pre_merge_sha,
            rolled_back=rollback_ok,
        )
    lease = f"--force-with-lease=refs/heads/{payload.base_branch}:{locked_sha}"
    refspec = f"{candidate}:refs/heads/{payload.base_branch}"
    push = _push(resolved_worktree, lease, refspec)
    if push.returncode != 0:
        return _reconcile_failed_push(
            payload,
            repo_id=repo_id,
            repo_root=repo_root,
            worktree_path=worktree_path,
            candidate=candidate,
            locked_sha=locked_sha,
            push=push,
        )
    try:
        _teardown_if_present(repo_root, worktree_path, payload.story_id)
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
        EdgeGitError,
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
        return _failure(repo_id, "candidate_fetch_failed", _git_detail(fetch))
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
        try:
            _teardown_if_present(repo_root, worktree_path, payload.story_id)
        except WorktreeIdentityError as exc:
            return _failure(
                repo_id,
                "worktree_identity_invalid",
                str(exc),
                locked_sha=locked_sha,
            )
        except EdgeGitError as exc:
            return _success(
                repo_id,
                "already_merged",
                candidate,
                locked_sha,
                detail=f"main already merged; teardown remains retryable: {exc}",
            )
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
    return (
        _run_git(
            repo_root, "merge-base", "--is-ancestor", ancestor, descendant
        ).returncode
        == 0
    )


def _rollback(
    repo_root: Path, worktree_path: Path, story_id: str, pre_merge_sha: str
) -> bool:
    from agentkit.harness_client.projectedge.command_executor import _run_git

    try:
        resolved = _require_safe_story_worktree(repo_root, worktree_path, story_id)
    except WorktreeIdentityError:
        return False
    branch = _run_git(resolved, "symbolic-ref", "-q", "--short", "HEAD")
    if branch.returncode == 0:
        return False
    return _run_git(resolved, "reset", "--hard", pre_merge_sha).returncode == 0


def _teardown_if_present(
    repo_root: Path, worktree_path: Path, story_id: str
) -> None:
    from agentkit.harness_client.projectedge.command_executor import (
        EdgeGitError,
        _require_git,
        _run_git,
    )

    _require_safe_worktrees_root(repo_root)
    if _path_is_link_or_junction(worktree_path):
        raise WorktreeIdentityError(
            "merge_local refuses to follow a symlinked or junction worktree path"
        )
    if not worktree_path.exists():
        return
    resolved = _require_safe_story_worktree(repo_root, worktree_path, story_id)
    _require_git(
        _run_git(repo_root, "worktree", "remove", "--force", str(resolved)),
        "worktree remove after merge",
    )
    branch = _run_git(repo_root, "branch", "-D", f"story/{story_id}")
    if branch.returncode not in (0, 1):
        raise EdgeGitError(_git_detail(branch))


def _require_safe_story_worktree(
    repo_root: Path, worktree_path: Path, story_id: str
) -> Path:
    """Bind a destructive operation to the commanded linked story worktree."""
    from agentkit.harness_client.projectedge.command_executor import (
        EdgeGitError,
        _read_story_marker,
        _require_registered_linked_worktree,
    )

    _require_safe_worktrees_root(repo_root)
    if _path_is_link_or_junction(worktree_path):
        raise WorktreeIdentityError(
            "merge_local refuses to follow a symlinked or junction worktree path"
        )
    if not worktree_path.is_dir():
        raise WorktreeIdentityError("the commanded story worktree is absent")
    try:
        resolved = worktree_path.resolve(strict=True)
        _require_registered_linked_worktree(repo_root, resolved)
    except (OSError, RuntimeError, EdgeGitError) as exc:
        raise WorktreeIdentityError(str(exc)) from exc
    marker = _read_story_marker(resolved)
    if marker is None or marker.get("story_id") != story_id:
        raise WorktreeIdentityError(
            "the linked worktree marker does not match the commanded story"
        )
    return resolved


def _require_safe_worktrees_root(repo_root: Path) -> None:
    """Refuse a symlink or junction at the repository worktrees root."""
    if _path_is_link_or_junction(repo_root / "worktrees"):
        raise WorktreeIdentityError(
            "merge_local refuses a symlinked or junction worktrees root"
        )


def _path_is_link_or_junction(path: Path) -> bool:
    """Return whether ``path`` is a symlink or Windows reparse-point junction."""
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except OSError:
        attributes = 0
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return path.is_symlink() or bool(attributes & reparse_flag)


def _head_state(worktree_path: Path) -> tuple[str, str | None]:
    """Capture the current commit and attached branch before local merge work."""
    from agentkit.harness_client.projectedge.command_executor import _run_git

    head = _run_git(worktree_path, "rev-parse", "HEAD")
    branch = _run_git(worktree_path, "symbolic-ref", "-q", "--short", "HEAD")
    return (
        head.stdout.strip() if head.returncode == 0 else "",
        branch.stdout.strip() if branch.returncode == 0 else None,
    )


def _reconcile_failed_push(
    payload: MergeLocalCommandPayload,
    *,
    repo_id: str,
    repo_root: Path,
    worktree_path: Path,
    candidate: str,
    locked_sha: str,
    push: subprocess.CompletedProcess[str],
) -> MergeLocalReport:
    """Re-fetch remote main before classifying an ambiguous push result."""
    from agentkit.harness_client.projectedge.command_executor import EdgeGitError, _run_git

    fetch = _run_git(repo_root, "fetch", "origin", payload.base_branch)
    if fetch.returncode != 0:
        return _failure(
            repo_id,
            "push_result_unconfirmed",
            "main-update push failed and remote main could not be reconciled; "
            "no rollback is claimed",
            locked_sha=locked_sha,
            pre_merge_sha=locked_sha,
        )
    remote_sha = _read_sha(repo_root, f"refs/remotes/origin/{payload.base_branch}")
    if _is_ancestor(repo_root, candidate, remote_sha):
        detail = "main contains the candidate after an ambiguous push result"
        try:
            _teardown_if_present(repo_root, worktree_path, payload.story_id)
        except (WorktreeIdentityError, EdgeGitError) as exc:
            detail = f"{detail}; teardown remains retryable: {exc}"
        return _success(
            repo_id,
            "already_merged",
            candidate,
            locked_sha,
            pre_merge_sha=locked_sha,
            detail=detail,
        )
    rollback_ok = _rollback(repo_root, worktree_path, payload.story_id, locked_sha)
    if not rollback_ok:
        return _failure(
            repo_id,
            "rollback_failed",
            "main-update push failed and the detached local merge could not be rolled back",
            locked_sha=locked_sha,
            pre_merge_sha=locked_sha,
        )
    if remote_sha != locked_sha:
        code: FailureCode = "cas_contention"
        detail = (
            "remote main changed and rejected the atomic lease; "
            "local merge was rolled back"
        )
    else:
        code = _push_failure_code(push)
        detail = f"main-update push failed without advancing remote main: {_git_detail(push)}"
    return _failure(
        repo_id,
        code,
        detail,
        locked_sha=locked_sha,
        pre_merge_sha=locked_sha,
        rolled_back=True,
    )


def _push_failure_code(push: subprocess.CompletedProcess[str]) -> FailureCode:
    """Classify a confirmed-unapplied push without changing push credentials."""
    detail = _git_detail(push).lower()
    if push.returncode == 124 or "timed out" in detail or "timeout" in detail:
        return "push_timeout"
    auth_tokens = ("authentication", "permission denied", "could not read username")
    if any(token in detail for token in auth_tokens):
        return "push_auth_failed"
    return "push_failed"


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
