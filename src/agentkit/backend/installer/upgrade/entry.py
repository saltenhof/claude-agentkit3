"""Upgrade boundary control for writer-backed state dependencies.

The CLI boundary control for ``upgrade-project`` (FK-51 §51.2 — the installer is
transport-agnostic; the CLI is a boundary control of the calling BC). It accepts
the authenticated writer-backed registration, skill and governance surfaces and
delegates to :func:`run_upgrade`, which builds and runs the SHARED AG3-088
checkpoint engine over the upgrade flow (story §6 — upgrade is an engine-driven
flow, not a second installer).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.installer.checkpoint_engine.execution_mode import ExecutionMode
from agentkit.backend.installer.upgrade.upgrade_flow import run_upgrade

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.installer.repository import ProjectRegistrationRepository
    from agentkit.backend.installer.upgrade.cleanup import CleanupPlan
    from agentkit.backend.installer.upgrade.hook_migration import HookRegistrationSurface
    from agentkit.backend.installer.upgrade.upgrade_flow import UpgradeResult
    from agentkit.backend.skills import Skills


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
    registration_repo: ProjectRegistrationRepository | None = None,
    governance: HookRegistrationSurface | None = None,
    skills: Skills | None = None,
) -> UpgradeResult:
    """Run the FK-51 upgrade flow through the engine for a productive project.

    Validates the writer-backed dependencies, then delegates to the engine-driven
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
    from agentkit.backend.exceptions import ProjectError

    if not project_root.is_dir():
        raise ProjectError(
            f"Project root does not exist: {project_root}",
            detail={"project_root": str(project_root)},
        )

    if registration_repo is None or governance is None or skills is None:
        raise ProjectError(
            "upgrade-project requires the authenticated active control-plane "
            "writer; no local State-Backend fallback is permitted",
            detail={
                "cause": "ControlPlaneWriterRequired",
                "project_key": project_key,
            },
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
        skills=skills,
        cleanup_plan=cleanup_plan,
    )


__all__ = ["run_checkpoint_upgrade"]
