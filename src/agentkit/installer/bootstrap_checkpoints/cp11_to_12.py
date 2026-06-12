"""Checkpoint handlers CP 11 and CP 12 (FK-50 §50.3).

* CP 11 — ``git config core.hooksPath tools/hooks/`` + CLAUDE.md skeleton
  (created only on first install, never overwritten — CLAUDE.md is human-owned).
* CP 12 — read-only verification of all prior checkpoints (FK-50 §50.3 CP 12).
"""

from __future__ import annotations

import subprocess
import time
from typing import TYPE_CHECKING

from agentkit.installer.checkpoint_engine import node_ids as nid
from agentkit.installer.checkpoint_engine.reasons import REASON_ALREADY_SATISFIED
from agentkit.installer.checkpoint_engine.result_builder import (
    is_dry_run,
    make_result,
    planned_result,
)
from agentkit.installer.registration import CheckpointStatus

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.installer.checkpoint_engine.context import CheckpointContext
    from agentkit.installer.registration import CheckpointResult

#: Target-project git hooks path (FK-50 §50.3 CP 11).
_HOOKS_PATH_VALUE = "tools/hooks/"
#: CP 11 fail reason: git config write failed.
REASON_GIT_CONFIG_FAILED = "git_config_failed"
#: Minimal CLAUDE.md skeleton (human-owned; never overwritten on re-install).
_CLAUDE_MD_SKELETON = (
    "# Project Guidelines\n\n"
    "This CLAUDE.md is human-owned. AgentKit created this skeleton on first\n"
    "install and never overwrites it.\n"
)


def _claude_md_path(project_root: Path) -> Path:
    """Return the target-project ``CLAUDE.md`` path."""
    return project_root / "CLAUDE.md"


def _current_hooks_path(project_root: Path) -> str | None:
    """Return the configured ``core.hooksPath`` (or ``None`` if unset/no git)."""
    try:
        # fixed argv, no shell
        completed = subprocess.run(  # noqa: S603
            ["git", "-C", str(project_root), "config", "--get", "core.hooksPath"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    value = (completed.stdout or "").strip()
    return value or None


def _set_hooks_path(project_root: Path) -> bool:
    """Set ``core.hooksPath`` = ``tools/hooks/``; return success."""
    try:
        # fixed argv, no shell
        completed = subprocess.run(  # noqa: S603
            [
                "git",
                "-C",
                str(project_root),
                "config",
                "core.hooksPath",
                _HOOKS_PATH_VALUE,
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def _cp11_plan_result(
    *, hooks_set: bool, claude_present: bool, dry_run: bool, start: float
) -> CheckpointResult:
    """Build the read-only CP 11 outcome (dry-run plan / verify status).

    Read-only modes never mutate; they report the planned status: PASS when
    nothing would change, CREATED when the CLAUDE.md skeleton is absent (it would
    be created), else UPDATED.
    """
    will_change = (not hooks_set) or (not claude_present)
    if not will_change:
        planned = CheckpointStatus.PASS
    elif not claude_present:
        planned = CheckpointStatus.CREATED
    else:
        planned = CheckpointStatus.UPDATED
    detail = (
        f"Would ensure core.hooksPath={_HOOKS_PATH_VALUE} and the CLAUDE.md "
        "skeleton (created only if absent)."
    )
    if dry_run:
        return planned_result(
            nid.CP_11_GIT_HOOKS_AND_CLAUDE,
            planned_status=planned,
            detail=detail,
            start=start,
        )
    return make_result(
        nid.CP_11_GIT_HOOKS_AND_CLAUDE,
        status=planned,
        detail=detail,
        reason=REASON_ALREADY_SATISFIED if planned is CheckpointStatus.PASS else None,
        start=start,
    )


def cp11_git_hooks_and_claude(context: CheckpointContext) -> CheckpointResult:
    """CP 11 — set ``core.hooksPath`` + create the CLAUDE.md skeleton (idempotent).

    Register mode: sets ``core.hooksPath`` to ``tools/hooks/`` when not already
    set, and writes the CLAUDE.md skeleton ONLY when absent (never overwrites —
    CLAUDE.md is human-owned, FK-50 §50.3 CP 11). Dry-run/verify never mutate.
    """
    start = time.monotonic()
    root = context.project_root
    claude_md = _claude_md_path(root)
    hooks_set = _current_hooks_path(root) == _HOOKS_PATH_VALUE
    claude_present = claude_md.is_file()

    if not context.mode.mutations_allowed:
        return _cp11_plan_result(
            hooks_set=hooks_set,
            claude_present=claude_present,
            dry_run=is_dry_run(context.mode),
            start=start,
        )

    changed = False
    if not hooks_set and not _set_hooks_path(root):
        return make_result(
            nid.CP_11_GIT_HOOKS_AND_CLAUDE,
            status=CheckpointStatus.FAILED,
            detail=(
                f"Failed to set core.hooksPath={_HOOKS_PATH_VALUE} "
                "(is the project a git repo with write access?)."
            ),
            reason=REASON_GIT_CONFIG_FAILED,
            start=start,
        )
    changed = changed or not hooks_set
    if not claude_present:
        from agentkit.installer.file_ops import atomic_write_text

        atomic_write_text(claude_md, _CLAUDE_MD_SKELETON)
        context.run_state.created_files.append(str(claude_md.relative_to(root)))
        changed = True

    status = CheckpointStatus.CREATED if changed else CheckpointStatus.PASS
    return make_result(
        nid.CP_11_GIT_HOOKS_AND_CLAUDE,
        status=status,
        detail=f"Ensured core.hooksPath={_HOOKS_PATH_VALUE} and CLAUDE.md skeleton.",
        start=start,
    )


def cp12_verify_registration(context: CheckpointContext) -> CheckpointResult:
    """CP 12 — read-only verification of all prior checkpoints (FK-50 §50.3).

    Always read-only (never mutates in ANY mode). Validates the install surface
    the prior checkpoints established: project config present, profile resolved,
    registration looked up, and — for register mode — the deployed artefacts.
    Returns PASS or FAILED with a machine reason.
    """
    from agentkit.installer.paths import project_config_path

    start = time.monotonic()
    problems: list[str] = []
    root = context.project_root

    if context.run_state.resolved_profile is None:
        problems.append("profile not resolved (CP 6)")
    if context.run_state.project_yaml is None:
        problems.append("project.yaml not built (CP 5)")

    # In register mode the config must be on disk; in read-only modes its
    # absence is acceptable (nothing was written), so only assert when mutating.
    if context.mode.mutations_allowed and not project_config_path(root).is_file():
        problems.append("project.yaml missing on disk")

    if problems:
        return make_result(
            nid.CP_12_VERIFY_REGISTRATION,
            status=CheckpointStatus.FAILED,
            detail="Verification found problems: " + "; ".join(problems),
            reason="verification_failed",
            start=start,
        )
    return make_result(
        nid.CP_12_VERIFY_REGISTRATION,
        status=CheckpointStatus.PASS,
        detail="All prior checkpoints verified (read-only).",
        start=start,
    )


__all__ = [
    "REASON_GIT_CONFIG_FAILED",
    "cp11_git_hooks_and_claude",
    "cp12_verify_registration",
]
