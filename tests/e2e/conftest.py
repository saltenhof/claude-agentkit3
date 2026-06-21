"""E2E test fixtures."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from agentkit.backend.installer import InstallConfig, install_agentkit
from agentkit.backend.pipeline_engine.lifecycle import NoOpHandler, PhaseHandlerRegistry

if TYPE_CHECKING:
    from pathlib import Path

# ``pytest_plugins`` lebt in ``tests/conftest.py`` (Top-Level, pytest 8+
# Anforderung); hier nur Collection-Hook fuer Postgres-Bindung.
#
# AG3-051 (Codex-Fix): OPT-IN statt Suite-Wholesale. Frueher haengte dieser Hook
# ``postgres_isolated_schema`` an JEDES ``/e2e/`` item. Das zog Docker auch auf
# reine GitHub-Live-Tests, die KEIN State-Backend ausueben:
# ``github_live/test_issues.py`` und ``github_live/test_projects.py`` reden nur
# mit der GitHub-API (kein ``save_*``/``load_*``). Das ist derselbe AK4-Verstoss
# wie bei der Contract-Deny-List ("Pure-Tests ziehen kein Docker/Postgres").
#
# Modell jetzt: eine EXPLIZITE ALLOW-LIST der Postgres-nutzenden e2e-Pfade. Die
# Smoke-Pipeline und die GitHub-Live-Phasentests persistieren echten State
# (``save_story_context``/``save_phase_snapshot``/``save_flow_execution``) und
# brauchen die per-test-Isolation; die zwei reinen GitHub-API-Module nicht.
_POSTGRES_E2E_ALLOW_PATHS: tuple[str, ...] = (
    "/e2e/smoke/",
    "/e2e/github_live/test_closure_phase.py",
    "/e2e/github_live/test_setup_phase.py",
)


def pytest_collection_modifyitems(config, items):  # type: ignore[no-untyped-def]
    del config  # unused, explicit for hook signature parity
    for item in items:
        path = str(item.fspath).replace("\\", "/")
        if any(allow in path for allow in _POSTGRES_E2E_ALLOW_PATHS):
            item.fixturenames.append("postgres_isolated_schema")


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
            project_key="test-project",
            project_name="test-project",
            project_root=project_dir,
            github_owner="acme",  # AG3-039 R6: CP 7 coordinates are MANDATORY
            github_repo="demo",
            sonarqube_available=False,  # AG3-052: conscious opt-out, no live Sonar
            ci_available=False,  # AG3-056: conscious opt-out, no live Jenkins
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
