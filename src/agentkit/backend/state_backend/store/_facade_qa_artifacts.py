"""QA artifact, closure report, and QA read facade compatibility exports."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from agentkit.backend.state_backend.artifact_catalog_store import (
    load_artifact_record as load_artifact_record,
)
from agentkit.backend.state_backend.artifact_catalog_store import (
    load_artifact_record_for_scope as load_artifact_record_for_scope,
)
from agentkit.backend.state_backend.artifact_catalog_store import (
    read_artifact_record as read_artifact_record,
)
from agentkit.backend.state_backend.prompt_runtime_store import (
    find_prompt_audit_output_hashes as find_prompt_audit_output_hashes,
)
from agentkit.backend.state_backend.store._facade_backend import (
    _backend_module,
)
from agentkit.backend.state_backend.telemetry_event_store import (
    load_qa_findings as load_qa_findings,
)
from agentkit.backend.state_backend.telemetry_event_store import (
    load_qa_findings_for_scope as load_qa_findings_for_scope,
)
from agentkit.backend.state_backend.telemetry_event_store import (
    load_qa_stage_results as load_qa_stage_results,
)
from agentkit.backend.state_backend.telemetry_event_store import (
    load_qa_stage_results_for_scope as load_qa_stage_results_for_scope,
)
from agentkit.backend.state_backend.verify_artifact_store import (
    find_latest_qa_envelope as find_latest_qa_envelope,
)
from agentkit.backend.state_backend.verify_artifact_store import (
    load_latest_verify_decision as load_latest_verify_decision,
)
from agentkit.backend.state_backend.verify_artifact_store import (
    load_latest_verify_decision_for_scope as load_latest_verify_decision_for_scope,
)
from agentkit.backend.state_backend.verify_artifact_store import (
    read_latest_verify_decision_record as read_latest_verify_decision_record,
)
from agentkit.backend.state_backend.verify_artifact_store import (
    record_layer_artifacts as record_layer_artifacts,
)
from agentkit.backend.state_backend.verify_artifact_store import (
    record_verify_decision as record_verify_decision,
)

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.closure.execution_report.records import ExecutionReport


def record_closure_report(
    story_dir: Path,
    report: ExecutionReport,
    *,
    owner_session_id: str,
    expected_ownership_epoch: int,
    projection_dir: Path | None = None,
) -> Path:
    """Persist the closure report and its export projection.

    Args:
        owner_session_id: (AG3-144, FK-91 §91.1a Rule 15) The caller's
            early-captured active ``run_ownership_records.owner_session_id``.
            Re-verified at commit time under ``SELECT ... FOR UPDATE``.
        expected_ownership_epoch: The caller's early-captured
            ``ownership_epoch`` snapshot, re-verified the same way.

    Raises:
        OwnershipFenceViolationError: (AG3-142 reuse) When the story's active
            ownership record no longer admits this exact snapshot at commit
            time -- nothing written.
    """
    flow_row = _backend_module().load_flow_execution_row(story_dir)
    payload = report.to_dict()
    return cast(
        "Path",
        _backend_module().persist_closure_report_row(
            story_dir,
            flow_row=flow_row,
            report_row={
                "story_id": getattr(report, "story_id", story_dir.name),
                "status": report.status,
                "payload": payload,
            },
            owner_session_id=owner_session_id,
            expected_ownership_epoch=expected_ownership_epoch,
            projection_dir=projection_dir,
        ),
    )


__all__ = [
    "record_layer_artifacts",
    "record_verify_decision",
    "load_latest_verify_decision",
    "load_latest_verify_decision_for_scope",
    "read_latest_verify_decision_record",
    "find_latest_qa_envelope",
    "find_prompt_audit_output_hashes",
    "load_artifact_record",
    "load_artifact_record_for_scope",
    "read_artifact_record",
    "record_closure_report",
    "load_qa_stage_results",
    "load_qa_stage_results_for_scope",
    "load_qa_findings",
    "load_qa_findings_for_scope",
]
