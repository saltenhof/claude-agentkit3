"""AuditBundleExporter: JSONL audit bundle export at closure (FK-68 §68.3.6).

FK-68 §68.3.6 / §68.2.1 (audit-bundle glossary): the telemetry of a completed
story run can be exported as JSONL for long-term archival and human readability.
It is NOT a canonical runtime store -- the operative truth stays in the state
backend. Per the audit-bundle glossary it may ONLY be produced from a valid,
non-fully-reset run.

The exporter (AG3-036 §2.1.9) produces six files under ``output_dir``:

- ``events.jsonl`` -- all execution events of the run (FK-68 §68.3.6)
- ``qa_stage_results.jsonl`` -- the run's QA stage results (FK-69 read model)
- ``qa_findings.jsonl`` -- the run's QA findings (FK-69 read model)
- ``story_metrics.json`` -- the single closure metrics record
- ``phase_states.jsonl`` -- the run's flow/phase execution records
- ``manifest.json`` -- a content index with a SHA-256 hash per file

FAIL-CLOSED: ``export`` requires the run to be completed (a ``story_metrics``
record exists with a terminal ``final_status``). A reset run has its FK-69
projections purged (FK-69 §69.10.1), so the missing metrics record makes the
export fail closed with :class:`AuditBundleExportError` -- never a partial,
forgeable bundle.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from datetime import datetime
from typing import TYPE_CHECKING

from agentkit.state_backend.store import (
    load_execution_events,
    load_flow_execution,
    resolve_runtime_scope,
)
from agentkit.telemetry.projection_accessor import (
    ProjectionFilter,
    ProjectionKind,
)

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.telemetry.projection_accessor import ProjectionAccessor
    from agentkit.telemetry.storage import StateBackendEmitter

#: Terminal ``final_status`` values that mark a run as completed (non-reset).
_COMPLETED_STATUSES = frozenset({"COMPLETED", "DONE", "MERGED", "CLOSED"})

#: Stable file names of the audit bundle (FK-68 §68.3.6 / AG3-036 §2.1.9).
_EVENTS_FILE = "events.jsonl"
_QA_STAGE_RESULTS_FILE = "qa_stage_results.jsonl"
_QA_FINDINGS_FILE = "qa_findings.jsonl"
_STORY_METRICS_FILE = "story_metrics.json"
_PHASE_STATES_FILE = "phase_states.jsonl"
_MANIFEST_FILE = "manifest.json"


class AuditBundleExportError(RuntimeError):
    """Raised when an audit bundle cannot be produced fail-closed.

    Carries the offending ``story_id`` / ``run_id`` and the reason (e.g. a
    reset / not-completed run with no ``story_metrics`` record).
    """

    def __init__(self, *, story_id: str, run_id: str, reason: str) -> None:
        """Initialise the export error.

        Args:
            story_id: The story whose export was refused.
            run_id: The run whose export was refused.
            reason: Machine-readable refusal reason.
        """
        self.story_id = story_id
        self.run_id = run_id
        self.reason = reason
        super().__init__(
            f"audit bundle export refused for story_id={story_id!r} "
            f"run_id={run_id!r}: {reason}"
        )


@dataclasses.dataclass(frozen=True)
class AuditBundleFile:
    """One file of an exported audit bundle.

    Attributes:
        name: Bundle-relative file name.
        path: Absolute path of the written file.
        sha256: Hex SHA-256 of the file content.
        record_count: Number of JSONL records (1 for the single-record JSON).
        size_bytes: File size in bytes.
    """

    name: str
    path: Path
    sha256: str
    record_count: int
    size_bytes: int


@dataclasses.dataclass(frozen=True)
class AuditBundle:
    """Result of an audit-bundle export (FK-68 §68.3.6).

    Attributes:
        story_id: The exported story.
        run_id: The exported run.
        output_dir: Directory the bundle was written to.
        files: The six bundle files (excluding the manifest).
        manifest_path: Path of the written ``manifest.json``.
    """

    story_id: str
    run_id: str
    output_dir: Path
    files: tuple[AuditBundleFile, ...]
    manifest_path: Path


class AuditBundleExporter:
    """Exports a completed story run as a JSONL audit bundle (FK-68 §68.3.6)."""

    def __init__(
        self,
        projection_accessor: ProjectionAccessor,
        event_store: StateBackendEmitter,
    ) -> None:
        """Initialise with the FK-69 projection accessor and the event store.

        Args:
            projection_accessor: Owner of the QA / story-metrics read models.
            event_store: Canonical telemetry emitter bound to the story dir;
                supplies execution events and the story directory for phase
                states.
        """
        self._projection_accessor = projection_accessor
        self._event_store = event_store

    def export(self, story_id: str, run_id: str, output_dir: Path) -> AuditBundle:
        """Export the run's telemetry + projections as a JSONL audit bundle.

        FAIL-CLOSED: refuses to export a run that is not completed (no terminal
        ``story_metrics`` record -- e.g. a reset run whose FK-69 rows were
        purged), raising :class:`AuditBundleExportError`.

        Args:
            story_id: The story to export.
            run_id: The run to export.
            output_dir: Directory to write the bundle into (created if absent).

        Returns:
            The :class:`AuditBundle` describing the written files.

        Raises:
            AuditBundleExportError: When the run is not a completed, non-reset
                run.
        """
        story_dir = self._event_store.story_dir
        project_key = self._resolve_project_key(story_id, story_dir)

        metrics = self._load_story_metrics(project_key, story_id, run_id)
        if metrics is None:
            raise AuditBundleExportError(
                story_id=story_id,
                run_id=run_id,
                reason="no_story_metrics: run is reset or not completed",
            )
        final_status = str(metrics.get("final_status", "")).upper()
        if final_status not in _COMPLETED_STATUSES:
            raise AuditBundleExportError(
                story_id=story_id,
                run_id=run_id,
                reason=f"not_completed: final_status={final_status!r}",
            )

        output_dir.mkdir(parents=True, exist_ok=True)

        files: list[AuditBundleFile] = [
            self._write_jsonl(
                output_dir,
                _EVENTS_FILE,
                self._event_rows(story_dir, project_key, story_id, run_id),
            ),
            self._write_jsonl(
                output_dir,
                _QA_STAGE_RESULTS_FILE,
                self._qa_stage_result_rows(project_key, story_id, run_id),
            ),
            self._write_jsonl(
                output_dir,
                _QA_FINDINGS_FILE,
                self._qa_finding_rows(project_key, story_id, run_id),
            ),
            self._write_json_record(output_dir, _STORY_METRICS_FILE, metrics),
            self._write_jsonl(
                output_dir,
                _PHASE_STATES_FILE,
                self._phase_state_rows(story_dir, run_id),
            ),
        ]

        manifest_path = self._write_manifest(
            output_dir, story_id=story_id, run_id=run_id, files=files
        )
        return AuditBundle(
            story_id=story_id,
            run_id=run_id,
            output_dir=output_dir,
            files=tuple(files),
            manifest_path=manifest_path,
        )

    # ------------------------------------------------------------------
    # Row collection
    # ------------------------------------------------------------------

    def _resolve_project_key(self, story_id: str, story_dir: Path) -> str:
        scope = resolve_runtime_scope(story_dir)
        if scope.story_id == story_id and scope.project_key:
            return scope.project_key
        # Fall back to the project key derived from any event of the story.
        for event in self._event_store.query(story_id):
            if event.project_key:
                return event.project_key
        return ""

    def _event_rows(
        self,
        story_dir: Path,
        project_key: str,
        story_id: str,
        run_id: str,
    ) -> list[dict[str, object]]:
        records = load_execution_events(
            story_dir,
            project_key=project_key or None,
            story_id=story_id,
            run_id=run_id,
        )
        return [_execution_event_to_dict(record) for record in records]

    def _qa_stage_result_rows(
        self, project_key: str, story_id: str, run_id: str
    ) -> list[dict[str, object]]:
        records = self._projection_accessor.read_projection(
            ProjectionKind.QA_STAGE_RESULTS,
            ProjectionFilter(
                project_key=project_key or None,
                story_id=story_id,
                run_id=run_id,
            ),
        )
        return [_dataclass_to_dict(record) for record in records]

    def _qa_finding_rows(
        self, project_key: str, story_id: str, run_id: str
    ) -> list[dict[str, object]]:
        records = self._projection_accessor.read_projection(
            ProjectionKind.QA_FINDINGS,
            ProjectionFilter(
                project_key=project_key or None,
                story_id=story_id,
                run_id=run_id,
            ),
        )
        return [_dataclass_to_dict(record) for record in records]

    def _load_story_metrics(
        self, project_key: str, story_id: str, run_id: str
    ) -> dict[str, object] | None:
        records = self._projection_accessor.read_projection(
            ProjectionKind.STORY_METRICS,
            ProjectionFilter(
                project_key=project_key or None,
                story_id=story_id,
                run_id=run_id,
            ),
        )
        if not records:
            return None
        return _dataclass_to_dict(records[0])

    def _phase_state_rows(
        self, story_dir: Path, run_id: str
    ) -> list[dict[str, object]]:
        flow = load_flow_execution(story_dir)
        if flow is None or flow.run_id != run_id:
            return []
        return [_dataclass_to_dict(flow)]

    # ------------------------------------------------------------------
    # Writers
    # ------------------------------------------------------------------

    @staticmethod
    def _write_jsonl(
        output_dir: Path, name: str, rows: list[dict[str, object]]
    ) -> AuditBundleFile:
        path = output_dir / name
        lines = [json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows]
        content = ("\n".join(lines) + "\n") if lines else ""
        data = content.encode("utf-8")
        path.write_bytes(data)
        return AuditBundleFile(
            name=name,
            path=path,
            sha256=hashlib.sha256(data).hexdigest(),
            record_count=len(rows),
            size_bytes=len(data),
        )

    @staticmethod
    def _write_json_record(
        output_dir: Path, name: str, record: dict[str, object]
    ) -> AuditBundleFile:
        path = output_dir / name
        data = json.dumps(
            record, ensure_ascii=False, sort_keys=True, indent=2
        ).encode("utf-8")
        path.write_bytes(data)
        return AuditBundleFile(
            name=name,
            path=path,
            sha256=hashlib.sha256(data).hexdigest(),
            record_count=1,
            size_bytes=len(data),
        )

    @staticmethod
    def _write_manifest(
        output_dir: Path,
        *,
        story_id: str,
        run_id: str,
        files: list[AuditBundleFile],
    ) -> Path:
        manifest: dict[str, object] = {
            "story_id": story_id,
            "run_id": run_id,
            "schema": "agentkit.audit-bundle/v1",
            "files": [
                {
                    "name": f.name,
                    "sha256": f.sha256,
                    "record_count": f.record_count,
                    "size_bytes": f.size_bytes,
                }
                for f in files
            ],
        }
        path = output_dir / _MANIFEST_FILE
        path.write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        return path


def _execution_event_to_dict(record: object) -> dict[str, object]:
    """Serialise an ``ExecutionEventRecord`` to a JSON-safe dict.

    Args:
        record: An ``ExecutionEventRecord`` dataclass instance.

    Returns:
        A JSON-safe dict with the ISO timestamp.
    """
    return _dataclass_to_dict(record)


def _dataclass_to_dict(record: object) -> dict[str, object]:
    """Serialise a frozen dataclass record to a JSON-safe dict.

    Datetimes are rendered as ISO-8601 strings; nested dicts pass through.

    Args:
        record: A dataclass instance (record types are all frozen dataclasses).

    Returns:
        A JSON-safe dict.

    Raises:
        TypeError: When *record* is not a dataclass instance (fail-closed:
            the audit bundle never silently drops a non-dataclass record).
    """
    if not dataclasses.is_dataclass(record) or isinstance(record, type):
        raise TypeError(
            f"audit bundle record is not a dataclass instance: {type(record)!r}"
        )
    raw = dataclasses.asdict(record)
    return {key: _json_safe(value) for key, value in raw.items()}


def _json_safe(value: object) -> object:
    """Convert a value to a JSON-serialisable form (datetimes -> ISO strings)."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


__all__ = [
    "AuditBundle",
    "AuditBundleExportError",
    "AuditBundleExporter",
    "AuditBundleFile",
]
