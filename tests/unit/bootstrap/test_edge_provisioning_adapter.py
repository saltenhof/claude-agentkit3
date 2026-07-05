"""Unit tests for the edge-provisioning coordinator adapter (AG3-145 Teilschritt C).

Drives :class:`SetupEdgeProvisioningCoordinator` over IN-MEMORY repository fakes
(no Postgres, no edge process): proves the idempotent commission-then-read cycle,
the fail-closed PENDING while a command is open, the per-repo evidence mapping,
the provisioning worktree-map read, the failure-report handling, and the
fail-closed missing-ownership guard.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agentkit.backend.bootstrap.edge_provisioning_adapter import (
    SetupEdgeProvisioningCoordinator,
)
from agentkit.backend.control_plane.ownership import OwnershipAcquisition, OwnershipStatus
from agentkit.backend.control_plane.records import (
    EdgeCommandRecord,
    RunOwnershipRecord,
    TakeoverTransferRecord,
)
from agentkit.backend.control_plane.repository import (
    EdgeCommandRepository,
    RunOwnershipRepository,
    TakeoverTransferRepository,
)
from agentkit.backend.exceptions import ConfigError

_NOW = datetime(2026, 7, 5, tzinfo=UTC)
_PROJECT = "proj"
_STORY = "AG3-900"
_RUN = "run-900"
_SESSION = "sess-owner"


def _ownership_repo(*, run_id: str = _RUN) -> RunOwnershipRepository:
    record = RunOwnershipRecord(
        project_key=_PROJECT,
        story_id=_STORY,
        run_id=run_id,
        owner_session_id=_SESSION,
        ownership_epoch=1,
        status=OwnershipStatus.ACTIVE,
        acquired_via=OwnershipAcquisition.SETUP,
        acquired_at=_NOW,
        audit_ref="audit:x",
    )
    return RunOwnershipRepository(load_active_ownership=lambda _pk, _sid: record)


class _CommandStore:
    """In-memory Edge-Command-Queue fake."""

    def __init__(self) -> None:
        self.records: dict[str, EdgeCommandRecord] = {}

    def insert(self, record: EdgeCommandRecord) -> None:
        self.records[record.command_id] = record

    def load(self, command_id: str) -> EdgeCommandRecord | None:
        return self.records.get(command_id)

    def report(
        self, command_id: str, *, result_type: str, payload: dict[str, object]
    ) -> None:
        current = self.records[command_id]
        self.records[command_id] = replace(
            current,
            status="completed",
            result_type=result_type,
            result_payload=payload,
            result_op_id="op-x",
            completed_at=_NOW,
        )

    def repo(self) -> EdgeCommandRepository:
        return EdgeCommandRepository(insert_command=self.insert, load_command=self.load)


def _coordinator(
    store: _CommandStore,
    *,
    transfer: TakeoverTransferRecord | None = None,
    remote_head: str | None = None,
    run_id: str = _RUN,
) -> SetupEdgeProvisioningCoordinator:
    return SetupEdgeProvisioningCoordinator(
        edge_commands=store.repo(),
        ownership_repo=_ownership_repo(run_id=run_id),
        transfer_repo=TakeoverTransferRepository(
            load_transfer=lambda *_a: transfer,
        ),
        remote_head_reader=lambda _repo, _branch: remote_head,
    )


def test_probe_commission_is_pending_then_ready() -> None:
    store = _CommandStore()
    coordinator = _coordinator(store)

    first = coordinator.ensure_preflight_probes(
        project_key=_PROJECT,
        story_id=_STORY,
        run_id=_RUN,
        repos=("repo-a",),
        branch="story/AG3-900",
    )
    assert first.pending is True
    # Exactly one command commissioned, scoped to the owning session/epoch.
    (record,) = store.records.values()
    assert record.command_kind == "preflight_probe"
    assert record.session_id == _SESSION
    assert record.ownership_epoch == 1

    # A re-entry BEFORE the edge reports stays pending -- idempotent, no duplicate.
    second = coordinator.ensure_preflight_probes(
        project_key=_PROJECT, story_id=_STORY, run_id=_RUN,
        repos=("repo-a",), branch="story/AG3-900",
    )
    assert second.pending is True
    assert len(store.records) == 1

    # Edge reports -> ready, evidence mapped, ownership context present.
    store.report(
        record.command_id,
        result_type="preflight_probe_report",
        payload={
            "result_type": "preflight_probe_report",
            "repo_id": "repo-a",
            "branch_present": True,
            "head_sha": "abc",
        },
    )
    ready = coordinator.ensure_preflight_probes(
        project_key=_PROJECT, story_id=_STORY, run_id=_RUN,
        repos=("repo-a",), branch="story/AG3-900",
    )
    assert ready.pending is False
    evidence = ready.evidence["repo-a"]
    assert evidence is not None
    assert evidence.branch_present is True
    assert evidence.head_sha == "abc"
    assert ready.ownership is not None
    assert ready.ownership.own_session_active_ownership is True


def test_probe_takeover_base_flows_from_transfer_record() -> None:
    store = _CommandStore()
    transfer = TakeoverTransferRecord(
        project_key=_PROJECT,
        story_id=_STORY,
        run_id=_RUN,
        ownership_epoch=1,
        repo_id="repo-a",
        takeover_base_sha="base-sha",
    )
    coordinator = _coordinator(store, transfer=transfer, remote_head="remote-sha")
    coordinator.ensure_preflight_probes(
        project_key=_PROJECT, story_id=_STORY, run_id=_RUN,
        repos=("repo-a",), branch="story/AG3-900",
    )
    (record,) = store.records.values()
    store.report(
        record.command_id,
        result_type="preflight_probe_report",
        payload={
            "result_type": "preflight_probe_report",
            "repo_id": "repo-a",
            "branch_present": True,
            "head_sha": "base-sha",
        },
    )
    ready = coordinator.ensure_preflight_probes(
        project_key=_PROJECT, story_id=_STORY, run_id=_RUN,
        repos=("repo-a",), branch="story/AG3-900",
    )
    evidence = ready.evidence["repo-a"]
    assert evidence is not None
    assert evidence.takeover_base_sha == "base-sha"
    assert evidence.remote_head_sha == "remote-sha"


def test_unreadable_probe_result_maps_to_none() -> None:
    store = _CommandStore()
    coordinator = _coordinator(store)
    coordinator.ensure_preflight_probes(
        project_key=_PROJECT, story_id=_STORY, run_id=_RUN,
        repos=("repo-a",), branch="story/AG3-900",
    )
    (record,) = store.records.values()
    # The edge reported a command_error (unsupported/failed) -> not readable.
    store.report(
        record.command_id,
        result_type="command_error",
        payload={"result_type": "command_error", "error_code": "x", "message": "y"},
    )
    ready = coordinator.ensure_preflight_probes(
        project_key=_PROJECT, story_id=_STORY, run_id=_RUN,
        repos=("repo-a",), branch="story/AG3-900",
    )
    assert ready.pending is False
    assert ready.evidence["repo-a"] is None


def test_provisioning_reads_worktree_root_from_report() -> None:
    store = _CommandStore()
    coordinator = _coordinator(store)
    first = coordinator.ensure_provisioning(
        project_key=_PROJECT, story_id=_STORY, run_id=_RUN,
        repos=("repo-a",), branch="story/AG3-900", base_ref="main",
    )
    assert first.pending is True
    (record,) = store.records.values()
    assert record.command_kind == "provision_worktree"
    store.report(
        record.command_id,
        result_type="worktree_report",
        payload={
            "result_type": "worktree_report",
            "repo_id": "repo-a",
            "outcome": "provisioned",
            "worktree_root": "/dev/wt/AG3-900",
        },
    )
    ready = coordinator.ensure_provisioning(
        project_key=_PROJECT, story_id=_STORY, run_id=_RUN,
        repos=("repo-a",), branch="story/AG3-900", base_ref="main",
    )
    assert ready.pending is False
    assert ready.worktree_map == {"repo-a": Path("/dev/wt/AG3-900")}
    assert ready.failed_repos == ()


def test_provisioning_failure_report_is_a_failed_repo() -> None:
    store = _CommandStore()
    coordinator = _coordinator(store)
    coordinator.ensure_provisioning(
        project_key=_PROJECT, story_id=_STORY, run_id=_RUN,
        repos=("repo-a",), branch="story/AG3-900", base_ref="main",
    )
    (record,) = store.records.values()
    store.report(
        record.command_id,
        result_type="command_error",
        payload={"result_type": "command_error", "error_code": "e", "message": "m"},
    )
    ready = coordinator.ensure_provisioning(
        project_key=_PROJECT, story_id=_STORY, run_id=_RUN,
        repos=("repo-a",), branch="story/AG3-900", base_ref="main",
    )
    assert ready.pending is False
    assert ready.failed_repos == ("repo-a",)
    assert ready.worktree_map == {}


def test_missing_own_active_ownership_fails_closed() -> None:
    store = _CommandStore()
    # The active ownership record belongs to a DIFFERENT run -> fail-closed.
    coordinator = _coordinator(store, run_id="other-run")
    with pytest.raises(ConfigError, match="no active run-ownership record"):
        coordinator.ensure_preflight_probes(
            project_key=_PROJECT, story_id=_STORY, run_id=_RUN,
            repos=("repo-a",), branch="story/AG3-900",
        )
