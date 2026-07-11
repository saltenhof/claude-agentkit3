"""Edge-side takeover worktree reconciliation (FK-56 §56.13e, AG3-151).

Blood-type T with a thin R result boundary. The executor verifies the local
worktree identity from its canonical path plus ``.agentkit-story.json``. A
matching clean worktree at ``takeover_base_sha`` is already reconciled. Local
writes in that same verified worktree are moved through the shared atomic
quarantine implementation before the existing provision executor recreates the
path from the takeover base. Git stash and salvage are deliberately absent.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from agentkit.backend.control_plane.models import (
    ProvisionWorktreeCommandPayload,
    TakeoverErrorResult,
    TakeoverQuarantineDetail,
    TakeoverReconcileCommandPayload,
    WorktreeReport,
)
from agentkit.harness_client.projectedge.quarantine import quarantine_worktree

if TYPE_CHECKING:
    from collections.abc import Callable

    from agentkit.backend.config.models import ProjectConfig

_STORY_MARKER_FILENAME = ".agentkit-story.json"


@dataclass(frozen=True)
class TakeoverReconcileExecution:
    """One repo's typed reconcile report plus optional local quarantine audit."""

    result: WorktreeReport | TakeoverErrorResult
    quarantine_detail: TakeoverQuarantineDetail | None = None


def execute_takeover_reconcile(
    payload: TakeoverReconcileCommandPayload,
    *,
    project_config: ProjectConfig,
    project_root: Path,
    now_provider: Callable[[], datetime] | None = None,
) -> TakeoverReconcileExecution:
    """Reconcile one commissioned repo against its immutable takeover base.

    The physical repo path is resolved exclusively from local project config.
    A verified same-worktree identity with local drift is quarantined and then
    reprovisioned. Missing or ambiguous identity is reported as contested
    without moving an unverified directory.
    """
    from agentkit.harness_client.projectedge.command_executor import (
        EdgeGitError,
        _require_git,
        _resolve_repo_root,
        _run_git,
    )

    repo_root = _resolve_repo_root(project_config, project_root, payload.repo_id)
    worktree_path = repo_root / "worktrees" / payload.story_id
    branch = f"story/{payload.story_id}"
    provision_payload = ProvisionWorktreeCommandPayload(
        story_id=payload.story_id,
        project_key=payload.project_key,
        run_id=payload.run_id,
        repo_id=payload.repo_id,
        branch=branch,
        base_ref=payload.takeover_base_sha,
    )

    if not worktree_path.exists():
        return _provision_missing_target(
            payload,
            provision_payload=provision_payload,
            project_config=project_config,
            project_root=project_root,
            repo_root=repo_root,
            worktree_path=worktree_path,
            branch=branch,
        )

    marker = _read_marker(worktree_path)
    marker_state = _classify_marker(marker, payload=payload)
    if marker_state == "ambiguous":
        if _is_reprovision_remnant(
            repo_root,
            worktree_path,
            branch=branch,
            takeover_base_sha=payload.takeover_base_sha,
        ):
            return _provision_missing_target(
                payload,
                provision_payload=provision_payload,
                project_config=project_config,
                project_root=project_root,
                repo_root=repo_root,
                worktree_path=worktree_path,
                branch=branch,
                remove_remnant=True,
            )
        return _error(
            payload,
            "contested_local_writes",
            "worktree identity is ambiguous: marker and canonical path do not match",
        )
    if not _registered_at_canonical_path(repo_root, worktree_path):
        return _error(
            payload,
            "contested_local_writes",
            "worktree identity is ambiguous: canonical path is not git-registered",
        )

    head = _run_git(worktree_path, "rev-parse", "HEAD")
    try:
        _require_git(head, "rev-parse HEAD")
        clean = _has_no_local_writes(worktree_path)
    except EdgeGitError as exc:
        return _error(payload, "contested_local_writes", str(exc))
    head_sha = head.stdout.strip()
    if marker_state == "current" and clean and head_sha == payload.takeover_base_sha:
        return TakeoverReconcileExecution(
            result=WorktreeReport(
                repo_id=payload.repo_id,
                outcome="no_op",
                worktree_root=str(worktree_path),
                branch=branch,
                head_sha=head_sha,
                marker_present=True,
            )
        )

    quarantine_store = (
        project_root.parent / ".agentkit-quarantine" / project_root.name
    )
    reason = (
        "stale takeover target identity"
        if marker_state == "stale"
        else "verified takeover worktree contains local writes or SHA drift"
    )
    try:
        quarantined = quarantine_worktree(
            source_root=worktree_path,
            quarantine_store=quarantine_store,
            reason=reason,
            now=(now_provider or (lambda: datetime.now(UTC)))(),
        )
    except (OSError, ValueError) as exc:
        return _error(payload, "contested_local_writes", f"quarantine failed: {exc}")
    if quarantined is None:
        return _error(
            payload,
            "contested_local_writes",
            "verified worktree disappeared before quarantine completed",
        )
    quarantine_detail = TakeoverQuarantineDetail(
        repo_id=payload.repo_id,
        quarantine_path=quarantined.quarantine_root,
        reason=quarantined.reason,
    )

    try:
        report = _recover_and_provision(
            provision_payload,
            project_config=project_config,
            project_root=project_root,
            repo_root=repo_root,
            worktree_path=worktree_path,
            branch=branch,
        )
    except EdgeGitError as exc:
        return _error(
            payload,
            "contested_local_writes",
            f"reprovision after quarantine failed: {exc}",
            quarantine_detail=quarantine_detail,
        )

    if marker_state == "stale":
        return _error(
            payload,
            "local_stale_or_dirty_takeover_target",
            "stale same-story target was quarantined and reprovisioned; explicit retry required",
            quarantine_detail=quarantine_detail,
        )
    return TakeoverReconcileExecution(
        result=report,
        quarantine_detail=quarantine_detail,
    )


def _provision_missing_target(
    payload: TakeoverReconcileCommandPayload,
    *,
    provision_payload: ProvisionWorktreeCommandPayload,
    project_config: ProjectConfig,
    project_root: Path,
    repo_root: Path,
    worktree_path: Path,
    branch: str,
    remove_remnant: bool = False,
) -> TakeoverReconcileExecution:
    """Recover and provision an absent or owned partial-reprovision target."""
    from agentkit.harness_client.projectedge.command_executor import (
        EdgeGitError,
    )

    try:
        report = _recover_and_provision(
            provision_payload,
            project_config=project_config,
            project_root=project_root,
            repo_root=repo_root,
            worktree_path=worktree_path,
            branch=branch,
            remove_remnant=remove_remnant,
        )
    except EdgeGitError as exc:
        return _error(payload, "local_stale_or_dirty_takeover_target", str(exc))
    return TakeoverReconcileExecution(result=report)


def _recover_and_provision(
    provision_payload: ProvisionWorktreeCommandPayload,
    *,
    project_config: ProjectConfig,
    project_root: Path,
    repo_root: Path,
    worktree_path: Path,
    branch: str,
    remove_remnant: bool = False,
) -> WorktreeReport:
    """Converge stale registration/branch state before provisioning.

    Both the post-quarantine path and every replay use this single recovery
    sequence. A markerless path is removed only after the caller has proved it
    is an owned partial reprovision, never for an ambiguous foreign target.
    """
    from agentkit.harness_client.projectedge.command_executor import (
        EdgeGitError,
        _require_git,
        _run_git,
        execute_provision_worktree,
    )

    if remove_remnant and worktree_path.exists():
        if _registered_at_canonical_path(repo_root, worktree_path):
            _require_git(
                _run_git(repo_root, "worktree", "remove", "--force", str(worktree_path)),
                "partial worktree remove",
            )
        else:
            if worktree_path.is_symlink():
                raise EdgeGitError(
                    "refusing to remove a symlinked partial worktree remnant"
                )
            try:
                shutil.rmtree(worktree_path)
            except OSError as exc:
                raise EdgeGitError(
                    f"partial worktree remnant removal failed: {exc}"
                ) from exc

    _require_git(_run_git(repo_root, "worktree", "prune"), "worktree prune")
    branch_present = _run_git(
        repo_root, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"
    )
    if branch_present.returncode == 0:
        _require_git(_run_git(repo_root, "branch", "-D", branch), "branch delete")
    elif branch_present.returncode != 1:
        _require_git(branch_present, "show-ref")
    return execute_provision_worktree(
        provision_payload,
        project_config=project_config,
        project_root=project_root,
    )


def _is_reprovision_remnant(
    repo_root: Path,
    worktree_path: Path,
    *,
    branch: str,
    takeover_base_sha: str,
) -> bool:
    """Recognize only state produced by an interrupted local reprovision."""
    marker_path = worktree_path / _STORY_MARKER_FILENAME
    if marker_path.exists():
        return False
    if _registered_at_canonical_path(repo_root, worktree_path):
        from agentkit.harness_client.projectedge.command_executor import (
            EdgeGitError,
            _require_git,
            _run_git,
        )

        try:
            branch_result = _run_git(
                worktree_path, "symbolic-ref", "--quiet", "--short", "HEAD"
            )
            _require_git(branch_result, "symbolic-ref HEAD")
            head_result = _run_git(worktree_path, "rev-parse", "HEAD")
            _require_git(head_result, "rev-parse HEAD")
            return (
                branch_result.stdout.strip() == branch
                and head_result.stdout.strip() == takeover_base_sha
                and _has_no_local_writes(worktree_path)
            )
        except EdgeGitError:
            return False
    return _is_unreadable_freeze_publication_remnant(worktree_path)


def _is_unreadable_freeze_publication_remnant(worktree_path: Path) -> bool:
    """Identify the guard-only root created after failed reprovision publication."""
    try:
        children = list(worktree_path.iterdir())
        freeze_path = worktree_path / ".agent-guard" / "freeze.json"
        payload = json.loads(freeze_path.read_text(encoding="utf-8"))
        guard_children = set(children[0].iterdir()) if len(children) == 1 else set()
    except (OSError, ValueError):
        return False
    return (
        len(children) == 1
        and children[0].name == ".agent-guard"
        and children[0].is_dir()
        and not children[0].is_symlink()
        and guard_children == {freeze_path}
        and payload == {"state_readable": False, "active_freezes": []}
    )


def _read_marker(worktree_path: Path) -> dict[str, object] | None:
    marker_path = worktree_path / _STORY_MARKER_FILENAME
    if not marker_path.is_file():
        return None
    try:
        payload = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _classify_marker(
    marker: dict[str, object] | None,
    *,
    payload: TakeoverReconcileCommandPayload,
) -> str:
    if marker is None:
        return "ambiguous"
    if (
        marker.get("story_id") != payload.story_id
        or marker.get("project_key") != payload.project_key
    ):
        return "ambiguous"
    return "current" if marker.get("run_id") == payload.run_id else "stale"


def _registered_at_canonical_path(repo_root: Path, worktree_path: Path) -> bool:
    from agentkit.harness_client.projectedge.command_executor import _run_git

    result = _run_git(repo_root, "worktree", "list", "--porcelain")
    if result.returncode != 0:
        return False
    expected = worktree_path.resolve()
    return any(
        Path(line.removeprefix("worktree ")).resolve() == expected
        for line in result.stdout.splitlines()
        if line.startswith("worktree ")
    )


def _has_no_local_writes(worktree_path: Path) -> bool:
    from agentkit.harness_client.projectedge.command_executor import (
        _require_git,
        _run_git,
    )

    result = _run_git(worktree_path, "status", "--porcelain", "--untracked-files=all")
    _require_git(result, "status --porcelain")
    for line in result.stdout.splitlines():
        relative = line[3:].replace("\\", "/") if len(line) > 3 else ""
        if relative == _STORY_MARKER_FILENAME or relative.startswith(".agent-guard/"):
            continue
        return False
    return True


def _error(
    payload: TakeoverReconcileCommandPayload,
    result_type: str,
    detail: str,
    *,
    quarantine_detail: TakeoverQuarantineDetail | None = None,
) -> TakeoverReconcileExecution:
    return TakeoverReconcileExecution(
        result=TakeoverErrorResult(
            result_type=result_type,
            repo_id=payload.repo_id,
            detail=detail,
        ),
        quarantine_detail=quarantine_detail,
    )


__all__ = ["TakeoverReconcileExecution", "execute_takeover_reconcile"]
