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
from tests.fixtures.installer_writer import (
    InMemoryInstallerHookRepository,
    InMemoryInstallerProjectRepository,
    InMemoryInstallerRegistrationRepository,
)
from tests.fixtures.vectordb_installer import (
    GRPC_ENDPOINT,
    HTTP_ENDPOINT,
    ReadyVectorDbPreflight,
    passing_mcp_probe,
)
from tests.unit.vectordb.corpus_doubles import RecordingWeaviateClient

from agentkit.backend.installer.registration import RuntimeProfile
from agentkit.backend.installer.runner import (
    MANDATORY_SKILLS,
    InstallConfig,
)
from agentkit.backend.skills import MINIMUM_CONFORM_SKILL_BUNDLE_VERSIONS, Skills
from agentkit.backend.skills.bundle_store import SkillBundle, SkillBundleStore
from agentkit.backend.skills.repository import InMemorySkillBindingRepository

if TYPE_CHECKING:
    from pathlib import Path

_BUNDLE_IDS = {name: f"{name}-core" for name in MANDATORY_SKILLS}


InMemoryRegistrationRepo = InMemoryInstallerRegistrationRepository


def _provisioned_skills(bundle_store_root: Path) -> tuple[Skills, SkillBundleStore]:
    store = SkillBundleStore(store_root=bundle_store_root)
    for skill_name in MANDATORY_SKILLS:
        bundle_id = f"{skill_name}-core"
        bundle_version = MINIMUM_CONFORM_SKILL_BUNDLE_VERSIONS.get(
            bundle_id, "4.0.0"
        )
        bundle_root = bundle_store_root / bundle_id / bundle_version
        bundle_root.mkdir(parents=True, exist_ok=True)
        (bundle_root / "SKILL.md").write_text(f"# {skill_name}\n", encoding="utf-8")
        store.register_bundle(
            SkillBundle(
                bundle_id=bundle_id,
                bundle_version=bundle_version,
                bundle_root=bundle_root,
                manifest_digest="0" * 64,
            )
        )
    skills = Skills(bundle_store=store, binding_repo=InMemorySkillBindingRepository())
    return skills, store


#: Explicit, non-default Weaviate endpoints for the engine unit tests. They are
#: deliberately NOT localhost defaults: ``runtime_binding._reject_localhost``
#: rejects those (PO decision D2), and CP 10 must never synthesise an endpoint.
def make_config(
    root: Path,
    *,
    bundle_store_root: Path,
    registration_repo: InMemoryRegistrationRepo,
    project_repo: InMemoryInstallerProjectRepository | None = None,
    hook_registration_repo: InMemoryInstallerHookRepository | None = None,
    repo_existence_probe: object | None = None,
    features_vectordb: bool = True,
    features_are: bool = False,
    vectordb_http_endpoint: str | None = HTTP_ENDPOINT,
    vectordb_grpc_endpoint: str | None = GRPC_ENDPOINT,
    are_module_scope_map: dict[str, str] | None = None,
    repositories: list[dict[str, str]] | None = None,
    github_owner: str | None = "acme",
    github_repo: str | None = "demo",
    mcp_registration_probe: object = passing_mcp_probe,
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
        project_repo=project_repo or registration_repo.project_repo,
        hook_registration_repo=(
            hook_registration_repo or registration_repo.hook_repo
        ),
        runtime_profile=RuntimeProfile.CORE,
        repo_existence_probe=repo_existence_probe,  # type: ignore[arg-type]
        features_vectordb=features_vectordb,
        features_are=features_are,
        vectordb_http_endpoint=vectordb_http_endpoint,
        vectordb_grpc_endpoint=vectordb_grpc_endpoint,
        vectordb_preflight=ReadyVectorDbPreflight(),
        vectordb_client=RecordingWeaviateClient(),
        mcp_registration_probe=mcp_registration_probe,  # type: ignore[arg-type]
        are_module_scope_map=are_module_scope_map,
        sonarqube_available=False,
        ci_available=False,
    )


@pytest.fixture
def registration_repo() -> InMemoryRegistrationRepo:
    """A fresh in-memory registration repo."""
    return InMemoryRegistrationRepo()
