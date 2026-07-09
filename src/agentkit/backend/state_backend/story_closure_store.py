"""Story-closure persistence store."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from agentkit.backend.state_backend.state_backend_connection_manager import (
    _backend_module,
    _require_control_plane_backend,
)

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path


def record_closure_report(
    story_dir: Path,
    report: Any,
    *,
    owner_session_id: str,
    expected_ownership_epoch: int,
    projection_dir: Path | None = None,
) -> Path:
    """Persist the closure report and its export projection."""
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


def upsert_push_freshness_record_global(record: Any) -> None:
    """Upsert one push-freshness row per project/story/run/repo."""
    from agentkit.backend.state_backend import persistence_mappers as mappers

    _require_control_plane_backend()
    backend = _backend_module()
    backend.upsert_push_freshness_record_global_row(
        mappers.push_freshness_record_to_row(record),
    )


def load_push_freshness_record_global(
    project_key: str,
    story_id: str,
    run_id: str,
    repo_id: str,
) -> Any | None:
    """Load one push-freshness record for a repo, or ``None``."""
    from agentkit.backend.state_backend import persistence_mappers as mappers

    _require_control_plane_backend()
    backend = _backend_module()
    row = backend.load_push_freshness_record_global_row(
        project_key,
        story_id,
        run_id,
        repo_id,
    )
    if row is None:
        return None
    return mappers.push_freshness_row_to_record(row)


def list_push_freshness_records_global(
    project_key: str,
    story_id: str,
    run_id: str,
) -> tuple[Any, ...]:
    """List the run's push-freshness records, one per repo."""
    from agentkit.backend.state_backend import persistence_mappers as mappers

    _require_control_plane_backend()
    backend = _backend_module()
    rows = backend.list_push_freshness_records_global_row(
        project_key,
        story_id,
        run_id,
    )
    return tuple(mappers.push_freshness_row_to_record(row) for row in rows)


def upsert_push_barrier_verdict_global(record: Any) -> None:
    """Upsert the authoritative per-repo push-barrier verdict."""
    from agentkit.backend.state_backend import persistence_mappers as mappers

    _require_control_plane_backend()
    backend = _backend_module()
    backend.upsert_push_barrier_verdict_global_row(
        mappers.push_barrier_verdict_to_row(record),
    )


def load_push_barrier_verdict_global(
    *,
    project_key: str,
    story_id: str,
    run_id: str,
    boundary_type: Any,
    boundary_id: str,
    repo_id: str,
) -> Any | None:
    """Load one push-barrier verdict, or ``None``."""
    from agentkit.backend.state_backend import persistence_mappers as mappers

    _require_control_plane_backend()
    backend = _backend_module()
    row = backend.load_push_barrier_verdict_global_row(
        project_key,
        story_id,
        run_id,
        boundary_type.value,
        boundary_id,
        repo_id,
    )
    if row is None:
        return None
    return mappers.push_barrier_verdict_row_to_record(row)


def list_push_barrier_verdicts_global(
    *,
    project_key: str,
    story_id: str,
    run_id: str,
    boundary_type: Any,
    boundary_id: str,
) -> tuple[Any, ...]:
    """List the per-repo verdicts for one boundary instance."""
    from agentkit.backend.state_backend import persistence_mappers as mappers

    _require_control_plane_backend()
    backend = _backend_module()
    rows = backend.list_push_barrier_verdicts_global_row(
        project_key,
        story_id,
        run_id,
        boundary_type.value,
        boundary_id,
    )
    return tuple(mappers.push_barrier_verdict_row_to_record(row) for row in rows)


def upsert_ref_protection_degradation_finding_global(
    *,
    project_key: str,
    story_id: str,
    repo_id: str,
    finding: Any,
    recorded_at: datetime,
) -> None:
    """Persist a project-visible ref-protection degradation finding."""
    _require_control_plane_backend()
    backend = _backend_module()
    backend.upsert_ref_protection_degradation_finding_global_row(
        {
            "project_key": project_key,
            "story_id": story_id,
            "repo_id": repo_id,
            "finding_code": finding.finding_code,
            "severity": finding.severity,
            "provider_label": finding.provider_label,
            "detail": finding.detail,
            "recorded_at": recorded_at.isoformat(),
        }
    )


def list_ref_protection_degradation_findings_global(
    project_key: str,
    story_id: str,
) -> tuple[dict[str, object], ...]:
    """List project-visible ref-protection degradation finding rows."""
    _require_control_plane_backend()
    backend = _backend_module()
    rows = backend.list_ref_protection_degradation_finding_global_rows(
        project_key,
        story_id,
    )
    return tuple(dict(row) for row in rows)


__all__ = [
    "record_closure_report",
    "upsert_push_freshness_record_global",
    "load_push_freshness_record_global",
    "list_push_freshness_records_global",
    "upsert_push_barrier_verdict_global",
    "load_push_barrier_verdict_global",
    "list_push_barrier_verdicts_global",
    "upsert_ref_protection_degradation_finding_global",
    "list_ref_protection_degradation_findings_global",
]
