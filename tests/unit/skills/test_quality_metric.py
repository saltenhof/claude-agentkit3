"""Unit tests for FK-43 skill quality metric aggregation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from agentkit.skills.errors import UnknownSkillNameError
from agentkit.skills.quality_metric import (
    AttributionState,
    SourceWindow,
    collect_quality_metrics,
)
from agentkit.telemetry.projection_accessor import ProjectionFilter, ProjectionKind


@dataclass(frozen=True)
class _StoryMetric:
    project_key: str
    completed_at: str
    final_status: str
    qa_rounds: int


@dataclass(frozen=True)
class _Incident:
    project_key: str
    incident_id: str
    recorded_at: datetime


class _FakeProjectionAccessor:
    def __init__(
        self,
        *,
        story_metrics: list[_StoryMetric],
        incidents: list[_Incident],
    ) -> None:
        self.calls: list[tuple[ProjectionKind, ProjectionFilter]] = []
        self._story_metrics = story_metrics
        self._incidents = incidents

    def read_projection(
        self,
        projection_kind: ProjectionKind,
        filter: ProjectionFilter,  # noqa: A002
    ) -> list[object]:
        self.calls.append((projection_kind, filter))
        if projection_kind is ProjectionKind.STORY_METRICS:
            return [
                record
                for record in self._story_metrics
                if record.project_key == filter.project_key
            ]
        if projection_kind is ProjectionKind.FC_INCIDENTS:
            return [
                record for record in self._incidents if record.project_key == filter.project_key
            ]
        raise AssertionError(f"unexpected projection kind: {projection_kind}")


def _window() -> SourceWindow:
    return SourceWindow(
        start_at=datetime(2026, 6, 1, tzinfo=UTC),
        end_at=datetime(2026, 7, 1, tzinfo=UTC),
    )


def test_collect_quality_metrics_aggregates_projection_sources() -> None:
    accessor = _FakeProjectionAccessor(
        story_metrics=[
            _StoryMetric("AK3", "2026-06-02T10:00:00+00:00", " completed ", 1),
            _StoryMetric("AK3", "2026-06-03T10:00:00+00:00", "FAILED", 3),
            _StoryMetric("AK3", "2026-06-04T10:00:00+00:00", "yielded", 2),
            _StoryMetric("OTHER", "2026-06-05T10:00:00+00:00", "DONE", 1),
            _StoryMetric("AK3", "2026-07-02T10:00:00+00:00", "DONE", 1),
        ],
        incidents=[
            _Incident("AK3", "FC-2026-0001", datetime(2026, 6, 2, tzinfo=UTC)),
            _Incident("AK3", "FC-2026-0002", datetime(2026, 6, 3, tzinfo=UTC)),
            _Incident("AK3", "FC-2026-0003", datetime(2026, 7, 3, tzinfo=UTC)),
            _Incident("OTHER", "FC-2026-0004", datetime(2026, 6, 3, tzinfo=UTC)),
        ],
    )

    metric = collect_quality_metrics(
        "execute-userstory",
        project_key="AK3",
        source_window=_window(),
        projection_accessor=accessor,
        known_skill_names={"execute-userstory"},
    )

    assert metric.usage_count == 3
    assert metric.successful_runs == 1
    assert metric.failed_runs == 1
    assert metric.unknown_status_runs == 1
    assert (
        metric.successful_runs + metric.failed_runs + metric.unknown_status_runs
        == metric.usage_count
    )
    assert metric.avg_qa_rounds == pytest.approx(2.0)
    assert metric.remediation_count == 3
    assert metric.incident_count == 2
    assert metric.incident_ids == ("FC-2026-0001", "FC-2026-0002")
    assert metric.bundle_version is None
    assert metric.attribution is AttributionState.UNATTRIBUTABLE
    assert [call[0] for call in accessor.calls] == [
        ProjectionKind.STORY_METRICS,
        ProjectionKind.FC_INCIDENTS,
    ]


def test_final_status_classification_is_deterministic_and_fail_closed() -> None:
    accessor = _FakeProjectionAccessor(
        story_metrics=[
            _StoryMetric("AK3", "2026-06-02T10:00:00+00:00", "done", 1),
            _StoryMetric("AK3", "2026-06-03T10:00:00+00:00", " MERGED ", 1),
            _StoryMetric("AK3", "2026-06-04T10:00:00+00:00", "blocked", 1),
            _StoryMetric("AK3", "2026-06-05T10:00:00+00:00", "Escalated", 1),
            _StoryMetric("AK3", "2026-06-06T10:00:00+00:00", "mystery", 1),
        ],
        incidents=[],
    )

    metric = collect_quality_metrics(
        "semantic-review",
        project_key="AK3",
        source_window=_window(),
        projection_accessor=accessor,
        known_skill_names={"semantic-review"},
    )

    assert metric.successful_runs == 2
    assert metric.failed_runs == 2
    assert metric.unknown_status_runs == 1
    assert (
        metric.successful_runs + metric.failed_runs + metric.unknown_status_runs
        == metric.usage_count
    )


def test_remediation_count_sums_every_qa_round_after_first_attempt() -> None:
    accessor = _FakeProjectionAccessor(
        story_metrics=[
            _StoryMetric("AK3", "2026-06-02T10:00:00+00:00", "DONE", 1),
            _StoryMetric("AK3", "2026-06-03T10:00:00+00:00", "DONE", 3),
        ],
        incidents=[],
    )

    metric = collect_quality_metrics(
        "execute-userstory",
        project_key="AK3",
        source_window=_window(),
        projection_accessor=accessor,
        known_skill_names={"execute-userstory"},
    )

    assert metric.remediation_count == 2


def test_unknown_skill_name_fails_closed_before_projection_reads() -> None:
    accessor = _FakeProjectionAccessor(story_metrics=[], incidents=[])

    with pytest.raises(UnknownSkillNameError):
        collect_quality_metrics(
            "missing-skill",
            project_key="AK3",
            source_window=_window(),
            projection_accessor=accessor,
            known_skill_names={"execute-userstory"},
        )

    assert accessor.calls == []
