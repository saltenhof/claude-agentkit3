"""Integration: the productive upgrade boundary control ``run_checkpoint_upgrade``.

Exercises the ``installer_upgrade`` entry (``entry.py``) against the real state
backend (the integration conftest attaches the per-test backend fixture to every
``/integration/`` item). It wires the productive
``StateBackendProjectRegistrationRepository`` and delegates to the engine-driven
upgrade flow (FK-51, AG3-089 FIX 1).
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
import yaml

from agentkit.backend.config.models import ProjectConfig
from agentkit.backend.exceptions import ProjectError
from agentkit.backend.installer.checkpoint_engine.execution_mode import ExecutionMode
from agentkit.backend.installer.paths import project_config_path
from agentkit.backend.installer.registration import ProjectRegistration, RuntimeProfile
from agentkit.backend.installer.upgrade._digest import config_file_digest
from agentkit.backend.installer.upgrade.config_migration import BACKUP_SUFFIX
from agentkit.backend.installer.upgrade.engine import UP_02_GUARD_BINDING
from agentkit.backend.installer.upgrade.entry import run_checkpoint_upgrade
from agentkit.backend.installer.upgrade.scenarios import UpgradeScenario
from agentkit.backend.installer.writer_client import InstallerHookGovernance
from agentkit.backend.skills import SkillBundleStore, Skills
from agentkit.backend.skills.binding import (
    SkillBinding,
    SkillBindingMode,
    SkillLifecycleStatus,
)
from agentkit.backend.state_backend.store.governance_hook_repository import (
    StateBackendHookRegistrationRepository,
)
from agentkit.backend.state_backend.store.project_registration_repository import (
    StateBackendProjectRegistrationRepository,
)
from agentkit.backend.state_backend.store.skill_binding_repository import (
    StateBackendSkillBindingRepository,
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
                    "sonarqube": {"available": False, "enabled": False},
                    "ci": {"available": False, "enabled": False},
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


def _writer_dependencies(
    project_root: Path,
) -> tuple[InstallerHookGovernance, Skills]:
    return (
        InstallerHookGovernance(
            hook_repo=StateBackendHookRegistrationRepository(project_root),
            project_key="demo",
            project_root=project_root,
        ),
        Skills(
            bundle_store=SkillBundleStore(),
            binding_repo=StateBackendSkillBindingRepository(project_root),
        ),
    )


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
    governance, skills = _writer_dependencies(project_root)

    result = run_checkpoint_upgrade(
        project_root,
        project_key="demo",
        github_owner="acme",
        github_repo="demo",
        target_config_version="4.0",
        mode=ExecutionMode.DRY_RUN,
        registration_repo=repo,
        governance=governance,
        skills=skills,
    )

    assert result.scenario.scenario is UpgradeScenario.CONFIG_EDITED
    assert result.mutated is False
    # Read-only: the on-disk config is untouched.
    assert config_path.read_text(encoding="utf-8") == before


def test_productive_upgrade_repairs_disabled_vectordb_with_visible_notice(
    tmp_path: Path,
) -> None:
    """The productive boundary makes an AK3-written false config valid again."""
    project_root = tmp_path / "historical-vectordb-project"
    project_root.mkdir()
    subprocess.run(
        ["git", "init"],
        cwd=project_root,
        check=True,
        capture_output=True,
    )
    config_path = _write_valid_config(project_root)
    historical = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    historical["pipeline"]["features"]["vectordb"] = False
    historical["pipeline"]["features"]["telemetry"] = False
    config_path.write_text(yaml.dump(historical, sort_keys=False), encoding="utf-8")
    before = config_path.read_bytes()

    repo = StateBackendProjectRegistrationRepository(project_root)
    repo.save(
        ProjectRegistration(
            project_key="demo",
            project_root=project_root,
            github_owner="acme",
            github_repo="demo",
            runtime_profile=RuntimeProfile.CORE,
            config_version="3.0",
            config_digest=config_file_digest(config_path),
            registered_at=datetime.now(tz=UTC),
        )
    )
    governance, skills = _writer_dependencies(project_root)

    result = run_checkpoint_upgrade(
        project_root,
        project_key="demo",
        github_owner="acme",
        github_repo="demo",
        target_config_version="3.0",
        mode=ExecutionMode.REGISTER,
        registration_repo=repo,
        governance=governance,
        skills=skills,
    )

    assert result.config_migrated is True
    assert "Project 'demo'" in result.detail
    assert str(project_root) in result.detail
    assert "pipeline.features.vectordb from false to true" in result.detail
    assert "changed project behavior from disabled to enabled" in result.detail
    assert config_path.with_name("project.yaml" + BACKUP_SUFFIX).read_bytes() == before
    on_disk = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert on_disk["pipeline"]["features"]["vectordb"] is True
    assert on_disk["pipeline"]["features"]["telemetry"] is False
    ProjectConfig.model_validate(on_disk)
    stored = repo.get("demo")
    assert stored is not None
    assert stored.config_digest == config_file_digest(config_path)


@pytest.mark.parametrize(
    ("skill_name", "bundle_id", "bundle_version"),
    [
        ("create-userstory", "create-userstory-core", "4.1.0"),
        ("execute-userstory", "execute-userstory-core", "4.0.0"),
        ("concept-incubation", "concept-incubation-core", "4.0.0"),
        ("create-userstory", "create-userstory-core", "not-a-version"),
    ],
)
@pytest.mark.parametrize(
    "mode",
    [ExecutionMode.REGISTER, ExecutionMode.DRY_RUN, ExecutionMode.VERIFY],
)
def test_run_checkpoint_upgrade_rejects_real_norm_violating_pin_before_mutation(
    tmp_path: Path,
    skill_name: str,
    bundle_id: str,
    bundle_version: str,
    mode: ExecutionMode,
) -> None:
    project_root = tmp_path / "proj"
    project_root.mkdir()
    config_path = _write_valid_config(project_root)
    before = config_path.read_text(encoding="utf-8")
    registration_repo = StateBackendProjectRegistrationRepository(project_root)
    registration_repo.save(
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
    binding_repo = StateBackendSkillBindingRepository(project_root)
    binding_repo.save(
        SkillBinding(
            binding_id=f"{skill_name}-{mode.value}",
            project_key=project_root.stem,
            skill_name=skill_name,
            bundle_id=bundle_id,
            bundle_version=bundle_version,
            content_digest="0" * 64,
            target_path=project_root / ".claude" / "skills" / skill_name,
            binding_mode=SkillBindingMode.SYMLINK,
            status=SkillLifecycleStatus.VERIFIED,
            pinned_at=datetime.now(tz=UTC),
        )
    )
    governance, skills = _writer_dependencies(project_root)

    result = run_checkpoint_upgrade(
        project_root,
        project_key="demo",
        github_owner="acme",
        github_repo="demo",
        target_config_version="4.0",
        mode=mode,
        registration_repo=registration_repo,
        governance=governance,
        skills=skills,
    )

    assert result.failed_checkpoints == (UP_02_GUARD_BINDING,)
    assert result.failed is True
    assert "Norm-violating skill pin(s)" in result.detail
    assert result.mutated is False
    assert config_path.read_text(encoding="utf-8") == before
    assert not config_path.with_name(config_path.name + BACKUP_SUFFIX).exists()
