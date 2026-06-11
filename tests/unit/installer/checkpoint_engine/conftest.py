"""Shared fixtures for the installer checkpoint-engine unit tests (AG3-088).

Builds an :class:`InstallConfig` wired with an in-memory registration repo and a
provisioned skill-bundle store + binding repo, so the engine can run a full
``register`` mode end-to-end against ``tmp_path`` WITHOUT a live state backend
(unit-level isolation; the integration suite exercises the real Postgres path).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from tests.fixtures.git_repo import ensure_git_repo

from agentkit.installer.registration import ProjectRegistration, RuntimeProfile
from agentkit.installer.runner import MANDATORY_SKILLS, InstallConfig
from agentkit.skills import Skills
from agentkit.skills.bundle_store import SkillBundle, SkillBundleStore
from agentkit.skills.repository import InMemorySkillBindingRepository

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

_BUNDLE_IDS = {name: f"{name}-core" for name in MANDATORY_SKILLS}


class InMemoryRegistrationRepo:
    """In-memory ``ProjectRegistrationRepository`` for unit isolation."""

    def __init__(self) -> None:
        self.rows: dict[str, ProjectRegistration] = {}
        self.save_calls = 0
        self.upgrade_calls = 0

    def get(self, project_key: str) -> ProjectRegistration | None:
        return self.rows.get(project_key)

    def save(self, registration: ProjectRegistration) -> None:
        self.rows[registration.project_key] = registration
        self.save_calls += 1

    def update_verified(self, project_key: str, verified_at: datetime) -> None:
        reg = self.rows[project_key]
        self.rows[project_key] = reg.model_copy(update={"last_verified_at": verified_at})

    def update_upgraded(
        self, project_key: str, upgraded_at: datetime, new_digest: str
    ) -> None:
        reg = self.rows[project_key]
        self.rows[project_key] = reg.model_copy(
            update={"last_upgraded_at": upgraded_at, "config_digest": new_digest}
        )
        self.upgrade_calls += 1

    def list_all(self) -> list[ProjectRegistration]:
        return [self.rows[k] for k in sorted(self.rows)]


def _provisioned_skills(bundle_store_root: Path) -> tuple[Skills, SkillBundleStore]:
    store = SkillBundleStore(store_root=bundle_store_root)
    for skill_name in MANDATORY_SKILLS:
        bundle_root = bundle_store_root / f"{skill_name}-core" / "4.0.0"
        bundle_root.mkdir(parents=True, exist_ok=True)
        (bundle_root / "SKILL.md").write_text(f"# {skill_name}\n", encoding="utf-8")
        store.register_bundle(
            SkillBundle(
                bundle_id=f"{skill_name}-core",
                bundle_version="4.0.0",
                bundle_root=bundle_root,
                manifest_digest="0" * 64,
            )
        )
    skills = Skills(bundle_store=store, binding_repo=InMemorySkillBindingRepository())
    return skills, store


def make_config(
    root: Path,
    *,
    bundle_store_root: Path,
    registration_repo: InMemoryRegistrationRepo,
    repo_existence_probe: object | None = None,
    features_vectordb: bool = False,
    features_are: bool = False,
    are_module_scope_map: dict[str, str] | None = None,
    repositories: list[dict[str, str]] | None = None,
    github_owner: str | None = "acme",
    github_repo: str | None = "demo",
) -> InstallConfig:
    """Build an :class:`InstallConfig` for the engine unit tests."""
    # CP 11 (FK-50 §50.3) configures core.hooksPath on the target project; real
    # AK3 targets ARE git repos, so the unit setup must provision one (else CP 11
    # fails on a clean CI agent where tmp_path is not inside any repo).
    ensure_git_repo(root)
    skills, store = _provisioned_skills(bundle_store_root)
    return InstallConfig(
        project_key=root.stem,
        project_name=root.stem,
        project_root=root,
        github_owner=github_owner,
        github_repo=github_repo,
        repositories=repositories,
        skills=skills,
        skill_bundle_store=store,
        skill_bundle_ids=_BUNDLE_IDS,
        registration_repo=registration_repo,  # type: ignore[arg-type]
        runtime_profile=RuntimeProfile.CORE,
        repo_existence_probe=repo_existence_probe,  # type: ignore[arg-type]
        features_vectordb=features_vectordb,
        features_are=features_are,
        are_module_scope_map=are_module_scope_map,
        sonarqube_available=False,
        ci_available=False,
    )


@pytest.fixture
def registration_repo() -> InMemoryRegistrationRepo:
    """A fresh in-memory registration repo."""
    return InMemoryRegistrationRepo()
