"""Installer component namespace for project registration and bootstrap.

Public installer symbols are loaded on first access.  Keeping package import
side-effect free is part of the dependency-preflight boundary: callers must be
able to inspect an incomplete environment before importing deeper checkpoint
or integration modules.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentkit.backend.installer.bootstrap_checkpoints import (
        run_checkpoint_install as run_checkpoint_install,
    )
    from agentkit.backend.installer.checkpoint_engine import (
        CheckpointEngine as CheckpointEngine,
    )
    from agentkit.backend.installer.checkpoint_engine import (
        ExecutionMode as ExecutionMode,
    )
    from agentkit.backend.installer.checkpoint_engine import (
        build_installer_flow as build_installer_flow,
    )
    from agentkit.backend.installer.registration import (
        CheckpointResult as CheckpointResult,
    )
    from agentkit.backend.installer.registration import (
        CheckpointStatus as CheckpointStatus,
    )
    from agentkit.backend.installer.registration import (
        ProjectRegistration as ProjectRegistration,
    )
    from agentkit.backend.installer.registration import (
        RuntimeProfile as RuntimeProfile,
    )
    from agentkit.backend.installer.repo_probe import (
        GhCliRepoExistenceProbe as GhCliRepoExistenceProbe,
    )
    from agentkit.backend.installer.repo_probe import (
        RepoExistenceProbe as RepoExistenceProbe,
    )
    from agentkit.backend.installer.repo_probe import (
        RepoProbeResult as RepoProbeResult,
    )
    from agentkit.backend.installer.repository import (
        ProjectRegistrationRepository as ProjectRegistrationRepository,
    )
    from agentkit.backend.installer.runner import (
        InstallConfig as InstallConfig,
    )
    from agentkit.backend.installer.runner import (
        InstallResult as InstallResult,
    )
    from agentkit.backend.installer.runner import (
        install_agentkit as install_agentkit,
    )
    from agentkit.backend.installer.upgrade import (
        CustomizationFootprint as CustomizationFootprint,
    )
    from agentkit.backend.installer.upgrade import (
        UpgradeResult as UpgradeResult,
    )
    from agentkit.backend.installer.upgrade import (
        UpgradeScenario as UpgradeScenario,
    )
    from agentkit.backend.installer.upgrade import (
        migrate_config as migrate_config,
    )
    from agentkit.backend.installer.upgrade import (
        run_cleanup as run_cleanup,
    )
    from agentkit.backend.installer.upgrade import (
        run_upgrade as run_upgrade,
    )

_CHECKPOINT_ENGINE_MODULE = "agentkit.backend.installer.checkpoint_engine"
_REGISTRATION_MODULE = "agentkit.backend.installer.registration"
_REPO_PROBE_MODULE = "agentkit.backend.installer.repo_probe"
_RUNNER_MODULE = "agentkit.backend.installer.runner"
_UPGRADE_MODULE = "agentkit.backend.installer.upgrade"

_EXPORT_MODULES = {
    "CheckpointEngine": _CHECKPOINT_ENGINE_MODULE,
    "CheckpointResult": _REGISTRATION_MODULE,
    "CheckpointStatus": _REGISTRATION_MODULE,
    "CustomizationFootprint": _UPGRADE_MODULE,
    "ExecutionMode": _CHECKPOINT_ENGINE_MODULE,
    "GhCliRepoExistenceProbe": _REPO_PROBE_MODULE,
    "InstallConfig": _RUNNER_MODULE,
    "InstallResult": _RUNNER_MODULE,
    "ProjectRegistration": _REGISTRATION_MODULE,
    "ProjectRegistrationRepository": "agentkit.backend.installer.repository",
    "RepoExistenceProbe": _REPO_PROBE_MODULE,
    "RepoProbeResult": _REPO_PROBE_MODULE,
    "RuntimeProfile": _REGISTRATION_MODULE,
    "UpgradeResult": _UPGRADE_MODULE,
    "UpgradeScenario": _UPGRADE_MODULE,
    "build_installer_flow": _CHECKPOINT_ENGINE_MODULE,
    "install_agentkit": _RUNNER_MODULE,
    "migrate_config": _UPGRADE_MODULE,
    "run_checkpoint_install": "agentkit.backend.installer.bootstrap_checkpoints",
    "run_cleanup": _UPGRADE_MODULE,
    "run_upgrade": _UPGRADE_MODULE,
}

_PREFLIGHTED_EXPORT_MODULES = {
    "agentkit.backend.installer.bootstrap_checkpoints",
    _RUNNER_MODULE,
}

__all__ = list(_EXPORT_MODULES)


def __getattr__(name: str) -> object:
    """Load one public installer symbol without importing unrelated surfaces."""
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    if module_name in _PREFLIGHTED_EXPORT_MODULES:
        from agentkit.backend.installer.interpreter import (
            resolve_ak3_interpreter,
        )

        resolve_ak3_interpreter()
        from agentkit.backend.installer.dependency_preflight import (
            require_runtime_dependencies,
        )

        require_runtime_dependencies()
    value = getattr(importlib.import_module(module_name), name)
    globals()[name] = value
    return value
