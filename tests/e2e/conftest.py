"""E2E test fixtures."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from agentkit.installer import InstallConfig, install_agentkit
from agentkit.pipeline.lifecycle import NoOpHandler, PhaseHandlerRegistry

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture()
def installed_project(tmp_path: Path) -> Path:
    """A target project with AgentKit installed.

    Returns:
        The project root directory with ``.agentkit/`` fully set up.
    """
    project_dir = tmp_path / "test-project"
    project_dir.mkdir()
    install_agentkit(
        InstallConfig(
            project_name="test-project",
            project_root=project_dir,
        )
    )
    return project_dir


@pytest.fixture()
def noop_registry() -> PhaseHandlerRegistry:
    """A PhaseHandlerRegistry with NoOpHandler for common phases.

    Registers NoOpHandler for all five standard phases:
    setup, exploration, implementation, verify, closure.
    """
    registry = PhaseHandlerRegistry()
    for phase in ("setup", "exploration", "implementation", "verify", "closure"):
        registry.register(phase, NoOpHandler())
    return registry
