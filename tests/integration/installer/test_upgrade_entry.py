"""Integration: the productive upgrade boundary control ``run_checkpoint_upgrade``.

Exercises the ``installer_upgrade`` entry (``entry.py``) against the real state
backend (the integration conftest attaches the per-test backend fixture to every
``/integration/`` item). It wires the productive
``StateBackendProjectRegistrationRepository`` and delegates to the engine-driven
upgrade flow (FK-51, AG3-089 FIX 1).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
import yaml

from agentkit.backend.exceptions import ProjectError
from agentkit.backend.installer.checkpoint_engine.execution_mode import ExecutionMode
from agentkit.backend.installer.paths import project_config_path
from agentkit.backend.installer.registration import ProjectRegistration, RuntimeProfile
from agentkit.backend.installer.upgrade.entry import run_checkpoint_upgrade
from agentkit.backend.installer.upgrade.scenarios import UpgradeScenario
from agentkit.backend.state_backend.store.project_registration_repository import (
    StateBackendProjectRegistrationRepository,
)

if TYPE_CHECKING:
    from pathlib import Path


def _write_valid_config(project_root: Path) -> Path:
    path = project_config_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.dump(
            {
                "project_key": "demo",
                "project_name": "demo",
                "repositories": [{"name": "backend", "path": "/opt/backend"}],
                "pipeline": {
                    "config_version": "3.0",
                    "features": {"multi_llm": False},
            "vectordb": {"host": "weaviate.test.local", "port": 19903, "grpc_port": 50051},
                    "sonarqube": {"available": False, "enabled": False},
                    "ci": {"available": False, "enabled": False},
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


def test_run_checkpoint_upgrade_missing_root_fails_closed(tmp_path: Path) -> None:
    """A non-existent project root fails closed (ProjectError)."""
    with pytest.raises(ProjectError):
        run_checkpoint_upgrade(
            tmp_path / "does-not-exist",
            project_key="demo",
            github_owner="acme",
            github_repo="demo",
            target_config_version="3.0",
            mode=ExecutionMode.VERIFY,
        )


def test_run_checkpoint_upgrade_dry_run_wires_real_repo(tmp_path: Path) -> None:
    """dry_run wires the productive registration repo and decides the scenario.

    Covers the ``entry.py`` composition path (real backend repo, no governance in
    a read-only run) end-to-end without mutating the project.
    """
    project_root = tmp_path / "proj"
    project_root.mkdir()
    config_path = _write_valid_config(project_root)
    before = config_path.read_text(encoding="utf-8")

    # Register the project in the real backend with a STALE digest so the
    # §51.3.2 CONFIG_EDITED scenario is decided.
    repo = StateBackendProjectRegistrationRepository(project_root)
    repo.save(
        ProjectRegistration(
            project_key="demo",
            project_root=project_root,
            github_owner="acme",
            github_repo="demo",
            runtime_profile=RuntimeProfile.CORE,
            config_version="3.0",
            config_digest="stale-registered-digest",
            registered_at=datetime.now(tz=UTC),
        )
    )

    result = run_checkpoint_upgrade(
        project_root,
        project_key="demo",
        github_owner="acme",
        github_repo="demo",
        target_config_version="4.0",
        mode=ExecutionMode.DRY_RUN,
    )

    assert result.scenario.scenario is UpgradeScenario.CONFIG_EDITED
    assert result.mutated is False
    # Read-only: the on-disk config is untouched.
    assert config_path.read_text(encoding="utf-8") == before
