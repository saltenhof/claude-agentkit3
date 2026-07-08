"""Real-filesystem integration tests for level-1/2 decommission (AG3-122).

Machine-uninstall (level 2) warns pinned projects as ``orphaned`` before removing
a bundle version on the real filesystem; core-decommission (level 1) is
destructive and fails closed without confirmation AND a mandatory export, and the
DB volume survives a service uninstall (``down -v`` forbidden) (FK-10 §10.2.9).
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.closure.post_merge_finalization.records import StoryMetricsRecord
from agentkit.backend.installer.lifecycle.decommission import (
    CanonicalStateExporter,
    CoreDecommissionError,
    CoreDecommissionRequest,
    MachineDecommissionError,
    PinnedProject,
    ServiceTeardownError,
    decommission_core,
    decommission_machine,
)
from agentkit.backend.project_management.entities import Project, ProjectConfiguration
from agentkit.backend.skills import create_directory_link
from agentkit.backend.state_backend.config import (
    ALLOW_SQLITE_ENV,
    STATE_BACKEND_ENV,
    STORE_DIR_ENV,
)
from agentkit.backend.state_backend.project_store import save_project
from agentkit.backend.state_backend.store import facade
from agentkit.backend.story_context_manager.models import StoryContext
from agentkit.backend.story_context_manager.types import (
    ImplementationContract,
    StoryMode,
    StoryType,
)
from agentkit.backend.telemetry.contract.records import ExecutionEventRecord

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

_PROJECT = "tenant-a"
_STORY = "AG3-900"
_RUN = "run-900"
_NOW = datetime(2026, 6, 20, 9, 0, tzinfo=UTC)


@pytest.fixture
def sqlite_store(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Iterator[Path]:
    """A real, seeded SQLite state backend for the canonical-export tests."""
    store = tmp_path / "state-store"
    store.mkdir()
    monkeypatch.setenv(STATE_BACKEND_ENV, "sqlite")
    monkeypatch.setenv(ALLOW_SQLITE_ENV, "1")
    monkeypatch.setenv(STORE_DIR_ENV, str(store))
    facade.reset_backend_cache_for_tests()
    yield store
    facade.reset_backend_cache_for_tests()


def _seed_canonical_state(store: Path) -> None:
    """Seed real audit-trail / closure / QA records into the SQLite backend."""
    save_project(
        Project(
            key=_PROJECT,
            name="Tenant A",
            story_id_prefix="AG3",
            configuration=ProjectConfiguration(
                repo_url="",
                default_branch="main",
                default_worker_count=1,
                repositories=["app"],
            ),
        ),
        store_dir=store,
    )
    facade.save_story_context_global(
        store,
        StoryContext(
            project_key=_PROJECT,
            story_id=_STORY,
            story_type=StoryType.IMPLEMENTATION,
            execution_route=StoryMode.EXECUTION,
            implementation_contract=ImplementationContract.STANDARD,
            title="Decommission export story",
            labels=["size:medium"],
            participating_repos=["app"],
            created_at=_NOW,
        ),
    )
    # Closure record (post-merge metrics) — also the canonical QA outcome source.
    facade.upsert_story_metrics(
        store,
        StoryMetricsRecord(
            project_key=_PROJECT,
            story_id=_STORY,
            run_id=_RUN,
            story_type="implementation",
            story_size="medium",
            mode="standard",
            processing_time_min=12.0,
            qa_rounds=2,
            increments=1,
            final_status="DONE",
            completed_at="2026-06-20T10:00:00+00:00",
            adversarial_findings=3,
            adversarial_tests_created=4,
        ),
    )
    # Audit-trail record (execution event).
    facade.append_execution_event_global(
        ExecutionEventRecord(
            project_key=_PROJECT,
            story_id=_STORY,
            run_id=_RUN,
            event_id="evt-900",
            event_type="node_result",
            occurred_at=_NOW,
            source_component="pipeline-engine",
            severity="info",
            phase="implementation",
            payload={"order": 1},
        ),
    )


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    text = path.read_text(encoding="utf-8").strip()
    return [json.loads(line) for line in text.splitlines() if line]


class _RecordingController:
    """Records whether the teardown was invoked (proves export-first ordering)."""

    def __init__(self) -> None:
        self.stopped = False

    def stop_services(self) -> Sequence[str]:
        self.stopped = True
        return ("backend", "frontend")


class _StubExporter:
    def __init__(self) -> None:
        self.calls: list[Path] = []

    def export(self, export_dir: Path) -> Path:
        self.calls.append(export_dir)
        export_dir.mkdir(parents=True, exist_ok=True)
        artifact = export_dir / "export.json"
        artifact.write_text("{}", encoding="utf-8")
        return artifact


class _VolumePreservingController:
    """Stops services like a ``docker compose down`` WITHOUT ``-v``.

    It is handed the DB volume path so the test can prove the service teardown
    never deletes it (the ``down -v`` footgun is not taken).
    """

    def __init__(self, db_volume: Path) -> None:
        self._db_volume = db_volume

    def stop_services(self) -> tuple[str, ...]:
        # A correct teardown leaves the DB volume in place (no `down -v`).
        assert self._db_volume.exists()
        return ("backend", "frontend")


def _make_bundle_store(tmp_path: Path, versions: tuple[str, ...]) -> Path:
    store = tmp_path / "bundles"
    for version in versions:
        version_dir = store / version
        version_dir.mkdir(parents=True)
        (version_dir / "bundle.json").write_text("{}", encoding="utf-8")
    return store


def test_machine_uninstall_warns_orphaned_before_removing_bundle(
    tmp_path: Path,
) -> None:
    store = _make_bundle_store(tmp_path, ("1.0.0", "2.0.0"))
    pinned = [
        PinnedProject(project_key="proj-a", bundle_version="1.0.0", project_root="/p/a"),
        PinnedProject(project_key="proj-b", bundle_version="2.0.0", project_root="/p/b"),
    ]

    result = decommission_machine(
        bundle_store_root=store, pinned_projects=pinned, bundle_version="1.0.0"
    )

    assert result.removed_bundle_versions == ("1.0.0",)
    assert result.orphaned_projects == ("proj-a",)
    # The removed version is gone; the unrelated version survives.
    assert not (store / "1.0.0").exists()
    assert (store / "2.0.0").is_dir()


def test_machine_uninstall_preserves_pinned_project_repos(tmp_path: Path) -> None:
    store = _make_bundle_store(tmp_path, ("1.0.0",))
    project_repo = tmp_path / "repo-a"
    project_repo.mkdir()
    (project_repo / "code.py").write_text("x = 1", encoding="utf-8")
    pinned = [
        PinnedProject(
            project_key="proj-a", bundle_version="1.0.0", project_root=str(project_repo)
        )
    ]

    decommission_machine(
        bundle_store_root=store, pinned_projects=pinned, bundle_version="1.0.0"
    )

    # A lower level never deletes the higher-level project repo (FK-10 §10.2.0).
    assert (project_repo / "code.py").read_text(encoding="utf-8") == "x = 1"


@pytest.mark.parametrize("malicious", ["..", "a/b", "a\\b", "."])
def test_machine_uninstall_rejects_path_traversal_bundle_version(
    tmp_path: Path, malicious: str
) -> None:
    """A traversal/non-single-name --bundle-version fails closed; nothing removed."""
    store = _make_bundle_store(tmp_path, ("1.0.0",))
    sibling = tmp_path / "victim"
    sibling.mkdir()
    (sibling / "keep.txt").write_text("important", encoding="utf-8")

    with pytest.raises(MachineDecommissionError):
        decommission_machine(
            bundle_store_root=store, pinned_projects=[], bundle_version=malicious
        )

    # Nothing removed: the store, its version dir, the sibling, and the parent
    # (the `..` target) all survive untouched.
    assert (store / "1.0.0").is_dir()
    assert (sibling / "keep.txt").read_text(encoding="utf-8") == "important"
    assert tmp_path.is_dir()


def test_machine_uninstall_rejects_absolute_bundle_version(tmp_path: Path) -> None:
    """An absolute-path --bundle-version cannot escape the store (fail-closed)."""
    store = _make_bundle_store(tmp_path, ("1.0.0",))
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("important", encoding="utf-8")

    with pytest.raises(MachineDecommissionError):
        decommission_machine(
            bundle_store_root=store,
            pinned_projects=[],
            bundle_version=str(outside),
        )

    # The absolute target outside the store is untouched.
    assert (outside / "keep.txt").read_text(encoding="utf-8") == "important"
    assert (store / "1.0.0").is_dir()


def test_machine_uninstall_removes_legitimate_single_version(tmp_path: Path) -> None:
    """A legitimate single version name is still removed after the guard."""
    store = _make_bundle_store(tmp_path, ("1.2.3", "4.5.6"))

    result = decommission_machine(
        bundle_store_root=store, pinned_projects=[], bundle_version="1.2.3"
    )

    assert result.removed_bundle_versions == ("1.2.3",)
    assert not (store / "1.2.3").exists()
    assert (store / "4.5.6").is_dir()


def test_core_decommission_aborts_without_confirmation(tmp_path: Path) -> None:
    request = CoreDecommissionRequest(confirm=False, export_dir=tmp_path / "export")
    with pytest.raises(CoreDecommissionError):
        decommission_core(
            request,
            service_controller=_VolumePreservingController(tmp_path / "db"),
            state_exporter=_StubExporter(),
        )


def test_core_decommission_aborts_without_mandatory_export(tmp_path: Path) -> None:
    request = CoreDecommissionRequest(confirm=True, export_dir=None)
    with pytest.raises(CoreDecommissionError):
        decommission_core(
            request,
            service_controller=_VolumePreservingController(tmp_path / "db"),
            state_exporter=_StubExporter(),
        )


def test_core_decommission_exports_first_and_preserves_db_volume(tmp_path: Path) -> None:
    db_volume = tmp_path / "pgdata"
    db_volume.mkdir()
    (db_volume / "state").write_text("canonical", encoding="utf-8")
    export_dir = tmp_path / "export"
    exporter = _StubExporter()

    result = decommission_core(
        CoreDecommissionRequest(confirm=True, export_dir=export_dir),
        service_controller=_VolumePreservingController(db_volume),
        state_exporter=exporter,
    )

    # Mandatory export ran BEFORE teardown and produced a real artifact.
    assert exporter.calls == [export_dir]
    assert result.exported_to.is_file()
    assert result.stopped_services == ("backend", "frontend")
    # The DB volume (canonical state) survives the service uninstall.
    assert result.db_volume_preserved is True
    assert (db_volume / "state").read_text(encoding="utf-8") == "canonical"


def test_core_decommission_default_exporter_serializes_real_records(
    sqlite_store: Path, tmp_path: Path
) -> None:
    """The DEFAULT exporter produces a REAL export of the canonical state.

    Seeds real audit-trail / closure / QA records in a real SQLite backend, runs
    the default :class:`CanonicalStateExporter`, and asserts the export dir holds
    the ACTUAL records (not just a manifest).
    """
    _seed_canonical_state(sqlite_store)
    export_dir = tmp_path / "export"
    controller = _RecordingController()

    result = decommission_core(
        CoreDecommissionRequest(confirm=True, export_dir=export_dir),
        service_controller=controller,
        state_exporter=CanonicalStateExporter(store_dir=sqlite_store),
    )

    # Export ran FIRST, then teardown.
    assert controller.stopped is True
    assert result.db_volume_preserved is True
    # Real audit-trail records (execution events), not a placeholder.
    audit = _read_jsonl(export_dir / "audit-trail.jsonl")
    assert any(record.get("event_id") == "evt-900" for record in audit)
    # Real closure records (post-merge metrics).
    closure = _read_jsonl(export_dir / "closure-records.jsonl")
    assert any(
        record.get("story_id") == _STORY and record.get("final_status") == "DONE"
        for record in closure
    )
    # Real QA outcome records.
    qa = _read_jsonl(export_dir / "qa-results.jsonl")
    assert any(
        record.get("story_id") == _STORY and record.get("qa_rounds") == 2
        for record in qa
    )
    # The manifest indexes the real files with their counts.
    manifest = json.loads(
        (export_dir / "state-backend-export-manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["records"]["audit_trail"]["count"] >= 1
    assert manifest["records"]["qa_results"]["count"] >= 1


def test_core_decommission_export_failure_aborts_before_teardown(
    tmp_path: Path,
) -> None:
    """Fail-closed: an unreadable backend aborts BEFORE any service teardown."""

    class _RaisingReader:
        def project_keys(self) -> Sequence[str]:
            msg = "state backend unreachable"
            raise RuntimeError(msg)

        def story_ids(self, project_key: str) -> Sequence[str]:
            return []

        def audit_trail_records(self, project_key: str) -> Sequence[dict[str, object]]:
            return []

        def closure_records(
            self, project_key: str, story_id: str
        ) -> Sequence[dict[str, object]]:
            return []

        def qa_records(
            self, project_key: str, story_id: str
        ) -> Sequence[dict[str, object]]:
            return []

    controller = _RecordingController()
    with pytest.raises(CoreDecommissionError):
        decommission_core(
            CoreDecommissionRequest(confirm=True, export_dir=tmp_path / "export"),
            service_controller=controller,
            state_exporter=CanonicalStateExporter(reader=_RaisingReader()),
        )
    # Nothing torn down on export failure.
    assert controller.stopped is False


def test_core_decommission_fails_closed_when_teardown_fails(tmp_path: Path) -> None:
    """A failing teardown surfaces fail-closed; no success result is produced."""

    class _FailingController:
        def stop_services(self) -> Sequence[str]:
            msg = "orchestrator unavailable"
            raise ServiceTeardownError(msg)

    with pytest.raises(ServiceTeardownError):
        decommission_core(
            CoreDecommissionRequest(confirm=True, export_dir=tmp_path / "export"),
            service_controller=_FailingController(),
            state_exporter=_StubExporter(),
        )


def test_default_controller_executes_teardown_without_down_v() -> None:
    """The productive default controller ACTUALLY runs ``docker compose down``.

    Stubs ``subprocess.run`` at the boundary (no Docker daemon needed) and asserts
    the default code path executes the real teardown argv — never ``down -v``.
    """
    from agentkit.backend.cli.lifecycle import _OperatorServiceController

    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []

    def fake_run(
        argv: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        calls.append((tuple(argv), kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    controller = _OperatorServiceController(runner=fake_run)
    stopped = controller.stop_services()

    assert tuple(stopped) == ("backend", "frontend")
    assert len(calls) == 1
    argv, kwargs = calls[0]
    assert argv == ("docker", "compose", "down")
    assert "-v" not in argv
    assert "--volumes" not in argv
    assert kwargs.get("check") is False


def test_default_controller_fails_closed_when_teardown_exits_nonzero() -> None:
    """A non-zero teardown exit fails closed — services are NOT reported stopped."""
    from agentkit.backend.cli.lifecycle import _OperatorServiceController

    def fake_run(
        argv: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="boom")

    controller = _OperatorServiceController(runner=fake_run)
    with pytest.raises(ServiceTeardownError):
        controller.stop_services()


def test_default_controller_fails_closed_when_command_unavailable() -> None:
    """An unavailable orchestrator fails closed instead of reporting success."""
    from agentkit.backend.cli.lifecycle import _OperatorServiceController

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        msg = "docker not found"
        raise FileNotFoundError(msg)

    controller = _OperatorServiceController(runner=fake_run)
    with pytest.raises(ServiceTeardownError):
        controller.stop_services()


def _directory_links_supported() -> bool:
    """Return whether the test filesystem can create a symlink or junction."""
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "src"
        src.mkdir()
        try:
            create_directory_link(Path(d) / "link", src)
        except OSError:
            return False
        return True


_LINKS_AVAILABLE = _directory_links_supported()


@pytest.mark.skipif(
    not _LINKS_AVAILABLE,
    reason="Filesystem supports neither symlinks nor directory junctions",
)
def test_machine_uninstall_rejects_reparse_point_store_root(tmp_path: Path) -> None:
    """A bundle store root that is a symlink/junction fails closed; nothing removed.

    Reproduces the §10.2.9 reparse-point escape: ``bundles -> ../central-state``.
    Were the root trusted, ``(root / version).resolve()`` would land inside the
    link target and the containment assertion would pass, so ``rmtree`` would
    delete THROUGH the link into ``central-state/1.0.0``. The verb must instead
    abort before any removal.
    """
    # The REAL outside directory the link points at (a higher-level artifact).
    central_state = tmp_path / "central-state"
    victim_version = central_state / "1.0.0"
    victim_version.mkdir(parents=True)
    (victim_version / "bundle.json").write_text("central", encoding="utf-8")

    # The bundle store root is itself a link to the outside directory.
    store_link = tmp_path / "bundles"
    create_directory_link(store_link, central_state)

    with pytest.raises(MachineDecommissionError):
        decommission_machine(
            bundle_store_root=store_link,
            pinned_projects=[],
            bundle_version="1.0.0",
        )

    # Nothing removed: the outside target and its children survive untouched.
    assert (victim_version / "bundle.json").read_text(encoding="utf-8") == "central"
    assert central_state.is_dir()


@pytest.mark.skipif(
    not _LINKS_AVAILABLE,
    reason="Filesystem supports neither symlinks nor directory junctions",
)
def test_machine_uninstall_rejects_reparse_point_version_entry(tmp_path: Path) -> None:
    """A version ENTRY that is a symlink/junction fails closed (no rmtree through it).

    The store root is a REAL directory, but one version slot is a link to an
    outside directory. ``rmtree`` through that link would destroy the target's
    contents (the detach footgun class). The verb must abort and leave the
    target's contents intact.
    """
    store = tmp_path / "bundles"
    store.mkdir()
    # A legitimate real version dir.
    (store / "1.0.0").mkdir()
    (store / "1.0.0" / "bundle.json").write_text("{}", encoding="utf-8")

    # An outside directory with contents that must survive.
    outside = tmp_path / "outside-target"
    outside.mkdir()
    (outside / "keep.txt").write_text("important", encoding="utf-8")

    # The version slot ``2.0.0`` is a link to the outside directory.
    create_directory_link(store / "2.0.0", outside)

    # Enumerate-all path: a single link entry aborts the whole verb (fail-closed).
    with pytest.raises(MachineDecommissionError):
        decommission_machine(
            bundle_store_root=store, pinned_projects=[], bundle_version=None
        )

    # The link target's CONTENTS survive (no rmtree recursed through the link),
    # and the real version dir is NOT removed either (nothing removed on abort).
    assert (outside / "keep.txt").read_text(encoding="utf-8") == "important"
    assert (store / "1.0.0" / "bundle.json").is_file()

    # The explicit --bundle-version path rejects the link entry the same way.
    with pytest.raises(MachineDecommissionError):
        decommission_machine(
            bundle_store_root=store, pinned_projects=[], bundle_version="2.0.0"
        )
    assert (outside / "keep.txt").read_text(encoding="utf-8") == "important"


@pytest.mark.skipif(
    not _LINKS_AVAILABLE,
    reason="Filesystem supports neither symlinks nor directory junctions",
)
def test_machine_uninstall_through_linked_parent_stays_contained_to_store(
    tmp_path: Path,
) -> None:
    """A store reached through a symlinked/junction PARENT stays contained.

    The store itself is a REAL directory; only an ANCESTOR is a link
    (``linked-parent -> central-state``, store = ``linked-parent/bundles``).
    The resolved-containment assertion resolves root and child consistently
    THROUGH the parent link, so removal is confined to ``<resolved-store>/
    <version>`` (a child of the resolved store). The store's siblings and the
    higher-level canonical state are NOT under the resolved store root, so they
    can never be touched — there is no escape (FK-10 §10.2.9 base rule).
    """
    central_state = tmp_path / "central-state"
    version_dir = central_state / "bundles" / "1.0.0"
    version_dir.mkdir(parents=True)
    (version_dir / "bundle.json").write_text("{}", encoding="utf-8")
    # A sibling of the store under the same canonical root that must survive.
    sibling = central_state / "sibling-canonical"
    sibling.mkdir()
    (sibling / "audit.db").write_text("canonical", encoding="utf-8")

    # The store is reached through a junction/symlink to its PARENT.
    linked_parent = tmp_path / "linked-parent"
    create_directory_link(linked_parent, central_state)
    store = linked_parent / "bundles"

    result = decommission_machine(
        bundle_store_root=store, pinned_projects=(), bundle_version="1.0.0"
    )

    # The legitimate in-store version is removed.
    assert result.removed_bundle_versions == ("1.0.0",)
    assert not (store / "1.0.0").exists()
    # Containment guarantee: removal never escaped the resolved store to touch
    # the store's sibling or the higher-level canonical state.
    assert (sibling / "audit.db").read_text(encoding="utf-8") == "canonical"
    assert central_state.is_dir()
