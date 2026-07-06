"""Edge-Push-Gate ``sync_push`` executor tests (AG3-147 AC6/AC8/AC10).

The gate-decision negative paths (offline, ex-owner, WIP ref, missing service
identity) are git-FREE: the gate refuses BEFORE any push, so they run without a
real repo (a fake online-ownership client + a scripted service-identity source
-- the sanctioned isolated-unit-test seams, not a mock of core logic). The
happy-path push runs a REAL git push to a REAL local bare remote (``requires_git``).
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.code_backend.provider_port import (
    StoryRefWriteCredentialClass,
    StoryRefWriteCredentialResult,
)
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
    EdgeCommandView,
    PushStatusReport,
    SyncPushCommandPayload,
)
from agentkit.harness_client.projectedge.client import PushOwnershipProbe
from agentkit.harness_client.projectedge.command_executor import (
    SyncPushContext,
    execute_command,
    execute_sync_push,
)

if TYPE_CHECKING:
    from pathlib import Path

_STORY_ID = "AG3-700"
_BRANCH = "story/AG3-700"


@dataclass(frozen=True)
class _FakeOwnershipClient:
    """A fake edge client whose only job is the online-ownership probe."""

    probe: PushOwnershipProbe
    calls: list[tuple[str, str, str, str]]

    def confirm_push_ownership(
        self, *, run_id: str, project_key: str, story_id: str, session_id: str
    ) -> PushOwnershipProbe:
        self.calls.append((run_id, project_key, story_id, session_id))
        return self.probe


@dataclass(frozen=True)
class _ScriptedServiceIdentity:
    """A scripted ``ServiceIdentitySource`` (never touches a real credential)."""

    result: StoryRefWriteCredentialResult

    def is_available(self) -> bool:
        return self.result.resolved

    def resolve_write_credential(self) -> StoryRefWriteCredentialResult:
        return self.result


_SERVICE_IDENTITY_OK = StoryRefWriteCredentialResult(
    resolved=True,
    credential_class=StoryRefWriteCredentialClass.SERVICE_IDENTITY,
    credential_ref="env:AGENTKIT_GITHUB_SERVICE_TOKEN",
    detail="scripted service identity",
)
_SERVICE_IDENTITY_ABSENT = StoryRefWriteCredentialResult(
    resolved=False, credential_class=None, credential_ref=None, detail="none configured",
)
_PERSONAL_TOKEN = StoryRefWriteCredentialResult(
    resolved=True,
    credential_class=StoryRefWriteCredentialClass.PERSONAL_DEVELOPER_TOKEN,
    credential_ref="env:GH_TOKEN",
    detail="personal developer token (must never write story/*)",
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


def _payload(branch: str = _BRANCH) -> SyncPushCommandPayload:
    return SyncPushCommandPayload(
        story_id=_STORY_ID,
        project_key="test-project",
        run_id="run-1",
        repo_id="api",
        branch=branch,
    )


def _context(
    probe: PushOwnershipProbe,
    *,
    identity: StoryRefWriteCredentialResult = _SERVICE_IDENTITY_OK,
) -> SyncPushContext:
    return SyncPushContext(
        client=_FakeOwnershipClient(probe=probe, calls=[]),  # type: ignore[arg-type]
        session_id="sess-A",
        service_identity_source=_ScriptedServiceIdentity(result=identity),
    )


# ---------------------------------------------------------------------------
# AC6: online-pflichtig -- offline => no push, visible backlog (git-free)
# ---------------------------------------------------------------------------


def test_offline_server_yields_backlog_without_pushing(tmp_path: Path) -> None:
    """AC6 offline negative test: an unreachable server -> no push, backlog."""
    context = _context(
        PushOwnershipProbe(server_reachable=False, owner_confirmed=False, detail="offline")
    )
    result = execute_sync_push(
        _payload(),
        project_config=_project_config(tmp_path, ["api"]),
        project_root=tmp_path,
        context=context,
    )
    assert isinstance(result, PushStatusReport)
    assert result.push_outcome == "behind_remote"
    assert result.head_sha is None  # no git ran -- the gate refused before any push


def test_stale_active_bundle_grants_no_push(tmp_path: Path) -> None:
    """AC6: the gate takes NO ACTIVE-bundle input -- only the fresh online check
    can confirm. A confirmed=False probe (the FK-56 §56.9a re-sync fallback does
    NOT apply to the push path) blocks the push."""
    context = _context(
        PushOwnershipProbe(server_reachable=True, owner_confirmed=False, detail="ex-owner")
    )
    result = execute_sync_push(
        _payload(),
        project_config=_project_config(tmp_path, ["api"]),
        project_root=tmp_path,
        context=context,
    )
    assert result.push_outcome == "behind_remote"
    assert result.head_sha is None


# ---------------------------------------------------------------------------
# AC10: only story/{id} is a legal push target (no WIP-ref path)
# ---------------------------------------------------------------------------


def test_non_official_ref_is_refused_even_when_owner_confirmed(tmp_path: Path) -> None:
    """AC10: a WIP ref never pushes, even with confirmed ownership."""
    context = _context(
        PushOwnershipProbe(server_reachable=True, owner_confirmed=True, detail="owner")
    )
    result = execute_sync_push(
        _payload(branch="wip/scratch"),
        project_config=_project_config(tmp_path, ["api"]),
        project_root=tmp_path,
        context=context,
    )
    assert result.push_outcome == "behind_remote"
    assert result.head_sha is None


# ---------------------------------------------------------------------------
# AC8: story/* written ONLY via the service identity, never the personal token
# ---------------------------------------------------------------------------


def test_missing_service_identity_blocks_push(tmp_path: Path) -> None:
    """AC8: no backend-managed service identity -> no push (fail-closed)."""
    context = _context(
        PushOwnershipProbe(server_reachable=True, owner_confirmed=True, detail="owner"),
        identity=_SERVICE_IDENTITY_ABSENT,
    )
    result = execute_sync_push(
        _payload(),
        project_config=_project_config(tmp_path, ["api"]),
        project_root=tmp_path,
        context=context,
    )
    assert result.push_outcome == "behind_remote"
    assert result.head_sha is None


def test_personal_developer_token_is_never_used_for_story_ref(tmp_path: Path) -> None:
    """AC8 negative: a resolved PERSONAL token is refused for a story/* write."""
    context = _context(
        PushOwnershipProbe(server_reachable=True, owner_confirmed=True, detail="owner"),
        identity=_PERSONAL_TOKEN,
    )
    result = execute_sync_push(
        _payload(),
        project_config=_project_config(tmp_path, ["api"]),
        project_root=tmp_path,
        context=context,
    )
    assert result.push_outcome == "behind_remote"
    assert result.head_sha is None


# ---------------------------------------------------------------------------
# execute_command dispatch: sync_push needs the context (fail-closed otherwise)
# ---------------------------------------------------------------------------


def test_sync_push_without_context_is_fail_closed(tmp_path: Path) -> None:
    """A sync_push dispatched without the online-ownership context is a
    deterministic fail-closed error, never a silent skip."""
    from datetime import UTC, datetime

    command = EdgeCommandView(
        command_id="cmd-1",
        command_kind="sync_push",
        payload=_payload().model_dump(mode="json"),
        status="delivered",
        created_at=datetime(2026, 7, 6, tzinfo=UTC),
    )
    result = execute_command(
        command, project_config=_project_config(tmp_path, ["api"]), project_root=tmp_path
    )
    assert result.result_type == "command_error"
    assert result.error_code == "sync_push_context_missing"


# ---------------------------------------------------------------------------
# AC6 happy path: gate open + service identity => REAL push to a local remote
# ---------------------------------------------------------------------------


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True)


@pytest.mark.requires_git
def test_gate_open_pushes_official_ref_to_remote(tmp_path: Path) -> None:
    """The gate opens + service identity resolves => the official story ref is
    pushed to the real remote and reported as ``pushed`` with the head SHA."""
    remote = tmp_path / "remote.git"
    remote.mkdir()
    subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
    repo = tmp_path / "api"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "T")
    _git(repo, "config", "commit.gpgsign", "false")
    (repo / "README.md").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", f"seed ({_STORY_ID})")
    _git(repo, "remote", "add", "origin", str(remote))
    _git(repo, "worktree", "add", str(repo / "worktrees" / _STORY_ID), "-b", _BRANCH, "main")

    context = _context(
        PushOwnershipProbe(server_reachable=True, owner_confirmed=True, detail="owner")
    )
    result = execute_sync_push(
        _payload(),
        project_config=_project_config(tmp_path, ["api"]),
        project_root=tmp_path,
        context=context,
    )

    assert result.push_outcome == "pushed"
    assert result.head_sha is not None and len(result.head_sha) == 40
    # The official ref landed on the remote at the reported head SHA.
    remote_ref = subprocess.run(
        ["git", "-C", str(remote), "rev-parse", f"refs/heads/{_BRANCH}"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    assert remote_ref == result.head_sha
