from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from tests.fixtures.git_repo import ensure_git_repo

from agentkit.installer import InstallConfig, install_agentkit
from agentkit.installer.runner import MANDATORY_SKILLS
from agentkit.skills import Skills, create_directory_link
from agentkit.skills.bundle_store import SkillBundle, SkillBundleStore
from agentkit.skills.repository import InMemorySkillBindingRepository

if TYPE_CHECKING:
    from datetime import datetime

    from agentkit.installer.registration import ProjectRegistration


class _InMemoryRegistrationRepo:
    """In-memory ProjectRegistrationRepository so the unit path skips Postgres.

    CP 7 (AG3-039) registers the project in the central State-Backend before any
    bundle binding; this namespace smoke test injects the fake so the full
    install runs without a live backend.
    """

    def __init__(self) -> None:
        self.rows: dict[str, ProjectRegistration] = {}

    def get(self, project_key: str) -> ProjectRegistration | None:
        return self.rows.get(project_key)

    def save(self, registration: ProjectRegistration) -> None:
        self.rows[registration.project_key] = registration

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

    def list_all(self) -> list[ProjectRegistration]:
        return [self.rows[k] for k in sorted(self.rows)]


def _directory_links_supported() -> bool:
    """Probe the production link layer (symlink POSIX / junction Windows; the
    junction needs no Developer Mode, so True on every supported platform)."""
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "src"
        src.mkdir()
        link = Path(d) / "link"
        try:
            create_directory_link(link, src)
            return True
        except OSError:
            return False


_LINKS_AVAILABLE = _directory_links_supported()
_BUNDLE_IDS = {name: f"{name}-core" for name in MANDATORY_SKILLS}


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
    return Skills(bundle_store=store, binding_repo=InMemorySkillBindingRepository()), store


@pytest.mark.skipif(
    not _LINKS_AVAILABLE,
    reason="Filesystem supports neither symlinks nor directory junctions",
)
def test_installer_namespace_exposes_install_api(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    # CP 11 configures core.hooksPath; real targets are git repos (see helper).
    ensure_git_repo(project_root)
    skills, store = _provisioned_skills(tmp_path / ".skill-bundles")
    config = InstallConfig(
        project_key="demo",
        project_name="demo",
        project_root=project_root,
        github_owner="acme",
        github_repo="demo",
        registration_repo=_InMemoryRegistrationRepo(),
        skills=skills,
        skill_bundle_store=store,
        skill_bundle_ids=_BUNDLE_IDS,
        # AG3-052 Design-Decision: scaffold default is available:true (FK-03
        # §3); no live Sonar here => conscious opt-out so CP 10d is SKIPPED.
        sonarqube_available=False,
        # AG3-056 (FIX-5): no live Jenkins here => conscious opt-out so the CI
        # preflight SKIPS.
        ci_available=False,
    )
    result = install_agentkit(config)

    assert result.success is True
    assert (project_root / ".agentkit" / "config" / "project.yaml").exists()
