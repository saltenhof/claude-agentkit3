"""CP10a handler: mandatory run-wide Story/Concept initial sync."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from agentkit.backend.exceptions import InstallationError
from agentkit.backend.installer.bootstrap_checkpoints.cp10_checkpoint_support import (
    record_created_file,
)
from agentkit.backend.installer.checkpoint_engine import node_ids as nid
from agentkit.backend.installer.checkpoint_engine.reasons import (
    REASON_CONFIGURATION_INVALID,
)
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


def cp10a_concept_context_properties(
    context: CheckpointContext,
) -> CheckpointResult:
    """Run both mandatory full reindexes and persist strict receipts."""
    from agentkit.backend.installer.cp10a_initial_sync import (
        run_initial_sync,
        verify_initial_sync,
    )

    start = time.monotonic()
    if context.run_state.project_config is None:
        return make_result(
            nid.CP_10A_CONCEPT_CONTEXT_PROPERTIES,
            status=CheckpointStatus.FAILED,
            detail="Strict project configuration is unavailable.",
            reason=REASON_CONFIGURATION_INVALID,
            start=start,
        )
    try:
        if is_dry_run(context.mode):
            return planned_result(
                nid.CP_10A_CONCEPT_CONTEXT_PROPERTIES,
                planned_status=CheckpointStatus.CREATED,
                detail="Would run story_sync and concept_sync full reindexes.",
                start=start,
            )
        if not context.mode.mutations_allowed:
            receipts = verify_initial_sync(
                context.project_root,
                expected_project_id=context.run_state.project_config.project_prefix,
            )
            return make_result(
                nid.CP_10A_CONCEPT_CONTEXT_PROPERTIES,
                status=CheckpointStatus.PASS,
                detail=(
                    "Verified typed story_sync and concept_sync success "
                    f"receipts for project {receipts[0].project_id}."
                ),
                start=start,
            )
        receipts_existed = all(
            (
                context.project_root
                / ".agentkit"
                / "receipts"
                / "vectordb"
                / name
            ).is_file()
            for name in ("story_sync.json", "concept_sync.json")
        )
        outcome = run_initial_sync(
            context.project_root,
            context.run_state.project_config,
            client=context.config.vectordb_client,
        )
    except InstallationError as exc:
        return make_result(
            nid.CP_10A_CONCEPT_CONTEXT_PROPERTIES,
            status=CheckpointStatus.FAILED,
            detail=str(exc),
            reason="initial_sync_failed",
            start=start,
        )
    if outcome.changed:
        for name in ("story_sync.json", "concept_sync.json"):
            record_created_file(
                context,
                context.project_root
                / ".agentkit"
                / "receipts"
                / "vectordb"
                / name,
            )
    if not outcome.changed:
        status = CheckpointStatus.PASS
    elif receipts_existed:
        status = CheckpointStatus.UPDATED
    else:
        status = CheckpointStatus.CREATED
    return make_result(
        nid.CP_10A_CONCEPT_CONTEXT_PROPERTIES,
        status=status,
        detail="Completed story_sync and concept_sync full reindexes with receipts.",
        start=start,
    )


__all__ = ["cp10a_concept_context_properties"]
