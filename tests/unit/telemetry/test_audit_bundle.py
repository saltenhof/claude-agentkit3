"""Unit tests for :class:`AuditBundleExporter` (AG3-036 AC9).

Uses the real SQLite-backed projection accessor + state-backend emitter (no
mocks): a completed run is materialised, exported and the six files plus the
manifest hashes are verified by a JSONL roundtrip.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.closure.post_merge_finalization.records import StoryMetricsRecord
from agentkit.backend.phase_state_store.models import FlowExecution
from agentkit.backend.state_backend.persistence_test_support import reset_backend_cache_for_tests
from agentkit.backend.state_backend.pipeline_runtime_store import save_flow_execution
from agentkit.backend.state_backend.store.telemetry_projection_repository_misc import (
    build_projection_repositories,
)
from agentkit.backend.state_backend.story_lifecycle_store import save_story_context
from agentkit.backend.story_context_manager.models import StoryContext
from agentkit.backend.story_context_manager.types import StoryMode, StoryType
from agentkit.backend.telemetry.audit_bundle import (
    AuditBundleExporter,
    AuditBundleExportError,
)
from agentkit.backend.telemetry.events import Event, EventType
from agentkit.backend.telemetry.projection_accessor import ProjectionAccessor, ProjectionKind
from agentkit.backend.telemetry.storage import StateBackendEmitter
from agentkit.backend.verify_system.stage_registry.records import (
    QAFindingRecord,
    QAStageResultRecord,
)

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

_PROJECT = "demo-proj"
_STORY = "AG3-900"
_RUN = "run-900"


@pytest.fixture()
def story_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[Path, None, None]:
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    reset_backend_cache_for_tests()
    story_dir = tmp_path / "stories" / _STORY
    story_dir.mkdir(parents=True, exist_ok=True)
    save_story_context(
        story_dir,
        StoryContext(
            project_key=_PROJECT,
            story_id=_STORY,
            story_type=StoryType.IMPLEMENTATION,
            execution_route=StoryMode.EXECUTION,
            project_root=tmp_path / _PROJECT,
        ),
    )
    save_flow_execution(
        story_dir,
        FlowExecution(
            project_key=_PROJECT,
            story_id=_STORY,
            run_id=_RUN,
            flow_id="implementation",
            level="story",
            owner="pipeline_engine",
            status="COMPLETED",
        ),
    )
    yield story_dir
    reset_backend_cache_for_tests()


def _accessor(story_dir: Path) -> ProjectionAccessor:
    return ProjectionAccessor(build_projection_repositories(story_dir))


def _seed_completed_run(accessor: ProjectionAccessor, emitter: StateBackendEmitter) -> None:
    accessor.write_projection(
        ProjectionKind.STORY_METRICS,
        StoryMetricsRecord(
            project_key=_PROJECT,
            story_id=_STORY,
            run_id=_RUN,
            story_type="IMPLEMENTATION",
            story_size="M",
            mode="standard",
            processing_time_min=12.0,
            qa_rounds=1,
            increments=2,
            final_status="COMPLETED",
            completed_at="2026-05-25T10:00:00+00:00",
        ),
    )
    accessor.write_projection(
        ProjectionKind.QA_STAGE_RESULTS,
        QAStageResultRecord(
            project_key=_PROJECT,
            story_id=_STORY,
            run_id=_RUN,
            attempt_no=1,
            stage_id="structural",
            layer="structural",
            producer_component="qa-structural-check",
            status="PASS",
            blocking=False,
            total_checks=4,
            failed_checks=0,
            warning_checks=0,
            artifact_id="art-1",
            recorded_at=datetime(2026, 5, 25, 10, 0, tzinfo=UTC),
        ),
    )
    accessor.write_projection(
        ProjectionKind.QA_FINDINGS,
        QAFindingRecord(
            project_key=_PROJECT,
            story_id=_STORY,
            run_id=_RUN,
            attempt_no=1,
            stage_id="structural",
            finding_id="f-1",
            check_id="mypy_error",
            status="REPORTED",
            severity="BLOCKING",
            blocking=True,
            source_component="qa-structural-check",
            artifact_id="art-1",
            occurred_at=datetime(2026, 5, 25, 10, 1, tzinfo=UTC),
        ),
    )
    emitter.emit(
        Event(
            story_id=_STORY,
            event_type=EventType.AGENT_START,
            project_key=_PROJECT,
            run_id=_RUN,
            payload={"worker_id": "w-1"},
        )
    )
    emitter.emit(
        Event(
            story_id=_STORY,
            event_type=EventType.INCREMENT_COMMIT,
            project_key=_PROJECT,
            run_id=_RUN,
            payload={"commit_sha": "abc"},
        )
    )


def test_export_produces_six_files_and_manifest(story_dir: Path) -> None:
    accessor = _accessor(story_dir)
    emitter = StateBackendEmitter(story_dir, default_project_key=_PROJECT)
    _seed_completed_run(accessor, emitter)

    out_dir = story_dir / "audit-bundle"
    bundle = AuditBundleExporter(accessor, emitter).export(_STORY, _RUN, out_dir)

    names = {f.name for f in bundle.files}
    assert names == {
        "events.jsonl",
        "qa_stage_results.jsonl",
        "qa_findings.jsonl",
        "story_metrics.json",
        "phase_states.jsonl",
    }
    assert bundle.manifest_path.exists()
    for f in bundle.files:
        assert f.path.exists()


def test_manifest_hashes_match_file_content(story_dir: Path) -> None:
    accessor = _accessor(story_dir)
    emitter = StateBackendEmitter(story_dir, default_project_key=_PROJECT)
    _seed_completed_run(accessor, emitter)

    out_dir = story_dir / "audit-bundle"
    bundle = AuditBundleExporter(accessor, emitter).export(_STORY, _RUN, out_dir)

    manifest = json.loads(bundle.manifest_path.read_text(encoding="utf-8"))
    by_name = {entry["name"]: entry for entry in manifest["files"]}
    for f in bundle.files:
        actual = hashlib.sha256(f.path.read_bytes()).hexdigest()
        assert by_name[f.name]["sha256"] == actual == f.sha256


def test_events_jsonl_roundtrip(story_dir: Path) -> None:
    accessor = _accessor(story_dir)
    emitter = StateBackendEmitter(story_dir, default_project_key=_PROJECT)
    _seed_completed_run(accessor, emitter)

    out_dir = story_dir / "audit-bundle"
    AuditBundleExporter(accessor, emitter).export(_STORY, _RUN, out_dir)

    lines = (
        (out_dir / "events.jsonl").read_text(encoding="utf-8").strip().splitlines()
    )
    rows = [json.loads(line) for line in lines]
    event_types = {row["event_type"] for row in rows}
    assert "agent_start" in event_types
    assert "increment_commit" in event_types
    for row in rows:
        assert row["story_id"] == _STORY
        assert row["run_id"] == _RUN


def test_story_metrics_single_record_roundtrip(story_dir: Path) -> None:
    accessor = _accessor(story_dir)
    emitter = StateBackendEmitter(story_dir, default_project_key=_PROJECT)
    _seed_completed_run(accessor, emitter)

    out_dir = story_dir / "audit-bundle"
    AuditBundleExporter(accessor, emitter).export(_STORY, _RUN, out_dir)

    metrics = json.loads((out_dir / "story_metrics.json").read_text(encoding="utf-8"))
    assert metrics["story_id"] == _STORY
    assert metrics["final_status"] == "COMPLETED"
    assert metrics["qa_rounds"] == 1


def test_export_refused_for_reset_or_incomplete_run(story_dir: Path) -> None:
    # No story_metrics record written -> the run is reset / not completed.
    accessor = _accessor(story_dir)
    emitter = StateBackendEmitter(story_dir, default_project_key=_PROJECT)

    out_dir = story_dir / "audit-bundle"
    with pytest.raises(AuditBundleExportError) as exc_info:
        AuditBundleExporter(accessor, emitter).export(_STORY, _RUN, out_dir)
    assert "no_story_metrics" in exc_info.value.reason


def test_dataclass_to_dict_rejects_non_dataclass() -> None:
    from agentkit.backend.telemetry.audit_bundle import _dataclass_to_dict

    with pytest.raises(TypeError):
        _dataclass_to_dict({"not": "a dataclass"})


def test_export_refused_for_non_terminal_status(story_dir: Path) -> None:
    accessor = _accessor(story_dir)
    emitter = StateBackendEmitter(story_dir, default_project_key=_PROJECT)
    accessor.write_projection(
        ProjectionKind.STORY_METRICS,
        StoryMetricsRecord(
            project_key=_PROJECT,
            story_id=_STORY,
            run_id=_RUN,
            story_type="IMPLEMENTATION",
            story_size="M",
            mode="standard",
            processing_time_min=1.0,
            qa_rounds=0,
            increments=0,
            final_status="IN_PROGRESS",
            completed_at="2026-05-25T10:00:00+00:00",
        ),
    )

    out_dir = story_dir / "audit-bundle"
    with pytest.raises(AuditBundleExportError) as exc_info:
        AuditBundleExporter(accessor, emitter).export(_STORY, _RUN, out_dir)
    assert "not_completed" in exc_info.value.reason
