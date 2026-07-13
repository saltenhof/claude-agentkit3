"""Edge-side Edge-Command-Queue executor (FK-91 §91.1b, FK-10 §10.2.4a, AG3-145).

Blood-type T (dev-local git subprocess) with a thin R reporting layer: the
physical worktree operations FK-10 §10.2.4a moves off the backend run HERE, on
the Project Edge. The command loop fetches this session's open commands
(:meth:`ProjectEdgeClient.fetch_open_commands`), executes each one dev-locally
against the REAL git repo, and reports the typed result with the edge's OWN
``op_id`` (:meth:`ProjectEdgeClient.report_command_result`).

``provision_worktree`` / ``teardown_worktree`` / ``preflight_probe`` (AG3-145),
``sync_push`` (AG3-147), ``takeover_reconcile`` (AG3-151), and
``reset_worktree`` (AG3-154) and ``merge_local`` (AG3-152) are executed here.
The edge derives the physical repo path from its LOCAL
project config, never from the backend (FK-10 §10.2.4a).
"""

from __future__ import annotations

import json
import os
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable

from agentkit.backend.code_backend.provider_port import (
    StoryRefWriteCredentialClass,
    StoryRefWriteCredentialResult,
)
from agentkit.backend.control_plane.edge_commands import is_executable_command_kind
from agentkit.backend.control_plane.models import (
    CommandErrorResult,
    EdgeCommandResultRequest,
    MergeLocalCommandPayload,
    PreflightProbeCommandPayload,
    PreflightProbeReport,
    ProjectEdgeSyncRequest,
    ProvisionWorktreeCommandPayload,
    PushStatusReport,
    ResetWorktreeCommandPayload,
    SyncPushCommandPayload,
    TakeoverReconcileCommandPayload,
    TakeoverReconcileWorktreeRequest,
    TeardownWorktreeCommandPayload,
    WorktreeReport,
)
from agentkit.backend.control_plane.push_sync import (
    decide_push_gate,
    official_story_ref,
)
from agentkit.backend.utils.io import atomic_write_text
from agentkit.harness_client.projectedge.merge_local import execute_merge_local
from agentkit.harness_client.projectedge.reconcile import (
    TakeoverReconcileExecution,
    execute_takeover_reconcile,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from agentkit.backend.config.models import ProjectConfig
    from agentkit.backend.control_plane.models import (
        EdgeCommandMutationResult,
        EdgeCommandResultPayload,
        EdgeCommandView,
    )
    from agentkit.harness_client.projectedge.client import ProjectEdgeClient

_STORY_MARKER_FILENAME = ".agentkit-story.json"
_EDGE_GIT_TIMEOUT_S = 30
_EDGE_GIT_PUSH_TIMEOUT_S = 120

#: The backend-managed env-var HANDLE carrying the story/* write credential
#: (FK-15 §15.5.1). Deployment contract: it MUST match the backend adapter's
#: ``DEFAULT_SERVICE_IDENTITY_ENV_VAR``. The edge resolves the credential through
#: a provider-neutral seam (below) rather than importing the GitHub Integrations
#: boundary (architecture-conformance AC010: ProjectEdge must not import Integrations).
_DEFAULT_EDGE_SERVICE_TOKEN_ENV_VAR = "AGENTKIT_GITHUB_SERVICE_TOKEN"


@runtime_checkable
class EdgeServiceCredentialSource(Protocol):
    """The edge-side ``story/*`` write-credential source (FK-15 §15.5.1, AG3-147).

    Provider-neutral: it returns the backend-managed service-identity credential
    (never the personal developer token). The concrete provider mechanic (GitHub
    ruleset admin etc.) stays in the backend adapter; the edge only needs "resolve
    the backend-managed token handle", so it depends on this narrow seam, not on
    the Integrations boundary.
    """

    def resolve_write_credential(self) -> StoryRefWriteCredentialResult:
        """Resolve the service-identity credential (never the personal token)."""
        ...


@dataclass(frozen=True)
class EnvVarEdgeServiceCredentialSource:
    """Resolve the service identity from a backend-managed env-var handle (fail-closed)."""

    env_var: str = _DEFAULT_EDGE_SERVICE_TOKEN_ENV_VAR

    def resolve_write_credential(self) -> StoryRefWriteCredentialResult:
        """Resolve ``SERVICE_IDENTITY`` when the env token is set, else fail-closed.

        Returns an opaque ``env:{name}`` handle (never the secret VALUE). It NEVER
        returns the personal developer token class -- there is no fallback path to
        the personal token for a ``story/*`` write (AC8).
        """
        if not os.environ.get(self.env_var, "").strip():
            return StoryRefWriteCredentialResult(
                resolved=False,
                credential_class=None,
                credential_ref=None,
                detail=(
                    f"no backend-managed service identity configured (env "
                    f"{self.env_var!r} unset); the personal developer token is "
                    "never substituted for a story/* write (fail-closed)"
                ),
            )
        return StoryRefWriteCredentialResult(
            resolved=True,
            credential_class=StoryRefWriteCredentialClass.SERVICE_IDENTITY,
            credential_ref=f"env:{self.env_var}",
            detail="resolved the backend-managed service identity",
        )


class EdgeGitError(RuntimeError):
    """A dev-local git subprocess failed on the edge (non-zero exit)."""


def _run_git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run one ``git -C <repo_root> <args>`` subprocess and return the result."""
    try:
        return subprocess.run(
            ["git", "-C", str(repo_root), *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=_EDGE_GIT_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired as exc:
        raise EdgeGitError(
            f"dev-local git {' '.join(args)} timed out after "
            f"{_EDGE_GIT_TIMEOUT_S}s"
        ) from exc


def _require_git(result: subprocess.CompletedProcess[str], action: str) -> None:
    """Raise :class:`EdgeGitError` when a git subprocess exited non-zero."""
    if result.returncode != 0:
        raise EdgeGitError(
            f"dev-local git {action} failed (exit {result.returncode}): "
            f"{result.stderr.strip()}"
        )


def _resolve_repo_root(
    project_config: ProjectConfig, project_root: Path, repo_id: str
) -> Path:
    """Resolve a repo's dev-local root from the LOCAL project config (FK-10 §10.2.4a).

    The edge -- never the backend -- knows the physical path. A relative
    configured path is resolved against the edge's project root.

    Raises:
        EdgeGitError: When ``repo_id`` is not a configured repository.
    """
    for repo in project_config.repositories:
        if repo.name == repo_id:
            return repo.path if repo.path.is_absolute() else project_root / repo.path
    raise EdgeGitError(
        f"repo {repo_id!r} is not configured in the local project config "
        f"(configured: {sorted(repo.name for repo in project_config.repositories)})"
    )


def _write_story_marker(
    worktree_path: Path, *, story_id: str, project_key: str, run_id: str
) -> None:
    """Materialize the FK-36 §36.6.3 story marker dev-locally (SOLL-138/139)."""
    payload = {
        "story_id": story_id,
        "project_key": project_key,
        "run_id": run_id,
        "created_at": datetime.now(tz=UTC).isoformat(),
    }
    atomic_write_text(
        worktree_path / _STORY_MARKER_FILENAME,
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        newline="",
    )


def _read_story_marker(worktree_path: Path) -> dict[str, object] | None:
    """Read the story marker in a worktree, or ``None`` when absent/unreadable."""
    marker_path = worktree_path / _STORY_MARKER_FILENAME
    if not marker_path.is_file():
        return None
    try:
        payload = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def execute_provision_worktree(
    payload: ProvisionWorktreeCommandPayload,
    *,
    project_config: ProjectConfig,
    project_root: Path,
) -> WorktreeReport:
    """Provision the story worktree dev-locally (FK-12 §12.5.1) + materialize the marker.

    Reports the physical ``worktree_root`` (the SINGLE truth for the session's
    ``worktree_roots``, FK-56 §56.8) plus the branch head SHA and marker
    presence. The backend derives NO path -- it consumes THIS report.
    """
    repo_root = _resolve_repo_root(project_config, project_root, payload.repo_id)
    worktree_path = repo_root / "worktrees" / payload.story_id
    if payload.reuse_existing_branch and worktree_path.is_dir():
        resolved = worktree_path.resolve(strict=True)
        _require_registered_linked_worktree(repo_root, resolved)
        return WorktreeReport(
            repo_id=payload.repo_id,
            outcome="no_op",
            worktree_root=str(resolved),
            branch=payload.branch,
            head_sha=_current_head_sha(resolved),
            marker_present=_read_story_marker(resolved) is not None,
        )
    if payload.reuse_existing_branch:
        remote_branch = f"origin/{payload.branch}"
        _require_git(
            _run_git(repo_root, "fetch", "origin", payload.branch),
            "fetch pushed story branch for reprovision",
        )
        branch_present, _head = _probe_branch(repo_root, payload.branch)
        if not branch_present:
            _require_git(
                _run_git(repo_root, "branch", payload.branch, remote_branch),
                "create local story branch from pushed ref",
            )
    add_args = (
        ("worktree", "add", str(worktree_path), payload.branch)
        if payload.reuse_existing_branch
        else (
            "worktree",
            "add",
            str(worktree_path),
            "-b",
            payload.branch,
            payload.base_ref,
        )
    )
    _require_git(
        _run_git(repo_root, *add_args),
        "worktree add",
    )
    _write_story_marker(
        worktree_path,
        story_id=payload.story_id,
        project_key=payload.project_key,
        run_id=payload.run_id,
    )
    head = _run_git(worktree_path, "rev-parse", "HEAD")
    _require_git(head, "rev-parse HEAD")
    return WorktreeReport(
        repo_id=payload.repo_id,
        outcome="provisioned",
        worktree_root=str(worktree_path),
        branch=payload.branch,
        head_sha=head.stdout.strip(),
        marker_present=True,
    )


def execute_teardown_worktree(
    payload: TeardownWorktreeCommandPayload,
    *,
    project_config: ProjectConfig,
    project_root: Path,
) -> WorktreeReport:
    """Tear down the story worktree dev-locally (FK-12 §12.5.3), idempotent (FK-10 §10.5.3).

    A double teardown is a reported ``no_op`` (the worktree is already gone),
    NEVER an error. The branch delete is best-effort (a missing branch is not a
    failure).
    """
    repo_root = _resolve_repo_root(project_config, project_root, payload.repo_id)
    worktree_path = repo_root / "worktrees" / payload.story_id
    existed = worktree_path.exists()
    if existed:
        _require_git(
            _run_git(repo_root, "worktree", "remove", "--force", str(worktree_path)),
            "worktree remove",
        )
    else:
        # Prune dangling metadata for a worktree removed outside git (idempotent).
        _run_git(repo_root, "worktree", "prune")
    # Best-effort branch delete: a missing branch is a no-op, never a failure.
    _run_git(repo_root, "branch", "-D", payload.branch)
    return WorktreeReport(
        repo_id=payload.repo_id,
        outcome="torn_down" if existed else "no_op",
        worktree_root=str(worktree_path),
        branch=payload.branch,
    )


def execute_reset_worktree(
    payload: ResetWorktreeCommandPayload,
    *,
    project_config: ProjectConfig,
    project_root: Path,
) -> WorktreeReport:
    """Discard uncommitted work by resetting the existing worktree to ``HEAD``."""
    repo_root = _resolve_repo_root(project_config, project_root, payload.repo_id)
    worktrees_root = repo_root / "worktrees"
    worktree_path = worktrees_root / payload.story_id
    if worktrees_root.is_symlink() or worktree_path.is_symlink():
        raise EdgeGitError("reset_worktree refuses to follow a symlinked worktree path")
    if not worktree_path.is_dir():
        raise EdgeGitError("reset_worktree requires the recovered worktree to exist")

    try:
        resolved_worktree = worktree_path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise EdgeGitError(
            "reset_worktree could not resolve the recovered worktree path"
        ) from exc

    _require_registered_linked_worktree(repo_root, resolved_worktree)
    _require_git(
        _run_git(resolved_worktree, "reset", "--hard", "HEAD"),
        "reset --hard HEAD",
    )
    # A local single-operator edge is the trust boundary: Windows cannot pin a
    # directory handle across git processes. Revalidate immediately before the
    # second destructive operation and keep using the same once-resolved path.
    _require_registered_linked_worktree(repo_root, resolved_worktree)
    _require_git(_run_git(resolved_worktree, "clean", "-fd"), "clean -fd")
    _write_story_marker(
        resolved_worktree,
        story_id=payload.story_id,
        project_key=payload.project_key,
        run_id=payload.run_id,
    )
    head_sha = _current_head_sha(resolved_worktree)
    return WorktreeReport(
        repo_id=payload.repo_id,
        outcome="reset",
        worktree_root=str(worktree_path),
        head_sha=head_sha,
        marker_present=True,
    )


def _require_registered_linked_worktree(repo_root: Path, worktree_path: Path) -> None:
    """Fail closed unless ``worktree_path`` is this repo's registered linked root."""
    main_toplevel_result = _run_git(repo_root, "rev-parse", "--show-toplevel")
    _require_git(main_toplevel_result, "rev-parse --show-toplevel for primary worktree")
    main_toplevel = _canonical_git_path(main_toplevel_result.stdout.strip())
    if worktree_path == main_toplevel:
        raise EdgeGitError("reset_worktree refuses to reset the primary worktree")

    worktree_toplevel_result = _run_git(worktree_path, "rev-parse", "--show-toplevel")
    _require_git(worktree_toplevel_result, "rev-parse --show-toplevel for recovered worktree")
    worktree_toplevel = _canonical_git_path(worktree_toplevel_result.stdout.strip())
    if worktree_toplevel != worktree_path:
        raise EdgeGitError(
            "reset_worktree target is not its own git worktree root "
            f"(target={worktree_path}, toplevel={worktree_toplevel})"
        )

    listing = _run_git(repo_root, "worktree", "list", "--porcelain", "-z")
    _require_git(listing, "worktree list --porcelain -z")
    registered_paths = {
        _canonical_git_path(field.removeprefix("worktree "), strict=False)
        for field in listing.stdout.split("\0")
        if field.startswith("worktree ")
    }
    if worktree_path not in registered_paths:
        raise EdgeGitError(
            "reset_worktree target is not a registered worktree of the configured repo"
        )

    repo_common_dir = _git_common_dir(repo_root)
    worktree_common_dir = _git_common_dir(worktree_path)
    if worktree_common_dir != repo_common_dir:
        raise EdgeGitError(
            "reset_worktree target is not linked to the configured repo's git metadata"
        )


def _git_common_dir(worktree_path: Path) -> Path:
    """Return one worktree's canonical common git metadata directory."""
    result = _run_git(worktree_path, "rev-parse", "--git-common-dir")
    _require_git(result, "rev-parse --git-common-dir")
    return _canonical_git_path(result.stdout.strip(), relative_to=worktree_path)


def _canonical_git_path(
    raw_path: str,
    *,
    relative_to: Path | None = None,
    strict: bool = True,
) -> Path:
    """Canonicalize a git-reported path or raise the edge's fail-closed error."""
    from pathlib import Path

    path = Path(raw_path)
    if relative_to is not None and not path.is_absolute():
        path = relative_to / path
    try:
        return path.resolve(strict=strict)
    except (OSError, RuntimeError) as exc:
        raise EdgeGitError(
            f"reset_worktree could not canonicalize git-reported path {raw_path!r}"
        ) from exc


def execute_preflight_probe(
    payload: PreflightProbeCommandPayload,
    *,
    project_config: ProjectConfig,
    project_root: Path,
) -> PreflightProbeReport:
    """Probe one repo's branch + worktree state (FK-22 §22.3.1). Pure collection.

    Reports branch class (present + head SHA), local worktree presence, path
    and marker content. Makes NO decision -- the backend's preflight checks 7/8
    decide on this evidence (AG3-145 substep C).
    """
    repo_root = _resolve_repo_root(project_config, project_root, payload.repo_id)
    branch_present, head_sha = _probe_branch(repo_root, payload.branch)
    worktree_path = repo_root / "worktrees" / payload.story_id
    worktree_present = worktree_path.exists()
    marker = _read_story_marker(worktree_path) if worktree_present else None
    marker_story_id = _optional_str(marker, "story_id")
    marker_run_id = _optional_str(marker, "run_id")
    return PreflightProbeReport(
        repo_id=payload.repo_id,
        branch_present=branch_present,
        head_sha=head_sha,
        worktree_present=worktree_present,
        worktree_path=str(worktree_path) if worktree_present else None,
        marker_present=marker is not None,
        marker_story_id=marker_story_id,
        marker_run_id=marker_run_id,
    )


def _probe_branch(repo_root: Path, branch: str) -> tuple[bool, str | None]:
    """Return ``(branch_present, head_sha)`` for a local branch (fail-closed on error).

    A ``show-ref`` exit of 0 = present, 1 = absent; any other exit is a genuine
    git failure (fail-closed :class:`EdgeGitError`, never silently "absent").
    """
    show_ref = _run_git(
        repo_root, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"
    )
    if show_ref.returncode not in (0, 1):
        _require_git(show_ref, "show-ref")
    if show_ref.returncode != 0:
        return False, None
    head = _run_git(repo_root, "rev-parse", f"refs/heads/{branch}")
    _require_git(head, "rev-parse branch")
    return True, head.stdout.strip()


def _optional_str(marker: dict[str, object] | None, key: str) -> str | None:
    if marker is None:
        return None
    value = marker.get(key)
    return value if isinstance(value, str) else None


@dataclass(frozen=True)
class SyncPushContext:
    """Edge-side context a ``sync_push`` execution needs (AG3-147, FK-15 §15.5.4).

    ``sync_push`` -- unlike the pure-local provision/teardown/probe executors --
    needs the control-plane ``client`` (for the bounded online-ownership check)
    and the session identity, plus the backend-managed service-identity source
    that authorises the ``story/*`` write (never the personal developer token).

    Attributes:
        client: The official Project Edge client for the bounded online check.
        session_id: This edge session's id (the online check confirms it is the
            current run owner).
        service_identity_source: The backend-managed ``story/*`` write-credential
            source (FK-15 §15.5.1). Defaults to the env-var handle; a unit test
            injects a scripted double.
    """

    client: ProjectEdgeClient
    session_id: str
    service_identity_source: EdgeServiceCredentialSource = field(
        default_factory=EnvVarEdgeServiceCredentialSource
    )


def execute_sync_push(
    payload: SyncPushCommandPayload,
    *,
    project_config: ProjectConfig,
    project_root: Path,
    context: SyncPushContext,
) -> PushStatusReport:
    """Execute the official Edge-Push-Gate push of ``story/{id}`` (AG3-147, FK-15 §15.5.4).

    The ONLY sanctioned push mechanic for ``story/*`` (FK-55 §55.9). It runs a
    FRESH bounded online-ownership check and decides the push gate (there is NO
    ACTIVE-bundle re-sync fallback -- a stale bundle grants no push, FK-56
    §56.9a excluded for the push path). Only when the gate opens AND the
    backend-managed service identity resolves does it push EXACTLY the official
    ``story/{story_id}`` ref (no WIP-ref path, AC10) via the service credential
    (never the personal developer token, AC8). Every refusal / failure is a
    visible push BACKLOG (``behind_remote``), never a raise: local work
    continues while the completion barrier stays fail-closed until a verified
    push (FK-10 §10.6.1, SOLL-146).
    """
    probe = context.client.confirm_push_ownership(
        run_id=payload.run_id,
        project_key=payload.project_key,
        story_id=payload.story_id,
        session_id=context.session_id,
    )
    gate = decide_push_gate(
        server_reachable=probe.server_reachable,
        server_confirms_ownership=probe.owner_confirmed,
        target_ref=payload.branch,
        story_id=payload.story_id,
    )
    if not gate.allowed:
        # Offline (OFFLINE_NO_SERVER_CONFIRMATION), ex-owner
        # (OWNERSHIP_NOT_CONFIRMED) or a WIP ref (NON_OFFICIAL_REF): no push ran.
        return _sync_push_report(payload, "behind_remote", head_sha=None)

    credential = context.service_identity_source.resolve_write_credential()
    if (
        not credential.resolved
        or credential.credential_class is not StoryRefWriteCredentialClass.SERVICE_IDENTITY
    ):
        # AC8 fail-closed: no backend-managed service identity -> NO push. The
        # personal developer token is NEVER substituted for a story/* write.
        return _sync_push_report(payload, "behind_remote", head_sha=None)

    try:
        repo_root = _resolve_repo_root(project_config, project_root, payload.repo_id)
        worktree_path = repo_root / "worktrees" / payload.story_id
        head_sha = _current_head_sha(worktree_path)
        tree = _run_git(worktree_path, "rev-parse", "HEAD^{tree}")
        _require_git(tree, "rev-parse HEAD^{tree}")
        tree_hash = tree.stdout.strip()
        status = _run_git(worktree_path, "status", "--porcelain")
        _require_git(status, "status --porcelain")
        fetch_main = _run_git(worktree_path, "fetch", "origin", "main")
        base_ancestor = fetch_main.returncode == 0 and (
            _run_git(
                worktree_path,
                "merge-base",
                "--is-ancestor",
                "origin/main",
                head_sha,
            ).returncode
            == 0
        )
        outcome = _push_official_ref(
            worktree_path,
            story_id=payload.story_id,
            head_sha=head_sha,
            credential_ref=credential.credential_ref,
        )
        if _current_head_sha(worktree_path) != head_sha:
            return _sync_push_report(payload, "behind_remote", head_sha=head_sha)
    except EdgeGitError:
        return _sync_push_report(payload, "behind_remote", head_sha=None)
    return _sync_push_report(
        payload,
        outcome,
        head_sha=head_sha,
        tree_hash=tree_hash,
        worktree_clean=not status.stdout.strip(),
        base_ancestor=base_ancestor,
    )


def _push_official_ref(
    worktree_path: Path,
    *,
    story_id: str,
    head_sha: str,
    credential_ref: str | None,
) -> Literal["pushed", "behind_remote"]:
    """Push exactly ``head_sha`` to the official ``refs/heads/story/{id}``.

    Returns ``"pushed"`` on a clean push, ``"behind_remote"`` on any push
    rejection / network failure (a visible backlog, NEVER a raise: opportunistic
    pushes must not block local work, SOLL-143/146). The service token stays in
    the subprocess environment and is never returned or logged.
    """
    refspec = f"{head_sha}:refs/heads/{official_story_ref(story_id)}"
    try:
        result = subprocess.run(
            ["git", "-C", str(worktree_path), "push", "origin", refspec],
            capture_output=True,
            text=True,
            check=False,
            env=_push_env(credential_ref),
            timeout=_EDGE_GIT_PUSH_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return "behind_remote"
    return "pushed" if result.returncode == 0 else "behind_remote"


def _current_head_sha(worktree_path: Path) -> str:
    """Return the current worktree HEAD SHA."""

    head = _run_git(worktree_path, "rev-parse", "HEAD")
    _require_git(head, "rev-parse HEAD")
    return head.stdout.strip()


def _sync_push_report(
    payload: SyncPushCommandPayload,
    push_outcome: Literal["pushed", "behind_remote"],
    *,
    head_sha: str | None,
    tree_hash: str | None = None,
    worktree_clean: bool | None = None,
    base_ancestor: bool | None = None,
) -> PushStatusReport:
    """Build the boundary-tagged ``sync_push`` result."""

    return PushStatusReport(
        repo_id=payload.repo_id,
        push_outcome=push_outcome,
        head_sha=head_sha,
        tree_hash=tree_hash,
        worktree_clean=worktree_clean,
        base_ancestor=base_ancestor,
        boundary_type=payload.boundary_type,
        boundary_id=payload.boundary_id,
        boundary_epoch=payload.boundary_epoch,
        ownership_epoch=payload.ownership_epoch,
    )


def _push_env(credential_ref: str | None) -> dict[str, str]:
    """Build the push subprocess env: no terminal prompt + the service token.

    The service credential is an opaque ``env:{NAME}`` handle (FK-15 §15.5.1);
    the token VALUE is read from that env var into ``GH_TOKEN`` for the push and
    never crosses a return/log boundary (ARCH-55: no secret in a wire field).
    """
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    if credential_ref is not None and credential_ref.startswith("env:"):
        token = os.environ.get(credential_ref.removeprefix("env:"), "")
        if token:
            env["GH_TOKEN"] = token
    return env


def execute_command(
    command: EdgeCommandView,
    *,
    project_config: ProjectConfig,
    project_root: Path,
    sync_push_context: SyncPushContext | None = None,
) -> EdgeCommandResultPayload | TakeoverReconcileExecution:
    """Dispatch ONE command to its executor and return the typed result payload.

    A kind outside the edge's executable set yields a deterministic
    :class:`CommandErrorResult` -- NEVER a silent no-op (Scope item 4). A
    ``sync_push`` needs the :class:`SyncPushContext` (client + identity); without
    it the command is a fail-closed ``sync_push_context_missing`` error, never a
    silent skip. An executor failure (bad payload / git error) is also surfaced
    as a :class:`CommandErrorResult` so the loop reports a terminal result.
    """
    from pydantic import ValidationError

    if not is_executable_command_kind(command.command_kind):
        return CommandErrorResult(
            error_code="unsupported_command_kind",
            message=(
                f"command kind {command.command_kind!r} is registered but not "
                "executable by this edge (owned by a neighbour story)"
            ),
        )
    if command.command_kind == "sync_push" and sync_push_context is None:
        return CommandErrorResult(
            error_code="sync_push_context_missing",
            message=(
                "sync_push requires the edge online-ownership client + service "
                "identity context; refusing fail-closed (never a silent skip)"
            ),
        )
    try:
        return _dispatch_executable(
            command,
            project_config=project_config,
            project_root=project_root,
            sync_push_context=sync_push_context,
        )
    except (ValidationError, EdgeGitError) as exc:
        return CommandErrorResult(
            error_code="command_execution_failed",
            message=f"{command.command_kind} failed: {exc}",
        )


def _dispatch_executable(
    command: EdgeCommandView,
    *,
    project_config: ProjectConfig,
    project_root: Path,
    sync_push_context: SyncPushContext | None,
) -> EdgeCommandResultPayload | TakeoverReconcileExecution:
    """Validate the payload and run the matching executor (executable kinds only)."""
    if command.command_kind == "provision_worktree":
        return execute_provision_worktree(
            ProvisionWorktreeCommandPayload.model_validate(command.payload),
            project_config=project_config,
            project_root=project_root,
        )
    if command.command_kind == "teardown_worktree":
        return execute_teardown_worktree(
            TeardownWorktreeCommandPayload.model_validate(command.payload),
            project_config=project_config,
            project_root=project_root,
        )
    if command.command_kind == "reset_worktree":
        return execute_reset_worktree(
            ResetWorktreeCommandPayload.model_validate(command.payload),
            project_config=project_config,
            project_root=project_root,
        )
    if command.command_kind == "sync_push":
        assert sync_push_context is not None  # noqa: S101 -- guarded in execute_command
        return execute_sync_push(
            SyncPushCommandPayload.model_validate(command.payload),
            project_config=project_config,
            project_root=project_root,
            context=sync_push_context,
        )
    if command.command_kind == "takeover_reconcile":
        return execute_takeover_reconcile(
            TakeoverReconcileCommandPayload.model_validate(command.payload),
            project_config=project_config,
            project_root=project_root,
        )
    if command.command_kind == "merge_local":
        return execute_merge_local(
            MergeLocalCommandPayload.model_validate(command.payload),
            project_config=project_config,
            project_root=project_root,
        )
    return execute_preflight_probe(
        PreflightProbeCommandPayload.model_validate(command.payload),
        project_config=project_config,
        project_root=project_root,
    )


def process_open_commands(
    client: ProjectEdgeClient,
    *,
    project_config: ProjectConfig,
    project_root: Path,
    run_id: str,
    project_key: str,
    session_id: str,
    story_id: str,
) -> Sequence[EdgeCommandMutationResult]:
    """Fetch, execute and report this session's open commands (the edge loop).

    Each command's result is reported with the edge's OWN client ``op_id``
    (Rule 5) so an ambiguous POST is reconcilable. The GET ack + the per-command
    result POST are the two wire calls; git runs strictly dev-locally between
    them. Returns the terminal outcomes (completed / replayed / rejected) in
    fetch order.
    """
    response = client.fetch_open_commands(
        run_id=run_id, project_key=project_key, session_id=session_id
    )
    sync_push_context = SyncPushContext(client=client, session_id=session_id)
    executions: list[
        tuple[EdgeCommandView, EdgeCommandResultPayload | TakeoverReconcileExecution]
    ] = []
    for command in response.commands:
        executions.append(
            (
                command,
                execute_command(
                    command,
                    project_config=project_config,
                    project_root=project_root,
                    sync_push_context=sync_push_context,
                ),
            )
        )

    reconcile_executions = [
        execution
        for command, execution in executions
        if command.command_kind == "takeover_reconcile"
        and isinstance(execution, TakeoverReconcileExecution)
    ]
    if any(
        command.command_kind == "takeover_reconcile"
        and not isinstance(execution, TakeoverReconcileExecution)
        for command, execution in executions
    ):
        raise EdgeGitError(
            "takeover reconcile command payload was unreadable; refusing to "
            "terminalize the queue command or bypass the reconcile obligation"
        )
    if reconcile_executions:
        reconcile_roots = [
            _resolve_repo_root(project_config, project_root, execution.result.repo_id)
            / "worktrees"
            / story_id
            for execution in reconcile_executions
        ]
        client.publish_unreadable_freeze_state(worktree_roots=reconcile_roots)
        reconcile_result = client.reconcile_takeover_worktree(
            run_id=run_id,
            request=TakeoverReconcileWorktreeRequest(
                project_key=project_key,
                story_id=story_id,
                session_id=session_id,
                op_id=f"op-{uuid.uuid4().hex}",
                results=[execution.result for execution in reconcile_executions],
                quarantine_details=[
                    execution.quarantine_detail
                    for execution in reconcile_executions
                    if execution.quarantine_detail is not None
                ],
            ),
        )
        reconcile_already_complete = (
            reconcile_result.status == "rejected"
            and reconcile_result.error_code == "takeover_reconcile_not_required"
        )
        if (
            reconcile_result.status not in {"resolved", "failed"}
            and not reconcile_already_complete
        ):
            raise EdgeGitError(
                "takeover reconcile result was not accepted by the official "
                f"route (status={reconcile_result.status!r}); queue commands "
                "remain open for deterministic retry"
            )
        client.sync(
            ProjectEdgeSyncRequest(
                project_key=project_key,
                session_id=session_id,
                op_id=f"op-{uuid.uuid4().hex}",
                freshness_class="mutation",
            )
        )

    outcomes: list[EdgeCommandMutationResult] = []
    for command, execution in executions:
        result_payload = (
            execution.result
            if isinstance(execution, TakeoverReconcileExecution)
            else execution
        )
        request = EdgeCommandResultRequest(
            project_key=project_key,
            story_id=story_id,
            session_id=session_id,
            op_id=f"op-{uuid.uuid4().hex}",
            result=result_payload,
        )
        outcomes.append(
            client.report_command_result(
                command_id=command.command_id, request=request
            )
        )
    return outcomes
