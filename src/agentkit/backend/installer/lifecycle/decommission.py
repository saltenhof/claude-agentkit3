"""Level-1/2 decommission (FK-10 §10.2.9, AG3-122).

Uninstall is per-level with SEPARATE, typed verbs (a flag/subcommand selects the
:class:`DecommissionLevel`, never a string cascade):

* **Machine-uninstall (level 2):** removes the dev machine's bundle store /
  shims. Before removing a bundle version, every project still pinned to it is
  WARNED as ``orphaned`` (FK-10 §10.2.9). The shared ``agentkit`` package itself
  is not self-removed from inside a running process (it would also break a
  co-installed AK2); that pip step stays an explicit operator action.
* **Core-decommission (level 1):** stops the backend/frontend services. It is
  DESTRUCTIVE and therefore requires BOTH an explicit confirmation AND a
  mandatory state-backend export (audit trail / closure records / QA) BEFORE any
  teardown. Deleting the DB volume is DECOUPLED from the service uninstall
  (``docker compose down -v`` is forbidden) so the canonical state survives a
  service teardown (FK-10 §10.2.0 base rule).
"""

from __future__ import annotations

import dataclasses
import json
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path, PureWindowsPath
from typing import TYPE_CHECKING, Any, Protocol, cast

from agentkit.backend.skills import is_directory_link

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


class DecommissionLevel(Enum):
    """Typed install-trinity level of a decommission verb (FK-10 §10.2.9)."""

    MACHINE = "machine"  # level 2
    CORE = "core"  # level 1


class MachineDecommissionError(Exception):
    """Raised when a level-2 machine-uninstall precondition is unmet (fail-closed).

    Notably guards the bundle-store removal against path traversal: a bundle
    version that is not a single, in-store child directory name (``..``, an
    embedded separator, an absolute or drive-relative path) is rejected BEFORE
    any ``rmtree``, so a lower-level uninstall can never delete outside its own
    surface (FK-10 §10.2.9 level-2 boundary).
    """


class CoreDecommissionError(Exception):
    """Raised when a core-decommission precondition is unmet (fail-closed)."""


class ServiceTeardownError(Exception):
    """Raised when the core service teardown cannot run or fails (fail-closed).

    A teardown that cannot be executed (orchestrator unavailable) or that exits
    non-zero must NOT be reported as "services stopped" (FK-10 §10.2.9, AC6 "kein
    Stub-Echo als 'done'"). The service controller raises this so the caller exits
    non-zero instead of claiming a successful decommission.
    """


@dataclass(frozen=True)
class PinnedProject:
    """A project pinned to a concrete bundle version (FK-10 §10.2.6)."""

    project_key: str
    bundle_version: str
    project_root: str


@dataclass(frozen=True)
class MachineDecommissionResult:
    """Outcome of a level-2 machine-uninstall.

    Attributes:
        removed_bundle_versions: Bundle-store version dirs removed (relative names).
        orphaned_projects: Project keys warned as ``orphaned`` before removal.
        success: Whether the machine-uninstall completed.
    """

    removed_bundle_versions: tuple[str, ...]
    orphaned_projects: tuple[str, ...]
    success: bool = True


@dataclass(frozen=True)
class CoreDecommissionRequest:
    """Inputs for a level-1 core-decommission (destructive, fail-closed).

    Attributes:
        confirm: Explicit operator confirmation (required; absence aborts).
        export_dir: Mandatory state-backend export destination (required; absence
            aborts BEFORE any teardown).
    """

    confirm: bool
    export_dir: Path | None


@dataclass(frozen=True)
class CoreDecommissionResult:
    """Outcome of a level-1 core-decommission.

    Attributes:
        exported_to: The state-backend export artifact written before teardown.
        stopped_services: The services stopped during teardown.
        db_volume_preserved: Always ``True`` — volume deletion is decoupled.
        success: Whether the core-decommission completed.
    """

    exported_to: Path
    stopped_services: tuple[str, ...]
    db_volume_preserved: bool
    success: bool = True


class StateBackendExporter(Protocol):
    """Export the central state backend (audit/closure/QA) before a teardown."""

    def export(self, export_dir: Path) -> Path:
        """Write the export artifact and return its path."""
        ...


class ServiceController(Protocol):
    """Stop the Core's backend/frontend services WITHOUT deleting the DB volume."""

    def stop_services(self) -> Sequence[str]:
        """Stop the services and return the stopped service names."""
        ...


def decommission_machine(
    *,
    bundle_store_root: Path,
    pinned_projects: Sequence[PinnedProject],
    bundle_version: str | None = None,
) -> MachineDecommissionResult:
    """Run a level-2 machine-uninstall (FK-10 §10.2.9).

    Warns every project still pinned to a removed bundle version as ``orphaned``
    BEFORE removing it, then removes the bundle-store version directory/-ies. The
    pinned projects (level-3 repos) themselves are PRESERVED — a lower level
    never deletes higher-level canonical state.

    Args:
        bundle_store_root: The immutable bundle store root (``…/bundles``).
        pinned_projects: Projects pinned to a concrete bundle version.
        bundle_version: A single version to remove; ``None`` removes every
            version directory in the store.

    Returns:
        The :class:`MachineDecommissionResult` carrying the orphaned warnings.
    """
    # A bundle store root that is ITSELF a reparse point (symlink/junction) would
    # make ``resolve()`` point at the link's OUTSIDE target, so the in-store
    # containment assertion would pass for ``<outside-target>/<version>`` and the
    # removal would delete THROUGH the link, destroying foreign state (FK-10
    # §10.2.9 destructive footgun; FK-43 §43.4.1.1). The root is checked AS GIVEN
    # (not resolved) BEFORE any enumeration or removal: a link root aborts the
    # whole verb so nothing is removed (fail-closed).
    if is_directory_link(bundle_store_root):
        msg = "refusing to run machine-uninstall: the bundle store root "
        msg += f"{bundle_store_root} is itself a symlink/junction (reparse point); "
        msg += "removing version directories underneath it would delete THROUGH the "
        msg += "link into its target; nothing removed (fail-closed)."
        raise MachineDecommissionError(msg)
    targets = _bundle_versions_to_remove(bundle_store_root, bundle_version)
    # Validate EVERY target name (the explicit --bundle-version AND each
    # enumerated store entry) BEFORE removing anything: a single unsafe name OR a
    # link entry aborts the whole verb so nothing is removed (fail-closed, defense
    # in depth).
    validated: list[tuple[str, Path]] = []
    for version_dir in targets:
        path = _ensure_safe_bundle_version_path(bundle_store_root, version_dir)
        _ensure_real_directory_entry(version_dir, path)
        validated.append((version_dir, path))
    orphaned = tuple(
        sorted(
            project.project_key
            for project in pinned_projects
            if project.bundle_version in targets
        )
    )
    removed: list[str] = []
    for version_dir, path in validated:
        if path.is_dir():
            shutil.rmtree(path)
            removed.append(version_dir)
    return MachineDecommissionResult(
        removed_bundle_versions=tuple(sorted(removed)),
        orphaned_projects=orphaned,
    )


def _ensure_safe_bundle_version_path(
    bundle_store_root: Path, version_dir: str
) -> Path:
    """Return the in-store removal path for ``version_dir`` or fail closed.

    A bundle-store version directory must be a SINGLE relative child name. This
    rejects every path-traversal footgun before the name is ever turned into an
    ``rmtree`` target (FK-10 §10.2.9 level-2 boundary):

    * empty, ``.`` or ``..``;
    * any embedded path separator (``/`` or ``\\``);
    * any drive/root/anchor (absolute paths and Windows drive-relative ``C:foo``).

    The structural check uses Windows path semantics (the strictest superset:
    both separators and ``C:``/UNC anchors are recognised) so a malicious name is
    rejected identically on every OS, not only the one running the verb. As a
    final containment assertion the resolved path must lie STRICTLY inside the
    resolved store root.

    Args:
        bundle_store_root: The bundle store root the removal must stay within.
        version_dir: The candidate version directory name to validate.

    Returns:
        The validated ``bundle_store_root / version_dir`` removal path.

    Raises:
        MachineDecommissionError: When ``version_dir`` is not a safe in-store
            single child name (nothing is removed).
    """
    candidate = PureWindowsPath(version_dir)
    if (
        version_dir in {"", ".", ".."}
        or "/" in version_dir
        or "\\" in version_dir
        or candidate.anchor != ""
        or candidate.drive != ""
        or len(candidate.parts) != 1
        or candidate.name != version_dir
    ):
        msg = f"refusing to remove bundle version {version_dir!r}: a bundle-store "
        msg += "version directory must be a single relative child name (no path "
        msg += "separators, no drive/root/anchor, not '.' or '..'); nothing removed "
        msg += "(fail-closed)."
        raise MachineDecommissionError(msg)
    # Resolving BOTH the root and the child confines all removal to within the
    # resolved bundle store even when the store is reached through a symlinked/
    # junction ANCESTOR: root and child resolve consistently through the parent
    # link, so the path stays a child of the resolved store. Removal can never
    # reach a sibling of the store or higher-level canonical state (FK-10
    # §10.2.9 base rule). A reparse-point store ROOT is a separate footgun and is
    # rejected as-given up front in ``decommission_machine``.
    root_resolved = bundle_store_root.resolve()
    resolved = (bundle_store_root / version_dir).resolve()
    if resolved == root_resolved or not resolved.is_relative_to(root_resolved):
        msg = f"refusing to remove bundle version {version_dir!r}: the resolved "
        msg += f"removal path {resolved} escapes the bundle store {root_resolved}; "
        msg += "nothing removed (fail-closed)."
        raise MachineDecommissionError(msg)
    return bundle_store_root / version_dir


def _ensure_real_directory_entry(version_dir: str, path: Path) -> None:
    """Fail closed when a version-store entry is a reparse point, not a real dir.

    A bundle-store version slot is expected to hold a REAL directory. A symlink/
    junction in that slot is anomalous: ``shutil.rmtree`` would recurse THROUGH
    the link and destroy the link target's contents (the detach footgun class,
    FK-43 §43.4.1.1). The entry is checked AS GIVEN (not resolved) so a link is
    detected before it is ever turned into an ``rmtree`` target; nothing is
    removed (fail-closed). Name validation + the resolved-containment assertion
    in :func:`_ensure_safe_bundle_version_path` stay as defense in depth.

    Args:
        version_dir: The candidate version directory name (for the message).
        path: The in-store ``bundle_store_root / version_dir`` removal path.

    Raises:
        MachineDecommissionError: When ``path`` is a symlink/junction.
    """
    if is_directory_link(path):
        msg = f"refusing to remove bundle version {version_dir!r}: the store entry "
        msg += f"{path} is a symlink/junction (reparse point), not a real directory; "
        msg += "removing it would delete THROUGH the link into its target; nothing "
        msg += "removed (fail-closed)."
        raise MachineDecommissionError(msg)


def _bundle_versions_to_remove(
    bundle_store_root: Path, bundle_version: str | None
) -> tuple[str, ...]:
    """Resolve the bundle-store version directory names to remove."""
    if bundle_version is not None:
        return (bundle_version,)
    if not bundle_store_root.is_dir():
        return ()
    return tuple(
        sorted(child.name for child in bundle_store_root.iterdir() if child.is_dir())
    )


def decommission_core(
    request: CoreDecommissionRequest,
    *,
    service_controller: ServiceController,
    state_exporter: StateBackendExporter | None = None,
) -> CoreDecommissionResult:
    """Run a level-1 core-decommission (destructive, fail-closed; FK-10 §10.2.9).

    Order is enforced: confirmation + mandatory export are checked BEFORE any
    teardown; the export runs FIRST; the service stop NEVER deletes the DB volume
    (``down -v`` is forbidden, the volume is preserved).

    Args:
        request: The confirmation + mandatory export destination.
        service_controller: Stops the backend/frontend services (no volume delete).
        state_exporter: The state-backend exporter; defaults to the real
            :class:`CanonicalStateExporter` (reads the canonical audit/closure/QA
            records and serializes them — never a manifest-only placeholder).

    Returns:
        The :class:`CoreDecommissionResult`.

    Raises:
        CoreDecommissionError: When confirmation or the mandatory export
            destination is missing, or the mandatory export itself fails (fail-
            closed — nothing is torn down).
        ServiceTeardownError: When the teardown command cannot run / exits
            non-zero (raised by the controller AFTER a successful export).
    """
    if not request.confirm:
        msg = "core-decommission is destructive and requires explicit confirmation "
        msg += "(--confirm); aborting without tearing anything down (fail-closed)."
        raise CoreDecommissionError(msg)
    if request.export_dir is None:
        msg = "core-decommission requires a mandatory state-backend export "
        msg += "(--export-dir) of the audit trail / closure records / QA results "
        msg += "BEFORE teardown; aborting (fail-closed)."
        raise CoreDecommissionError(msg)

    exporter = (
        state_exporter if state_exporter is not None else CanonicalStateExporter()
    )
    # The mandatory export runs FIRST. ANY failure (backend unreachable, read or
    # write error) aborts the whole decommission BEFORE any service is touched —
    # nothing is torn down on export failure (FK-10 §10.2.9 mandatory-export
    # precondition, fail-closed).
    try:
        exported_to = exporter.export(request.export_dir)
    except Exception as exc:  # noqa: BLE001 - fail-closed: any export failure aborts
        msg = "core-decommission mandatory state-backend export FAILED; nothing torn "
        msg += f"down (fail-closed): {exc}"
        raise CoreDecommissionError(msg) from exc
    stopped = tuple(service_controller.stop_services())
    # The DB volume is intentionally NOT touched here: volume deletion is a
    # separate, explicitly-confirmed destructive step (FK-10 §10.2.9 "Projekt-
    # Loeschung"), decoupled from the service uninstall (``down -v`` forbidden).
    return CoreDecommissionResult(
        exported_to=exported_to,
        stopped_services=stopped,
        db_volume_preserved=True,
    )


#: Export-artifact filenames per canonical record class (real records, one JSON
#: object per line — JSONL — not a manifest placeholder).
_AUDIT_TRAIL_FILE = "audit-trail.jsonl"
_CLOSURE_RECORDS_FILE = "closure-records.jsonl"
_QA_RESULTS_FILE = "qa-results.jsonl"
_MANIFEST_FILE = "state-backend-export-manifest.json"


class CanonicalStateReadPort(Protocol):
    """Read port over the canonical state backend (audit trail / closure / QA).

    Backend-agnostic: the productive adapter reads through the state-backend
    READ API/facade (SQLite and Postgres share the same surface). Every method
    is fail-closed — a backend/transport error propagates so the export aborts
    before any teardown.
    """

    def project_keys(self) -> Sequence[str]:
        """Return every registered project key."""
        ...

    def story_ids(self, project_key: str) -> Sequence[str]:
        """Return every story id of ``project_key``."""
        ...

    def audit_trail_records(self, project_key: str) -> Sequence[Mapping[str, object]]:
        """Return the audit-trail (execution-event) records of ``project_key``."""
        ...

    def closure_records(
        self, project_key: str, story_id: str
    ) -> Sequence[Mapping[str, object]]:
        """Return the closure (post-merge metrics) records of one story."""
        ...

    def qa_records(
        self, project_key: str, story_id: str
    ) -> Sequence[Mapping[str, object]]:
        """Return the canonical QA-outcome records of one story."""
        ...


def _record_to_jsonable(record: Any) -> dict[str, object]:
    """Serialize a frozen dataclass record to a JSON-ready dict (UTC-safe)."""
    raw = dataclasses.asdict(record)
    serializable = json.loads(json.dumps(raw, default=str, sort_keys=True))
    return cast("dict[str, object]", serializable)


class _FacadeCanonicalStateReadPort:
    """Productive :class:`CanonicalStateReadPort` over the state-backend facade.

    Reads the canonical records through the existing global state-backend READ
    API (``load_projects`` / ``load_story_contexts_global`` /
    ``load_execution_events_for_project_global`` / ``load_latest_story_metrics_
    global``). The same surface serves SQLite (dev/test) and Postgres (Core); a
    backend/transport failure propagates (fail-closed).

    Args:
        store_dir: Explicit SQLite store root for the project/story/metrics
            global reads; ``None`` resolves the configured default (ignored by
            Postgres, which reads its single global database).
    """

    def __init__(self, store_dir: Path | None = None) -> None:
        self._store_dir = store_dir

    def project_keys(self) -> Sequence[str]:
        # AG3-136: read the project catalog through the published ProjectRepository
        # port (via the sanctioned composition-root wiring seam) instead of importing
        # the generic ``state_backend.store`` facade loader directly. ``load_projects``
        # is pinned to the state-backend project-catalog read surface by
        # ``read_surface_rule.project_catalog_read_surface`` (FK-07 §7.9); A-code
        # (this installer BC) must consume it via the published port. Behaviour is
        # identical (the adapter's ``list()`` delegates to the same loader).
        from agentkit.backend.bootstrap.composition_root import (
            build_project_repository,
        )

        repository = build_project_repository(self._store_dir)
        return [project.key for project in repository.list()]

    def story_ids(self, project_key: str) -> Sequence[str]:
        contexts = self._story_repo().list_story_contexts(project_key)
        return [context.story_id for context in contexts]

    def audit_trail_records(self, project_key: str) -> Sequence[Mapping[str, object]]:
        # AG3-128: route the project-scoped execution-event read through the
        # sanctioned composition-root wiring seam instead of importing the
        # generic ``state_backend.store`` facade loader directly. The
        # ``load_execution_events_for_project_global`` loader is pinned to the
        # state-backend telemetry read surface + composition root by
        # ``read_surface_rule.telemetry_project_read_surface`` (FK-07 §7.7.5);
        # A-code (this installer BC) must consume it via the published seam, not
        # by direct facade coupling.
        from agentkit.backend.bootstrap.composition_root import (
            cli_load_execution_events_for_project_global,
        )

        events = cli_load_execution_events_for_project_global(project_key)
        return [_record_to_jsonable(event) for event in events]

    def closure_records(
        self, project_key: str, story_id: str
    ) -> Sequence[Mapping[str, object]]:
        metrics = self._story_repo().load_latest_story_metrics(project_key, story_id)
        return [_record_to_jsonable(metrics)] if metrics is not None else []

    def qa_records(
        self, project_key: str, story_id: str
    ) -> Sequence[Mapping[str, object]]:
        metrics = self._story_repo().load_latest_story_metrics(project_key, story_id)
        if metrics is None:
            return []
        # The canonical closure-time QA outcome (qa_rounds + adversarial
        # findings/tests + final status) is persisted globally on BOTH backends
        # via StoryMetricsRecord (FK-29). The per-attempt qa_stage_results /
        # qa_findings read model is Postgres-only (sqlite_store.load_qa_stage_
        # result_rows raises), so the backend-agnostic QA truth is sourced here.
        return [
            {
                "project_key": metrics.project_key,
                "story_id": metrics.story_id,
                "run_id": metrics.run_id,
                "final_status": metrics.final_status,
                "qa_rounds": metrics.qa_rounds,
                "adversarial_findings": metrics.adversarial_findings,
                "adversarial_tests_created": metrics.adversarial_tests_created,
            }
        ]

    def _story_repo(self) -> Any:
        # The story-read loaders (story context / latest metrics) may only be
        # reached through the explicit story-repository surface (architecture
        # conformance AC004); this adapter never imports the global loaders.
        from agentkit.backend.state_backend.store.story_read_repository import (
            StateBackendStoryReadRepository,
        )

        return StateBackendStoryReadRepository(self._store_dir)


class CanonicalStateExporter:
    """Default exporter: a REAL export of the canonical state (not a manifest).

    Reads the canonical audit-trail / closure / QA records through the state-
    backend READ API and serializes them as real JSONL artifacts (one record per
    line) into the operator-supplied destination, plus a manifest that indexes
    the written files and their record counts. Fail-closed: a backend/transport
    read error or a write error propagates, so :func:`decommission_core` aborts
    BEFORE any service teardown (nothing torn down on export failure).

    The full ``pg_dump``/volume snapshot remains an ops step (§10.2.5); this
    serializes the canonical CONTENT the mandatory-export precondition protects
    (audit trail / closure records / QA results) so a core-decommission can never
    destroy services while that content is unexported.

    Args:
        store_dir: Explicit SQLite store root for the default facade read port
            (ignored by Postgres). Unused when ``reader`` is supplied.
        reader: Injectable canonical-state read port (defaults to the facade
            adapter); the seam keeps the productive default real while tests can
            drive a recording/raising port.
    """

    def __init__(
        self,
        *,
        store_dir: Path | None = None,
        reader: CanonicalStateReadPort | None = None,
    ) -> None:
        self._reader: CanonicalStateReadPort = (
            reader if reader is not None else _FacadeCanonicalStateReadPort(store_dir)
        )

    def export(self, export_dir: Path) -> Path:
        export_dir.mkdir(parents=True, exist_ok=True)
        audit_trail: list[Mapping[str, object]] = []
        closure_records: list[Mapping[str, object]] = []
        qa_results: list[Mapping[str, object]] = []
        for project_key in self._reader.project_keys():
            audit_trail.extend(self._reader.audit_trail_records(project_key))
            for story_id in self._reader.story_ids(project_key):
                closure_records.extend(
                    self._reader.closure_records(project_key, story_id)
                )
                qa_results.extend(self._reader.qa_records(project_key, story_id))

        _write_jsonl(export_dir / _AUDIT_TRAIL_FILE, audit_trail)
        _write_jsonl(export_dir / _CLOSURE_RECORDS_FILE, closure_records)
        _write_jsonl(export_dir / _QA_RESULTS_FILE, qa_results)

        manifest_path = export_dir / _MANIFEST_FILE
        payload = {
            "export_kind": "state-backend",
            "exported_at": datetime.now(UTC).isoformat(),
            "records": {
                "audit_trail": {
                    "file": _AUDIT_TRAIL_FILE,
                    "count": len(audit_trail),
                },
                "closure_records": {
                    "file": _CLOSURE_RECORDS_FILE,
                    "count": len(closure_records),
                },
                "qa_results": {
                    "file": _QA_RESULTS_FILE,
                    "count": len(qa_results),
                },
            },
            "note": (
                "Mandatory pre-decommission export (FK-10 §10.2.9): the canonical "
                "audit-trail / closure / QA records read from the state backend, "
                "serialized as JSONL. The DB volume is preserved; "
                "'docker compose down -v' is forbidden during the service teardown."
            ),
        }
        manifest_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
        )
        return manifest_path


def _write_jsonl(path: Path, records: Sequence[Mapping[str, object]]) -> None:
    """Write ``records`` as JSON Lines (one canonical JSON object per line)."""
    lines = [json.dumps(record, sort_keys=True) for record in records]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


__all__ = [
    "CanonicalStateExporter",
    "CanonicalStateReadPort",
    "CoreDecommissionError",
    "CoreDecommissionRequest",
    "CoreDecommissionResult",
    "DecommissionLevel",
    "MachineDecommissionError",
    "MachineDecommissionResult",
    "PinnedProject",
    "ServiceController",
    "ServiceTeardownError",
    "StateBackendExporter",
    "decommission_core",
    "decommission_machine",
]
