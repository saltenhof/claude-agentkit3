"""Edge command-loop wiring: fetch -> execute -> report with own op_id (AG3-145 B).

Uses a recording fake client for the wire calls; the executor path runs real
git for the provision case (MOCKS/STUBS rule -- real dev-local git) and the
pure error-result path for the loop-mechanics case.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from types import SimpleNamespace
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
    ProjectEdgeSyncRequest,
    TakeoverReconcileWorktreeRequest,
)
from agentkit.harness_client.projectedge.command_executor import (
    EdgeGitError,
    process_open_commands,
)

if TYPE_CHECKING:
    from pathlib import Path


class _RecordingClient:
    """A fake ProjectEdgeClient recording the fetch + report calls."""

    def __init__(
        self,
        commands: list[EdgeCommandView],
        *,
        reconcile_status: str = "resolved",
        reconcile_error_code: str | None = None,
    ) -> None:
        self._commands = commands
        self._reconcile_status = reconcile_status
        self._reconcile_error_code = reconcile_error_code
        self.fetch_calls: list[tuple[str, str, str]] = []
        self.reported: list[tuple[str, EdgeCommandResultRequest]] = []
        self.reconcile_calls: list[tuple[str, TakeoverReconcileWorktreeRequest]] = []
        self.sync_calls: list[ProjectEdgeSyncRequest] = []
        self.unreadable_freeze_roots: list[Path] = []

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

    def reconcile_takeover_worktree(
        self, *, run_id: str, request: TakeoverReconcileWorktreeRequest
    ) -> object:
        self.reconcile_calls.append((run_id, request))
        return SimpleNamespace(
            status=self._reconcile_status,
            error_code=self._reconcile_error_code,
        )

    def sync(self, request: ProjectEdgeSyncRequest) -> None:
        self.sync_calls.append(request)

    def publish_unreadable_freeze_state(
        self, *, worktree_roots: list[Path]
    ) -> None:
        self.unreadable_freeze_roots.extend(worktree_roots)


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
        _command("cmd-a", "unknown_kind", {"repo_id": "api"}),
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


def test_loop_leaves_unreadable_takeover_command_open(tmp_path: Path) -> None:
    client = _RecordingClient(
        [_command("cmd-bad-reconcile", "takeover_reconcile", {"repo_id": "api"})]
    )

    with pytest.raises(EdgeGitError, match="payload was unreadable"):
        process_open_commands(
            client,  # type: ignore[arg-type]
            project_config=_project_config(tmp_path, ["api"]),
            project_root=tmp_path,
            run_id="run-1",
            project_key="test-project",
            session_id="sess-B",
            story_id="AG3-700",
        )

    assert client.reconcile_calls == []
    assert client.reported == []


def test_loop_rejects_genuinely_unaccepted_takeover_status(tmp_path: Path) -> None:
    repo_root = tmp_path / "api"
    repo_root.mkdir(parents=True)
    subprocess.run(["git", "-C", str(repo_root), "init", "-q", "-b", "main"], check=True)
    subprocess.run(["git", "-C", str(repo_root), "config", "user.email", "t@x"], check=True)
    subprocess.run(["git", "-C", str(repo_root), "config", "user.name", "T"], check=True)
    (repo_root / "README.md").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo_root), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(repo_root), "commit", "-q", "-m", "seed"], check=True)
    base_sha = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    client = _RecordingClient(
        [
            _command(
                "cmd-bad-status",
                "takeover_reconcile",
                {
                    "story_id": "AG3-700",
                    "project_key": "test-project",
                    "run_id": "run-1",
                    "repo_id": "api",
                    "takeover_base_sha": base_sha,
                },
            )
        ],
        reconcile_status="rejected",
        reconcile_error_code="object_claim_conflict",
    )

    with pytest.raises(EdgeGitError, match="result was not accepted"):
        process_open_commands(
            client,  # type: ignore[arg-type]
            project_config=_project_config(tmp_path, ["api"]),
            project_root=tmp_path,
            run_id="run-1",
            project_key="test-project",
            session_id="sess-B",
            story_id="AG3-700",
        )

    assert client.sync_calls == []
    assert client.reported == []


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


@pytest.mark.requires_git
def test_loop_aggregates_multi_repo_takeover_results_through_official_route(
    tmp_path: Path,
) -> None:
    base_by_repo: dict[str, str] = {}
    for repo_id in ("api", "web"):
        repo_root = tmp_path / repo_id
        repo_root.mkdir(parents=True)
        subprocess.run(
            ["git", "-C", str(repo_root), "init", "-q", "-b", "main"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(repo_root), "config", "user.email", "t@x"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(repo_root), "config", "user.name", "T"],
            check=True,
        )
        (repo_root / "README.md").write_text(f"{repo_id}\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo_root), "add", "README.md"], check=True)
        subprocess.run(
            ["git", "-C", str(repo_root), "commit", "-q", "-m", "seed"],
            check=True,
        )
        base_by_repo[repo_id] = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    commands = [
        _command(
            f"cmd-{repo_id}",
            "takeover_reconcile",
            {
                "story_id": "AG3-700",
                "project_key": "test-project",
                "run_id": "run-1",
                "repo_id": repo_id,
                "takeover_base_sha": base_sha,
            },
        )
        for repo_id, base_sha in base_by_repo.items()
    ]
    client = _RecordingClient(commands)

    outcomes = process_open_commands(
        client,  # type: ignore[arg-type]
        project_config=_project_config(tmp_path, ["api", "web"]),
        project_root=tmp_path,
        run_id="run-1",
        project_key="test-project",
        session_id="sess-B",
        story_id="AG3-700",
    )

    assert len(outcomes) == 2
    assert len(client.reconcile_calls) == 1
    _, request = client.reconcile_calls[0]
    assert {result.repo_id for result in request.results} == {"api", "web"}
    assert {result.result_type for result in request.results} == {"worktree_report"}
    assert len(client.sync_calls) == 1
    assert {path.parent.parent.name for path in client.unreadable_freeze_roots} == {
        "api",
        "web",
    }
    assert [request.result.result_type for _, request in client.reported] == [
        "worktree_report",
        "worktree_report",
    ]
