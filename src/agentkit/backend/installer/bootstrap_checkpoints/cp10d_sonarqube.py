"""CP10d handler: backend-mediated third-party validation."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from agentkit.backend.exceptions import InstallationError
from agentkit.backend.installer.bootstrap_checkpoints.cp10_checkpoint_support import (
    skipped_result,
)
from agentkit.backend.installer.checkpoint_engine import node_ids as nid
from agentkit.backend.installer.checkpoint_engine.reasons import (
    REASON_INAPPLICABLE,
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


def cp10d_sonarqube(context: CheckpointContext) -> CheckpointResult:
    """Run backend-mediated light Sonar/Jenkins/ARE validation."""
    from agentkit.backend.installer.runner import (
        _run_cp10d_sonarqube,
        _sonar_cp_to_checkpoint_result,
    )

    start = time.monotonic()
    yaml_data = context.run_state.project_yaml or {}
    if is_dry_run(context.mode):
        if not context.sonarqube_enabled:
            return skipped_result(
                nid.CP_10D_SONARQUBE,
                context,
                detail="sonarqube.available is false; CP 10d not applicable.",
                reason=REASON_INAPPLICABLE,
                start=start,
            )
        return planned_result(
            nid.CP_10D_SONARQUBE,
            planned_status=CheckpointStatus.PASS,
            detail=(
                "Would request backend-owned light "
                "Sonar/Jenkins/ARE validation."
            ),
            start=start,
        )
    if not context.sonarqube_enabled:
        return skipped_result(
            nid.CP_10D_SONARQUBE,
            context,
            detail=(
                "No mediated third-party system is enabled; "
                "CP 10d not applicable."
            ),
            reason=REASON_INAPPLICABLE,
            start=start,
        )
    try:
        sonar_result = _run_cp10d_sonarqube(
            context.config,
            context.project_root,
            yaml_data,
        )
    except InstallationError as exc:
        if context.mode.mutations_allowed:
            raise
        error_code = str(
            exc.detail.get(
                "error_code",
                "third_party_validation_failed",
            ),
        )
        raw_details = exc.detail.get("details")
        detail_items = raw_details if isinstance(raw_details, list) else [str(exc)]
        return make_result(
            nid.CP_10D_SONARQUBE,
            status=CheckpointStatus.FAILED,
            detail="; ".join(str(item) for item in detail_items),
            reason=error_code,
            start=start,
        )
    mapped = _sonar_cp_to_checkpoint_result(sonar_result)
    return make_result(
        nid.CP_10D_SONARQUBE,
        status=mapped.status,
        detail=mapped.detail,
        reason=mapped.reason,
        start=start,
    )


__all__ = ["cp10d_sonarqube"]
