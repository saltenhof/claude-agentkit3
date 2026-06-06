from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from agentkit.installer import InstallConfig, install_agentkit, uninstall_agentkit
from agentkit.installer.paths import PROMPT_BUNDLE_STORE_ENV
from agentkit.installer.runner import MANDATORY_SKILLS
from agentkit.skills import Skills, create_directory_link, is_directory_link
from agentkit.skills.bundle_store import SkillBundle, SkillBundleStore
from agentkit.skills.repository import InMemorySkillBindingRepository

if TYPE_CHECKING:
    from datetime import datetime

    from agentkit.installer.registration import ProjectRegistration


class _InMemoryRegistrationRepo:
    """In-memory ProjectRegistrationRepository so the unit path skips Postgres.

    CP 7 (AG3-039) registers the project in the central State-Backend before any
    bundle binding; these multi-harness unit tests inject this fake so the full
    install glue runs without a live backend.
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
    """Probe the production link layer (symlink on POSIX, junction on Windows).

    The Windows junction needs no Developer Mode, so this is True on every
    supported platform; the probe only guards an exotic filesystem.
    """
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


@pytest.mark.skipif(
    not _LINKS_AVAILABLE,
    reason="Filesystem supports neither symlinks nor directory junctions",
)
def test_install_creates_claude_and_codex_settings(tmp_path: Path) -> None:
    result = install_agentkit(_make_config(tmp_path))

    assert result.success is True
    assert (tmp_path / ".claude" / "settings.json").is_file()
    assert (tmp_path / ".codex" / "config.toml").is_file()
    assert "agentkit-hook-codex" in (
        tmp_path / ".codex" / "config.toml"
    ).read_text(encoding="utf-8")


@pytest.mark.skipif(
    not _LINKS_AVAILABLE,
    reason="Filesystem supports neither symlinks nor directory junctions",
)
def test_install_is_idempotent(tmp_path: Path) -> None:
    first = install_agentkit(_make_config(tmp_path))
    before = _file_snapshot(tmp_path)

    second = install_agentkit(_make_config(tmp_path))
    after = _file_snapshot(tmp_path)

    assert first.created_files
    assert second.created_files == ()
    assert after == before


@pytest.mark.skipif(
    not _LINKS_AVAILABLE,
    reason="Filesystem supports neither symlinks nor directory junctions",
)
def test_uninstall_removes_harness_settings(tmp_path: Path) -> None:
    install_agentkit(_make_config(tmp_path))

    result = uninstall_agentkit(tmp_path)

    assert result.success is True
    assert not (tmp_path / ".claude" / "settings.json").exists()
    assert not (tmp_path / ".codex" / "config.toml").exists()
    assert not (tmp_path / ".agentkit").exists()


@pytest.mark.skipif(
    not _LINKS_AVAILABLE,
    reason="Filesystem supports neither symlinks nor directory junctions",
)
def test_uninstall_removes_skill_links_and_central_bundle_survives(
    tmp_path: Path,
) -> None:
    """Codex-r7-r2: install creates the harness skill links; uninstall must
    DETACH every link (a junction via os.rmdir, NEVER rmtree through the link)
    so no link survives, the bind-point dirs are gone, AND the central bundle is
    untouched (the link removal must not delete its target).
    """
    bundle_store_root = tmp_path.parent / f".skill-bundles-{tmp_path.name}"
    install_agentkit(_make_config(tmp_path))

    # Links exist after install (one per mandatory skill, per harness).
    claude_links = [
        p for p in (tmp_path / ".claude" / "skills").iterdir() if is_directory_link(p)
    ]
    assert len(claude_links) == len(MANDATORY_SKILLS)

    uninstall_agentkit(tmp_path)

    # No skill links survive; both bind-point dirs are removed.
    assert not (tmp_path / ".claude" / "skills").exists()
    assert not (tmp_path / ".codex" / "skills").exists()
    # The CENTRAL bundles survive — os.rmdir detached the links without deleting
    # their targets (no rmtree through a junction).
    for skill_name in MANDATORY_SKILLS:
        assert (
            bundle_store_root / f"{skill_name}-core" / "4.0.0" / "SKILL.md"
        ).is_file()


def _provisioned_skills(bundle_store_root: Path) -> tuple[Skills, SkillBundleStore]:
    """Provision the four FK-43 §43.3.1 mandatory bundles in a fresh store.

    AG3-048: a normal install binds the four mandatory skills (no silent skip),
    so these tests must provision the bundles for the install to succeed.
    """
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


def _make_config(project_root: Path) -> InstallConfig:
    skills, store = _provisioned_skills(
        project_root.parent / f".skill-bundles-{project_root.name}"
    )
    return InstallConfig(
        project_key="ag3",
        project_name="AG3",
        project_root=project_root,
        github_owner="acme",
        github_repo="ag3",
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


def _file_snapshot(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


@pytest.fixture(autouse=True)
def _set_prompt_bundle_store_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        PROMPT_BUNDLE_STORE_ENV,
        str(tmp_path / ".prompt-bundle-store"),
    )
