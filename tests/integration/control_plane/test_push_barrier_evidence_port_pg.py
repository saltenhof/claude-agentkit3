"""Integration: the PRODUCTIVE two-stage push-barrier evidence port (AG3-147 AC1/AC3).

Proves ``StateBackedPushBarrierEvidence`` maps the REAL two evidence sources onto
the A-core inputs: the Postgres push-freshness record (the Edge report) AND a
REAL ``git ls-remote`` ref-read (the server confirmation) via the productive
composition-root code-backend factory, over local bare-repo remotes. Both stages
are exercised for real -- a repo counts as verified-pushed only when the server
ref-read confirms the same head SHA the Edge reported (FK-91 §91.1b).
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.bootstrap.composition_root import _build_repo_code_backend_port
from agentkit.backend.control_plane.push_sync import (
    PushBarrierBlockCode,
    PushFreshnessRecord,
    SyncPointBarrierType,
    evaluate_push_barrier,
)
from agentkit.backend.control_plane.push_verification import (
    StateBackedPushBarrierEvidence,
)
from agentkit.backend.control_plane.workspace_locator import StoryWorkspace
from agentkit.backend.state_backend.story_closure_store import upsert_push_freshness_record_global

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.integration, pytest.mark.requires_git]

_NOW = datetime(2026, 7, 6, 10, 0, tzinfo=UTC)
_PROJECT = "tenant-a"
_STORY = "AG3-910"
_RUN = "run-910"
_BRANCH = "story/AG3-910"


@pytest.fixture(autouse=True)
def _isolated_postgres(postgres_isolated_schema: object) -> None:
    del postgres_isolated_schema


@dataclass(frozen=True)
class _FixedWorkspaceLocator:
    project_root: Path

    def resolve(self, project_key: str, story_id: str, run_id: str) -> StoryWorkspace:
        return StoryWorkspace(
            project_key=project_key,
            story_id=story_id,
            run_id=run_id,
            project_root=self.project_root,
            story_dir=self.project_root / "stories" / story_id,
        )


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True)


def _bare_remote_with_story_branch(
    tmp_path: Path, name: str, *, push: bool
) -> tuple[Path, str | None]:
    """Create a bare remote; optionally push ``story/{id}`` and return its SHA."""
    remote = tmp_path / f"{name}.git"
    subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
    work = tmp_path / f"{name}-work"
    work.mkdir()
    _git(work, "init", "-q", "-b", "main")
    _git(work, "config", "user.email", "t@example.com")
    _git(work, "config", "user.name", "T")
    _git(work, "config", "commit.gpgsign", "false")
    (work / "f.txt").write_text(f"{name}\n", encoding="utf-8")
    _git(work, "add", ".")
    _git(work, "commit", "-q", "-m", f"seed {_STORY}")
    sha: str | None = None
    if push:
        _git(work, "push", "-q", str(remote), f"HEAD:refs/heads/{_BRANCH}")
        sha = subprocess.run(
            ["git", "-C", str(work), "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
    return remote, sha


def _write_project_config(project_root: Path, remotes: dict[str, Path]) -> None:
    import yaml

    config_dir = project_root / ".agentkit" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "project.yaml").write_text(
        yaml.safe_dump(
            {
                "project_key": _PROJECT,
                "project_name": "Tenant A",
                "repositories": [
                    {"name": name, "path": str(project_root / name), "remote_url": str(remote)}
                    for name, remote in remotes.items()
                ],
                # 'concept' avoids the code-producing sonarqube-stanza requirement;
                # the barrier port only reads 'repositories' from the config.
                "story_types": ["concept"],
                "pipeline": {
                    "config_version": "3.0",
                    "features": {"multi_llm": False},
                },
            }
        ),
        encoding="utf-8",
    )


def _freshness(
    repo_id: str,
    head_sha: str | None,
    *,
    backlog: bool,
    sync_point_id: str = "phase_completion:op-910",
) -> PushFreshnessRecord:
    return PushFreshnessRecord(
        project_key=_PROJECT,
        story_id=_STORY,
        run_id=_RUN,
        repo_id=repo_id,
        last_reported_head_sha=head_sha,
        last_pushed_head_sha=head_sha if not backlog else None,
        last_reported_at=_NOW,
        last_sync_point_id=sync_point_id,
        last_command_id=f"{_RUN}::sync_push::{sync_point_id}::{repo_id}",
        backlog=backlog,
        backlog_detail=None if not backlog else "behind remote",
    )


def _port(project_root: Path) -> StateBackedPushBarrierEvidence:
    return StateBackedPushBarrierEvidence(
        workspace_locator=_FixedWorkspaceLocator(project_root),  # type: ignore[arg-type]
        code_backend_factory=_build_repo_code_backend_port,
    )


def test_port_verifies_when_server_confirms_the_reported_head(tmp_path: Path) -> None:
    """AC1: both stages agree -> the barrier passes over the REAL ls-remote read."""
    api_remote, api_sha = _bare_remote_with_story_branch(tmp_path, "api", push=True)
    assert api_sha is not None
    _write_project_config(tmp_path, {"api": api_remote})
    upsert_push_freshness_record_global(_freshness("api", api_sha, backlog=False))

    inputs = _port(tmp_path).collect_repo_inputs(
        project_key=_PROJECT,
        story_id=_STORY,
        run_id=_RUN,
        required_sync_point_id="phase_completion:op-910",
    )

    verdict = evaluate_push_barrier(SyncPointBarrierType.PHASE_COMPLETION, inputs)
    assert verdict.passed is True
    assert inputs[0].server_head_sha == api_sha


def test_port_blocks_stale_running_latest_even_when_server_matches(
    tmp_path: Path,
) -> None:
    """Regression: freshness=A and server=A from an old boundary is not enough."""
    api_remote, api_sha = _bare_remote_with_story_branch(tmp_path, "api", push=True)
    assert api_sha is not None
    _write_project_config(tmp_path, {"api": api_remote})
    upsert_push_freshness_record_global(
        _freshness("api", api_sha, backlog=False, sync_point_id="phase_completion:op-old")
    )

    inputs = _port(tmp_path).collect_repo_inputs(
        project_key=_PROJECT,
        story_id=_STORY,
        run_id=_RUN,
        required_sync_point_id="phase_completion:op-new",
    )

    verdict = evaluate_push_barrier(SyncPointBarrierType.PHASE_COMPLETION, inputs)
    assert verdict.passed is False
    assert verdict.repo_verdicts[0].block_code is (
        PushBarrierBlockCode.STALE_EDGE_PUSH_REPORT
    )


def test_port_blocks_teildivergenz_one_repo_not_on_remote(tmp_path: Path) -> None:
    """AC3: api is verified, web's branch is NOT on its remote (server unresolved)
    -> the barrier blocks even though api passes, over the REAL ls-remote read."""
    api_remote, api_sha = _bare_remote_with_story_branch(tmp_path, "api", push=True)
    web_remote, _ = _bare_remote_with_story_branch(tmp_path, "web", push=False)
    assert api_sha is not None
    _write_project_config(tmp_path, {"api": api_remote, "web": web_remote})
    upsert_push_freshness_record_global(_freshness("api", api_sha, backlog=False))
    # web's edge claims a push, but the server ref-read will not resolve it.
    upsert_push_freshness_record_global(_freshness("web", "f" * 40, backlog=False))

    inputs = _port(tmp_path).collect_repo_inputs(
        project_key=_PROJECT,
        story_id=_STORY,
        run_id=_RUN,
        required_sync_point_id="phase_completion:op-910",
    )

    verdict = evaluate_push_barrier(SyncPointBarrierType.PHASE_COMPLETION, inputs)
    assert verdict.passed is False
    assert "web" in verdict.blocking_repos
    assert "api" not in verdict.blocking_repos
