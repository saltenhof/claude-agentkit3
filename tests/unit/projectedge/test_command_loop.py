"""Edge command-loop wiring: fetch -> execute -> report with own op_id (AG3-145 B).

Uses a recording fake client for the wire calls; the executor path runs real
git for the provision case (MOCKS/STUBS rule -- real dev-local git) and the
pure error-result path for the loop-mechanics case.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.config.models import (
    SUPPORTED_CONFIG_VERSION,
    Features,
    JenkinsConfig,
    PipelineConfig,
    ProjectConfig,
    RepositoryConfig,
    SonarQubeConfig,
)
from agentkit.backend.control_plane.models import (
    EdgeCommandMutationResult,
    EdgeCommandResultRequest,
    EdgeCommandView,
    OpenEdgeCommandsResponse,
)
from agentkit.harness_client.projectedge.command_executor import process_open_commands

if TYPE_CHECKING:
    from pathlib import Path


class _RecordingClient:
    """A fake ProjectEdgeClient recording the fetch + report calls."""

    def __init__(self, commands: list[EdgeCommandView]) -> None:
        self._commands = commands
        self.fetch_calls: list[tuple[str, str, str]] = []
        self.reported: list[tuple[str, EdgeCommandResultRequest]] = []

    def fetch_open_commands(
        self, *, run_id: str, project_key: str, session_id: str
    ) -> OpenEdgeCommandsResponse:
        self.fetch_calls.append((run_id, project_key, session_id))
        return OpenEdgeCommandsResponse(commands=self._commands)

    def report_command_result(
        self, *, command_id: str, request: EdgeCommandResultRequest
    ) -> EdgeCommandMutationResult:
        self.reported.append((command_id, request))
        return EdgeCommandMutationResult(
            status="completed", command_id=command_id, op_id=request.op_id
        )


def _project_config(project_root: Path, repo_names: list[str]) -> ProjectConfig:
    return ProjectConfig(
        project_key="test-project",
        project_name="Test Project",
        repositories=[
            RepositoryConfig(name=name, path=project_root / name) for name in repo_names
        ],
        pipeline=PipelineConfig(
            config_version=SUPPORTED_CONFIG_VERSION,
            features=Features(multi_llm=False),
            sonarqube=SonarQubeConfig(available=False, enabled=False),
            ci=JenkinsConfig(available=False, enabled=False),
        ),
    )


def _command(command_id: str, kind: str, payload: dict[str, object]) -> EdgeCommandView:
    return EdgeCommandView(
        command_id=command_id,
        command_kind=kind,
        payload=payload,
        status="delivered",
        created_at=datetime(2026, 7, 5, 12, 0, tzinfo=UTC),
    )


def test_loop_reports_each_command_with_a_fresh_client_op_id(tmp_path: Path) -> None:
    """The loop fetches, executes and reports each command with its OWN op_id."""
    commands = [
        _command("cmd-a", "sync_push", {"repo_id": "api"}),
        _command("cmd-b", "merge_local", {"repo_id": "api"}),
    ]
    client = _RecordingClient(commands)
    config = _project_config(tmp_path, ["api"])

    outcomes = process_open_commands(
        client,  # type: ignore[arg-type]
        project_config=config,
        project_root=tmp_path,
        run_id="run-1",
        project_key="test-project",
        session_id="sess-A",
        story_id="AG3-700",
    )

    assert client.fetch_calls == [("run-1", "test-project", "sess-A")]
    assert [command_id for command_id, _ in client.reported] == ["cmd-a", "cmd-b"]
    op_ids = [request.op_id for _, request in client.reported]
    # Every reported op_id is a non-empty, distinct client-minted key (Rule 5).
    assert all(op_id for op_id in op_ids)
    assert len(set(op_ids)) == len(op_ids)
    # An edge-unknown kind still reports a deterministic result (no silent no-op).
    for _, request in client.reported:
        assert request.result.result_type == "command_error"
    assert len(outcomes) == 2


@pytest.mark.requires_git
def test_loop_executes_real_provision_and_reports_worktree_report(tmp_path: Path) -> None:
    repo_root = tmp_path / "api"
    repo_root.mkdir(parents=True)
    subprocess.run(["git", "-C", str(repo_root), "init", "-q", "-b", "main"], check=True)
    subprocess.run(["git", "-C", str(repo_root), "config", "user.email", "t@x"], check=True)
    subprocess.run(["git", "-C", str(repo_root), "config", "user.name", "T"], check=True)
    subprocess.run(["git", "-C", str(repo_root), "config", "commit.gpgsign", "false"], check=True)
    (repo_root / "README.md").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo_root), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(repo_root), "commit", "-q", "-m", "seed"], check=True)

    commands = [
        _command(
            "cmd-prov",
            "provision_worktree",
            {
                "story_id": "AG3-700", "project_key": "test-project", "run_id": "run-1",
                "repo_id": "api", "branch": "story/AG3-700", "base_ref": "main",
            },
        )
    ]
    client = _RecordingClient(commands)
    config = _project_config(tmp_path, ["api"])

    process_open_commands(
        client,  # type: ignore[arg-type]
        project_config=config,
        project_root=tmp_path,
        run_id="run-1",
        project_key="test-project",
        session_id="sess-A",
        story_id="AG3-700",
    )

    assert len(client.reported) == 1
    _, request = client.reported[0]
    assert request.result.result_type == "worktree_report"
    assert (repo_root / "worktrees" / "AG3-700").is_dir()
