"""Two-stage push-barrier evidence port (FK-10 §10.2.4b, FK-91 §91.1b, AG3-147).

Blood-type R: maps the two evidence sources the hard push barriers need onto the
pure :mod:`agentkit.backend.control_plane.push_sync` A-core primitives -- it owns
NO decision (the A-core :func:`evaluate_push_barrier` decides) and NO provider
mechanic (the ``CodeBackendPort`` ref-read is provider-neutral, AG3-146):

* the EDGE report per participating repo -- the persisted push-freshness record
  (In-Scope #3): ``edge_report_present`` / ``edge_reported_pushed`` (a
  ``behind_remote`` backlog is NOT a push) / ``edge_reported_head_sha``;
* the SERVER ref-read per participating repo -- ``CodeBackendPort.ref_read`` on
  the official ``story/{id}`` branch (``git ls-remote``, no worktree).

The Edge report ALONE is never sufficient (FK-91 §91.1b): a repo counts as
verified-pushed only when BOTH stages agree on the same head SHA (the A-core
enforces that). The provider-specific ``CodeBackendPort`` construction (GitHub
owner/repo coordinate binding) is INJECTED by the composition root, so this
module stays provider-neutral (PO Directive III): it depends only on the port.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from agentkit.backend.config.loader import load_project_config
from agentkit.backend.control_plane.push_sync import (
    RepoPushVerificationInput,
    official_story_ref,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from agentkit.backend.code_backend.provider_port import CodeBackendPort
    from agentkit.backend.config.models import RepositoryConfig
    from agentkit.backend.control_plane.push_sync import PushFreshnessRecord
    from agentkit.backend.control_plane.workspace_locator import StoryWorkspaceLocator

__all__ = [
    "PushBarrierEvidencePort",
    "StateBackedPushBarrierEvidence",
]


@runtime_checkable
class PushBarrierEvidencePort(Protocol):
    """Collect the two-stage barrier evidence per participating repo (AG3-147)."""

    def collect_repo_inputs(
        self,
        *,
        project_key: str,
        story_id: str,
        run_id: str,
        required_sync_point_id: str | None = None,
    ) -> tuple[RepoPushVerificationInput, ...]:
        """Return one two-stage :class:`RepoPushVerificationInput` per repo.

        Fail-closed: a repo with no Edge report and/or an unresolved server ref
        yields an input the A-core blocks. Productive hard barriers pass their
        freshly commissioned sync-point id; a freshness row from another
        boundary is stale and fails closed. An empty tuple (no participating
        repos resolvable) makes the barrier fail closed (never an optimistic
        pass).
        """
        ...


@dataclass(frozen=True)
class StateBackedPushBarrierEvidence:
    """Productive :class:`PushBarrierEvidencePort` over the store + code backend.

    Attributes:
        workspace_locator: Resolves the backend-local ``project_root`` from
            canonical level-1 state (``project_registry``), never a dev-supplied
            path (AG3-123).
        code_backend_factory: Provider-specific factory binding a repo coordinate
            onto a ``CodeBackendPort`` (injected by the composition root so this
            module stays provider-neutral).
    """

    workspace_locator: StoryWorkspaceLocator
    code_backend_factory: Callable[[RepositoryConfig, Path], CodeBackendPort]

    def collect_repo_inputs(
        self,
        *,
        project_key: str,
        story_id: str,
        run_id: str,
        required_sync_point_id: str | None = None,
    ) -> tuple[RepoPushVerificationInput, ...]:
        """Assemble the per-repo two-stage barrier inputs (Edge + server)."""
        workspace = self.workspace_locator.resolve(project_key, story_id, run_id)
        project_config = load_project_config(workspace.project_root)
        server_ref = f"refs/heads/{official_story_ref(story_id)}"
        inputs: list[RepoPushVerificationInput] = []
        for repo in project_config.repositories:
            freshness = self._load_freshness(project_key, story_id, run_id, repo.name)
            server = self.code_backend_factory(
                repo, workspace.project_root
            ).ref_read(server_ref)
            inputs.append(
                RepoPushVerificationInput(
                    repo_id=repo.name,
                    edge_report_present=freshness is not None,
                    # A ``behind_remote`` backlog is explicitly NOT a push.
                    edge_reported_pushed=freshness is not None and not freshness.backlog,
                    edge_reported_head_sha=(
                        freshness.last_reported_head_sha if freshness else None
                    ),
                    server_ref_resolved=server.resolved,
                    server_head_sha=server.head_sha,
                    edge_report_sync_point_id=(
                        freshness.last_sync_point_id if freshness else None
                    ),
                    required_sync_point_id=required_sync_point_id,
                )
            )
        return tuple(inputs)

    @staticmethod
    def _load_freshness(
        project_key: str, story_id: str, run_id: str, repo_id: str
    ) -> PushFreshnessRecord | None:
        """Read the persisted push-freshness record (Postgres-only, K5)."""
        from agentkit.backend.state_backend.store import (
            load_push_freshness_record_global,
        )

        return load_push_freshness_record_global(
            project_key, story_id, run_id, repo_id
        )
