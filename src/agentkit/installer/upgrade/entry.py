"""Productive upgrade boundary control — wires the real backend + governance.

The CLI boundary control for ``upgrade-project`` (FK-51 §51.2 — the installer is
transport-agnostic; the CLI is a boundary control of the calling BC). It lives in
the ``installer_upgrade`` layer (the highest intra-BC layer), so it may compose
the lower installer layers and the state-backend adapters; it wires the
productive :class:`ProjectRegistrationRepository` and governance top surface and
delegates to :func:`run_upgrade`, which builds and runs the SHARED AG3-088
checkpoint engine over the upgrade flow (story §6 — upgrade is an engine-driven
flow, not a second installer).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.installer.checkpoint_engine.execution_mode import ExecutionMode
from agentkit.installer.upgrade.upgrade_flow import run_upgrade

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.installer.upgrade.cleanup import CleanupPlan
    from agentkit.installer.upgrade.upgrade_flow import UpgradeResult


def run_checkpoint_upgrade(
    project_root: Path,
    *,
    project_key: str,
    github_owner: str,
    github_repo: str,
    target_config_version: str,
    mode: ExecutionMode = ExecutionMode.REGISTER,
    bundle_version_changed: bool = False,
    explicit_binding_switch: bool = False,
    cleanup_plan: CleanupPlan | None = None,
) -> UpgradeResult:
    """Run the FK-51 upgrade flow through the engine for a productive project.

    Wires the productive registration repository and (in mutating mode) the
    governance top surface, then delegates to the engine-driven
    :func:`run_upgrade`.

    Args:
        project_root: The target-project root.
        project_key: The registered project key.
        github_owner: GitHub owner (governance project scoping).
        github_repo: GitHub repository name.
        target_config_version: Desired ``pipeline.config_version`` (AG3-070 SSOT).
        mode: The execution mode (register / dry_run / verify).
        bundle_version_changed: §51.3 bundle-version criterion.
        explicit_binding_switch: §51.3.3 explicit binding switch (no auto pull).
        cleanup_plan: Optional §51.7 cleanup plan.

    Returns:
        The :class:`UpgradeResult` of the engine-driven upgrade run.

    Raises:
        ProjectError: When the project root does not exist (fail-closed).
    """
    del github_owner, github_repo  # part of the caller signature; not consumed by the upgrade flow (S1172)
    from agentkit.exceptions import ProjectError

    if not project_root.is_dir():
        raise ProjectError(
            f"Project root does not exist: {project_root}",
            detail={"project_root": str(project_root)},
        )

    from agentkit.governance.runner import Governance
    from agentkit.state_backend.store.governance_hook_repository import (
        StateBackendHookRegistrationRepository,
    )
    from agentkit.state_backend.store.lock_record_repository import LockRecordRepository
    from agentkit.state_backend.store.project_registration_repository import (
        StateBackendProjectRegistrationRepository,
    )
    from agentkit.state_backend.store.worktree_repository import (
        StateBackendWorktreeRepository,
    )

    registration_repo = StateBackendProjectRegistrationRepository(project_root)
    governance: Governance | None = None
    if mode.mutations_allowed:
        # Governance is only needed for the mutating §51.6 hook registration.
        governance = Governance(
            hook_repo=StateBackendHookRegistrationRepository(project_root),
            lock_repo=LockRecordRepository(project_root),
            project_key=project_key,
            project_root=project_root,
            worktree_repo=StateBackendWorktreeRepository(project_root),
        )
    return run_upgrade(
        project_root,
        project_key=project_key,
        target_config_version=target_config_version,
        registration_repo=registration_repo,
        bundle_version_changed=bundle_version_changed,
        explicit_binding_switch=explicit_binding_switch,
        mode=mode,
        governance=governance,
        cleanup_plan=cleanup_plan,
    )


__all__ = ["run_checkpoint_upgrade"]
