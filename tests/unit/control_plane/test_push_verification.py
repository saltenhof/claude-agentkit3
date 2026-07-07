"""Unit tests for the pushed-only evidence adapter."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentkit.backend.code_backend.provider_port import RefReadResult
from agentkit.backend.control_plane.push_sync import PushFreshnessRecord
from agentkit.backend.control_plane.push_verification import StateBackedPushBarrierEvidence
from agentkit.backend.control_plane.workspace_locator import StoryWorkspace

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import MonkeyPatch


_PROJECT = "tenant-a"
_STORY = "AG3-147"
_RUN = "run-147"
_SYNC_POINT = "phase_completion:bind-1"
_NOW = datetime(2026, 7, 7, 9, 0, tzinfo=UTC)


@dataclass(frozen=True)
class _Repo:
    name: str


@dataclass(frozen=True)
class _ProjectConfig:
    repositories: tuple[_Repo, ...]


@dataclass(frozen=True)
class _WorkspaceLocator:
    project_root: Path

    def resolve(self, project_key: str, story_id: str, run_id: str) -> StoryWorkspace:
        return StoryWorkspace(
            project_key=project_key,
            story_id=story_id,
            run_id=run_id,
            project_root=self.project_root,
            story_dir=self.project_root / "stories" / story_id,
        )


@dataclass(frozen=True)
class _CodeBackend:
    repo_id: str
    heads: dict[str, str | None]

    def ref_read(self, ref: str) -> RefReadResult:
        head = self.heads.get(self.repo_id)
        return RefReadResult(
            ref=ref,
            resolved=head is not None,
            head_sha=head,
            detail="resolved" if head is not None else "missing",
        )


def _freshness(repo_id: str, head_sha: str | None, *, backlog: bool) -> PushFreshnessRecord:
    return PushFreshnessRecord(
        project_key=_PROJECT,
        story_id=_STORY,
        run_id=_RUN,
        repo_id=repo_id,
        last_reported_head_sha=head_sha,
        last_pushed_head_sha=None if backlog else head_sha,
        last_reported_at=_NOW,
        last_sync_point_id=_SYNC_POINT,
        last_command_id=f"{_RUN}::sync_push::{_SYNC_POINT}::{repo_id}",
        backlog=backlog,
        backlog_detail="behind remote" if backlog else None,
    )


def _port(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
    *,
    repos: tuple[str, ...],
    freshness: dict[str, PushFreshnessRecord | None],
    server_heads: dict[str, str | None],
) -> StateBackedPushBarrierEvidence:
    monkeypatch.setattr(
        "agentkit.backend.control_plane.push_verification.load_project_config",
        lambda _root: _ProjectConfig(tuple(_Repo(repo) for repo in repos)),
    )
    monkeypatch.setattr(
        StateBackedPushBarrierEvidence,
        "_load_freshness",
        staticmethod(lambda _project, _story, _run, repo_id: freshness.get(repo_id)),
    )
    return StateBackedPushBarrierEvidence(
        workspace_locator=_WorkspaceLocator(tmp_path),  # type: ignore[arg-type]
        code_backend_factory=lambda repo, _root: _CodeBackend(repo.name, server_heads),  # type: ignore[arg-type]
    )


def test_collect_repo_inputs_maps_edge_and_server_evidence(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    head = "a" * 40

    inputs = _port(
        monkeypatch,
        tmp_path,
        repos=("api",),
        freshness={"api": _freshness("api", head, backlog=False)},
        server_heads={"api": head},
    ).collect_repo_inputs(
        project_key=_PROJECT,
        story_id=_STORY,
        run_id=_RUN,
        required_sync_point_id=_SYNC_POINT,
    )

    assert len(inputs) == 1
    assert inputs[0].repo_id == "api"
    assert inputs[0].edge_report_present is True
    assert inputs[0].edge_reported_pushed is True
    assert inputs[0].edge_reported_head_sha == head
    assert inputs[0].server_ref_resolved is True
    assert inputs[0].server_head_sha == head
    assert inputs[0].edge_report_sync_point_id == _SYNC_POINT
    assert inputs[0].required_sync_point_id == _SYNC_POINT


def test_collect_repo_inputs_treats_backlog_as_not_pushed(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    head = "b" * 40

    inputs = _port(
        monkeypatch,
        tmp_path,
        repos=("api",),
        freshness={"api": _freshness("api", head, backlog=True)},
        server_heads={"api": head},
    ).collect_repo_inputs(project_key=_PROJECT, story_id=_STORY, run_id=_RUN)

    assert inputs[0].edge_report_present is True
    assert inputs[0].edge_reported_pushed is False
    assert inputs[0].edge_reported_head_sha == head


def test_collect_repo_inputs_fails_closed_on_missing_edge_or_server(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    inputs = _port(
        monkeypatch,
        tmp_path,
        repos=("api", "web"),
        freshness={"api": None, "web": _freshness("web", "c" * 40, backlog=False)},
        server_heads={"api": "d" * 40, "web": None},
    ).collect_repo_inputs(project_key=_PROJECT, story_id=_STORY, run_id=_RUN)

    api, web = inputs
    assert api.edge_report_present is False
    assert api.edge_reported_pushed is False
    assert api.edge_reported_head_sha is None
    assert api.server_ref_resolved is True
    assert web.edge_report_present is True
    assert web.server_ref_resolved is False
    assert web.server_head_sha is None
