"""CP10b handler: atomic pre/post-commit hook-ring publication."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from agentkit.backend.installer.bootstrap_checkpoints.cp10_checkpoint_support import (
    record_created_file,
)
from agentkit.backend.installer.checkpoint_engine import node_ids as nid
from agentkit.backend.installer.checkpoint_engine.result_builder import (
    is_dry_run,
    make_result,
    planned_result,
)
from agentkit.backend.installer.registration import CheckpointStatus

if TYPE_CHECKING:
    from agentkit.backend.installer.checkpoint_engine.context import (
        CheckpointContext,
    )
    from agentkit.backend.installer.registration import CheckpointResult


def cp10b_concept_validation_hook(
    context: CheckpointContext,
) -> CheckpointResult:
    """Materialize, verify and only then activate the real hook pair."""
    from agentkit.backend.installer.git_hook_dispatch import (
        migrate_git_hook_dispatch,
        verify_git_hook_dispatch,
    )

    start = time.monotonic()
    if is_dry_run(context.mode):
        return planned_result(
            nid.CP_10B_CONCEPT_VALIDATION_HOOK,
            planned_status=CheckpointStatus.CREATED,
            detail="Would materialise canonical pre-commit and post-commit dispatch.",
            start=start,
        )
    try:
        if context.mode.mutations_allowed:
            hooks_existed = all(
                (
                    context.project_root
                    / "tools"
                    / "hooks"
                    / name
                ).is_file()
                for name in ("pre-commit", "post-commit")
            )
            outcome = migrate_git_hook_dispatch(context.project_root)
        verify_git_hook_dispatch(context.project_root)
    except (OSError, ValueError) as exc:
        return make_result(
            nid.CP_10B_CONCEPT_VALIDATION_HOOK,
            status=CheckpointStatus.FAILED,
            detail=str(exc),
            reason="hook_dispatch_invalid",
            start=start,
        )
    if context.mode.mutations_allowed:
        if outcome.migrated:
            for name in ("pre-commit", "post-commit"):
                record_created_file(
                    context,
                    context.project_root / "tools" / "hooks" / name,
                )
        if not outcome.migrated:
            status = CheckpointStatus.PASS
        elif hooks_existed:
            status = CheckpointStatus.UPDATED
        else:
            status = CheckpointStatus.CREATED
    else:
        status = CheckpointStatus.PASS
    return make_result(
        nid.CP_10B_CONCEPT_VALIDATION_HOOK,
        status=status,
        detail=(
            "Verified canonical secret/validate and build-before-sync "
            "hook dispatch."
        ),
        start=start,
    )


__all__ = ["cp10b_concept_validation_hook"]
