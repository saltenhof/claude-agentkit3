"""Projection-backed aggregation for :class:`SkillQualityMetric`."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol, cast

from agentkit.skills.bundle_store import shipped_skill_bundles_root
from agentkit.skills.errors import (
    SkillQualityMetricSourceUnavailableError,
    UnknownSkillNameError,
)
from agentkit.skills.quality_metric.model import (
    AttributionState,
    SkillQualityMetric,
    SourceWindow,
)
from agentkit.telemetry.audit_bundle import _COMPLETED_STATUSES
from agentkit.telemetry.projection_accessor import ProjectionFilter, ProjectionKind

if TYPE_CHECKING:
    from collections.abc import Collection, Sequence
    from pathlib import Path

FAILURE_STATUSES: frozenset[str] = frozenset({"FAILED", "ESCALATED", "BLOCKED"})


class _ProjectionAccessorProtocol(Protocol):
    def read_projection(
        self,
        projection_kind: ProjectionKind,
        filter: ProjectionFilter,  # noqa: A002
    ) -> Sequence[object]:
        """Read projection records through the telemetry boundary."""


def collect_quality_metrics(
    skill_name: str,
    *,
    project_key: str,
    source_window: SourceWindow,
    projection_accessor: _ProjectionAccessorProtocol | None = None,
    known_skill_names: Collection[str] | None = None,
) -> SkillQualityMetric:
    """Collect fail-closed quality metrics for ``skill_name``.

    Args:
        skill_name: Suffix-free FK-43 skill identity.
        project_key: Project key used for projection filtering.
        source_window: Window applied to source timestamps.
        projection_accessor: Telemetry projection accessor. This is the only
            source read boundary used for story metrics and ``FC_INCIDENTS``.
        known_skill_names: Optional catalog identities used for fail-closed
            validation. Defaults to shipped bundle manifests.

    Returns:
        A typed skill quality metric.

    Raises:
        UnknownSkillNameError: If ``skill_name`` is not present in the catalog.
        SkillQualityMetricSourceUnavailableError: If no projection accessor is
            supplied.
    """

    catalog_names = set(known_skill_names or _read_shipped_skill_names())
    if skill_name not in catalog_names:
        raise UnknownSkillNameError(
            f"Unknown skill_name for quality metrics: {skill_name!r}",
            detail={"skill_name": skill_name, "known_skill_names": sorted(catalog_names)},
        )
    if projection_accessor is None:
        raise SkillQualityMetricSourceUnavailableError(
            "collect_quality_metrics requires Telemetry.ProjectionAccessor",
            detail={"skill_name": skill_name, "project_key": project_key},
        )

    projection_filter = ProjectionFilter(project_key=project_key)
    story_metric_records = [
        record
        for record in projection_accessor.read_projection(
            ProjectionKind.STORY_METRICS,
            projection_filter,
        )
        if _record_in_window(record, "completed_at", source_window)
    ]
    incident_records = [
        record
        for record in projection_accessor.read_projection(
            ProjectionKind.FC_INCIDENTS,
            projection_filter,
        )
        if _record_in_window(record, "recorded_at", source_window)
    ]

    successful_runs = 0
    failed_runs = 0
    unknown_status_runs = 0
    qa_rounds_total = 0
    remediation_count = 0

    for record in story_metric_records:
        status_bucket = _classify_final_status(getattr(record, "final_status", ""))
        if status_bucket == "success":
            successful_runs += 1
        elif status_bucket == "failure":
            failed_runs += 1
        else:
            unknown_status_runs += 1

        qa_rounds = int(getattr(record, "qa_rounds", 0))
        qa_rounds_total += qa_rounds
        remediation_count += max(qa_rounds - 1, 0)

    usage_count = len(story_metric_records)
    avg_qa_rounds = qa_rounds_total / usage_count if usage_count else None
    incident_ids = tuple(
        str(cast("Any", record).incident_id) for record in incident_records
    )

    return SkillQualityMetric(
        skill_name=skill_name,
        project_key=project_key,
        source_window=source_window,
        bundle_version=None,
        usage_count=usage_count,
        successful_runs=successful_runs,
        failed_runs=failed_runs,
        unknown_status_runs=unknown_status_runs,
        avg_qa_rounds=avg_qa_rounds,
        remediation_count=remediation_count,
        incident_count=len(incident_ids),
        incident_ids=incident_ids,
        attribution=AttributionState.UNATTRIBUTABLE,
    )


def _classify_final_status(final_status: object) -> str:
    normalized = str(final_status).strip().upper()
    if normalized in _COMPLETED_STATUSES:
        return "success"
    if normalized in FAILURE_STATUSES:
        return "failure"
    return "unknown"


def _record_in_window(record: object, field_name: str, source_window: SourceWindow) -> bool:
    timestamp = _parse_timestamp(getattr(record, field_name, None))
    if timestamp is None:
        return False
    if source_window.start_at is not None and timestamp < _normalize_datetime(
        source_window.start_at
    ):
        return False
    return not (
        source_window.end_at is not None
        and timestamp >= _normalize_datetime(source_window.end_at)
    )


def _parse_timestamp(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return _normalize_datetime(value)
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"
    try:
        return _normalize_datetime(datetime.fromisoformat(raw))
    except ValueError:
        return None


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _read_shipped_skill_names() -> frozenset[str]:
    root = shipped_skill_bundles_root()
    names: set[str] = set()
    if not root.is_dir():
        return frozenset()
    for manifest_path in sorted(root.glob("*/4.0.0/manifest.json")):
        name = _read_manifest_skill_name(manifest_path)
        if name is not None:
            names.add(name)
    return frozenset(names)


def _read_manifest_skill_name(manifest_path: Path) -> str | None:
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    skill_name = payload.get("skill_name")
    if not isinstance(skill_name, str) or not skill_name:
        return None
    return skill_name
