"""CP 10b — concept validation git hooks (AG3-176 AC4 / R14)."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from agentkit.backend.installer.checkpoint_engine import node_ids as nid
from agentkit.backend.installer.checkpoint_engine.reasons import REASON_ALREADY_SATISFIED
from agentkit.backend.installer.checkpoint_engine.result_builder import (
    is_dry_run,
    make_result,
    planned_result,
)
from agentkit.backend.installer.registration import CheckpointStatus

if TYPE_CHECKING:
    from agentkit.backend.installer.checkpoint_engine.context import CheckpointContext
    from agentkit.backend.installer.registration import CheckpointResult


def cp10b_concept_validation_hook(context: CheckpointContext) -> CheckpointResult:
    """CP 10b — materialise firing pre-commit + post-commit hooks (AG3-176 AC4).

    Depends on CP 11 (``core.hooksPath``). Materialises project-local
    ``tools/hooks/pre-commit`` (secret-detection preserved + concept validate
    --staged) and ``tools/hooks/post-commit`` (build BEFORE sync; no freshness
    on failure). Idempotent REGISTER/DRY_RUN/VERIFY.
    """
    start = time.monotonic()
    from agentkit.backend.vectordb.git_hooks import materialize_concept_git_hooks
    from agentkit.backend.vectordb.project_binding import (
        ProjectBindingError,
        bind_project,
    )

    # AG3-176 R5: only entry-validated ProjectConfig / bind_project — no silent
    # "concepts" invent.
    try:
        if context.run_state.project_config is not None:
            binding = bind_project(
                context.project_root, config=context.run_state.project_config
            )
        else:
            binding = bind_project(context.project_root)
        concepts_rel = binding.config.concepts_dir
    except ProjectBindingError as exc:
        return make_result(
            nid.CP_10B_CONCEPT_VALIDATION_HOOK,
            status=CheckpointStatus.FAILED,
            detail=(
                f"configuration_invalid: project binding failed before hook "
                f"materialisation (AG3-176 R5): {exc}"
            ),
            reason="configuration_invalid",
            start=start,
        )

    mutate = context.mode.mutations_allowed
    outcome = materialize_concept_git_hooks(
        context.project_root,
        concepts_dir=str(concepts_rel),
        mutate=mutate,
    )
    if "refusing silent rewrite" in outcome.detail:
        return make_result(
            nid.CP_10B_CONCEPT_VALIDATION_HOOK,
            status=CheckpointStatus.FAILED,
            detail=outcome.detail,
            reason="hook_customization_unrecognised",
            start=start,
        )

    if not mutate:
        planned = (
            CheckpointStatus.PASS
            if not outcome.pre_commit_written
            and "already current" in outcome.detail
            else CheckpointStatus.CREATED
        )
        # dry_run / verify: use change detection without write flags
        from agentkit.backend.vectordb.git_hooks import (
            post_commit_is_current,
            post_commit_path,
            pre_commit_is_current,
            pre_commit_path,
        )

        pre_p = pre_commit_path(context.project_root)
        post_p = post_commit_path(context.project_root)
        pre_ok = pre_p.is_file() and pre_commit_is_current(
            pre_p.read_text(encoding="utf-8"), concepts_dir=str(concepts_rel)
        )
        post_ok = post_p.is_file() and post_commit_is_current(
            post_p.read_text(encoding="utf-8"), concepts_dir=str(concepts_rel)
        )
        planned = CheckpointStatus.PASS if (pre_ok and post_ok) else CheckpointStatus.CREATED
        if is_dry_run(context.mode):
            return planned_result(
                nid.CP_10B_CONCEPT_VALIDATION_HOOK,
                planned_status=planned,
                detail=outcome.detail,
                start=start,
            )
        return make_result(
            nid.CP_10B_CONCEPT_VALIDATION_HOOK,
            status=planned,
            detail=outcome.detail,
            reason=REASON_ALREADY_SATISFIED if planned is CheckpointStatus.PASS else None,
            start=start,
        )

    if outcome.pre_commit_written or outcome.post_commit_written:
        for path in (outcome.pre_commit_path, outcome.post_commit_path):
            try:
                rel = str(path.relative_to(context.project_root))
            except ValueError:
                continue
            if rel not in context.run_state.created_files:
                context.run_state.created_files.append(rel)
        return make_result(
            nid.CP_10B_CONCEPT_VALIDATION_HOOK,
            status=CheckpointStatus.CREATED,
            detail=outcome.detail,
            start=start,
        )
    return make_result(
        nid.CP_10B_CONCEPT_VALIDATION_HOOK,
        status=CheckpointStatus.PASS,
        detail=outcome.detail,
        reason=REASON_ALREADY_SATISFIED,
        start=start,
    )



__all__ = ["cp10b_concept_validation_hook"]
