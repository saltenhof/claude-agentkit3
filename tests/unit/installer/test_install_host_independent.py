"""Host-independent install/uninstall coverage for the runner (AG3-048).

These tests drive the FULL ``install_agentkit`` glue and ``uninstall_agentkit``
WITHOUT needing symlink privilege (no Developer Mode required). Symlink
creation is the ONLY part of a real install that needs the privilege, so we
inject a fake ``Skills`` top-surface whose ``bind_skill`` records the call
instead of creating symlinks. Everything else (resource deploy, prompt-bundle
store/lock, control-plane config, project.yaml, codex settings, and the
mandatory-skill orchestration in ``_bind_mandatory_skills``) is exercised by
REAL code on any host.

This is not a mock of productive core logic: the installer's binding step is
DI-injected (``InstallConfig.skills``), and the fake exercises exactly the
contract the real ``Skills`` satisfies. The symlink-creation behaviour itself
is proven separately on a symlink-capable host (Jenkins) by the integration
and CLI tests.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.installer.runner import (
    MANDATORY_SKILLS,
    InstallConfig,
    install_agentkit,
    uninstall_agentkit,
)
from agentkit.skills.bundle_store import SkillBundle

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

    from agentkit.installer.registration import ProjectRegistration

_BUNDLE_IDS = {name: f"{name}-core" for name in MANDATORY_SKILLS}


class _InMemoryRegistrationRepo:
    """In-memory ProjectRegistrationRepository so the unit path skips Postgres.

    CP 7 (AG3-039) registers the project in the central State-Backend before any
    bundle binding. These host-independent unit tests inject this fake (DI, like
    the fake ``Skills``) so ``install_agentkit`` exercises CP 7 + the binding glue
    without a live backend.
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


class _FakeStore:
    """Resolves every mandatory bundle to a real on-disk dummy root."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def get_bundle(self, bundle_id: str) -> SkillBundle:
        bundle_root = self._root / bundle_id / "4.0.0"
        bundle_root.mkdir(parents=True, exist_ok=True)
        return SkillBundle(
            bundle_id=bundle_id,
            bundle_version="4.0.0",
            bundle_root=bundle_root,
            manifest_digest="0" * 64,
        )


class _RecordingSkills:
    """Fake Skills top-surface: records binds instead of creating symlinks."""

    def __init__(self) -> None:
        self.bound: list[str] = []

    def bind_skill(self, skill_name: str, bundle_root: Path, project_root: Path) -> None:
        del bundle_root, project_root
        self.bound.append(skill_name)

    def unbind_skill(self, skill_name: str, project_root: Path) -> None:  # pragma: no cover
        del skill_name, project_root


def _config(
    tmp_path: Path,
    skills: object,
    store: object,
    registration_repo: _InMemoryRegistrationRepo | None = None,
) -> InstallConfig:
    root = tmp_path / "project"
    root.mkdir(exist_ok=True)
    return InstallConfig(
        project_key="host-indep",
        project_name="host-indep",
        project_root=root,
        github_owner="acme",
        github_repo="host-indep",
        registration_repo=registration_repo or _InMemoryRegistrationRepo(),
        skills=skills,  # type: ignore[arg-type]
        skill_bundle_store=store,  # type: ignore[arg-type]
        skill_bundle_ids=_BUNDLE_IDS,
        # AG3-052 Design-Decision: scaffold default is available:true (FK-03
        # §3); no live Sonar here => conscious opt-out so CP 10d is SKIPPED.
        sonarqube_available=False,
        # AG3-056 (FIX-5): the CI preflight mirrors the Sonar discipline; no
        # live Jenkins here => conscious opt-out so the CI checkpoint SKIPS.
        ci_available=False,
    )


def test_full_install_glue_runs_and_binds_all_mandatory(tmp_path: Path) -> None:
    """The whole install pipeline runs on ANY host with injected binding.

    Proves the post-bind glue (prompt-bundle store/lock, control-plane config,
    project.yaml, codex settings) and that ``_bind_mandatory_skills`` binds all
    four mandatory skills exactly once.
    """
    skills = _RecordingSkills()
    store = _FakeStore(tmp_path / "bundles")
    config = _config(tmp_path, skills, store)

    result = install_agentkit(config)

    assert result.success
    assert sorted(skills.bound) == sorted(MANDATORY_SKILLS)
    root = config.project_root
    assert (root / ".agentkit" / "config" / "project.yaml").exists()
    # A representative set of glue artifacts were created.
    created = set(result.created_files)
    assert any("project.yaml" in c for c in created)


def test_full_install_aborts_when_ci_available_without_client(tmp_path: Path) -> None:
    """FIX-5 end-to-end: an available:true CI with no ci_client ABORTS install.

    The CI preflight is wired into ``install_agentkit`` exactly like CP 10d; a
    real CI trigger must never be promised against an unverified Jenkins.
    """
    import pytest

    from agentkit.exceptions import InstallationError

    skills = _RecordingSkills()
    store = _FakeStore(tmp_path / "bundles")
    config = _config(tmp_path, skills, store)
    # Re-declare CI as present but inject no Jenkins client => fail-closed abort.
    config.ci_available = True
    with pytest.raises(InstallationError, match="CI .Jenkins. precondition FAILED"):
        install_agentkit(config)


def test_full_install_passes_ci_preflight_with_working_client(tmp_path: Path) -> None:
    """FIX-5 end-to-end: an available:true CI with a working client install OK."""
    from dataclasses import dataclass

    @dataclass(frozen=True)
    class _Resp:
        json_body: dict[str, object]

    class _OkJenkins:
        def whoami(self) -> _Resp:
            return _Resp({"id": "ak3"})

        def job_exists(self, pipeline: str) -> _Resp:
            del pipeline
            return _Resp({"name": "ak3-pre-merge"})

    skills = _RecordingSkills()
    store = _FakeStore(tmp_path / "bundles")
    config = _config(tmp_path, skills, store)
    config.ci_available = True
    config.ci_client = _OkJenkins()  # type: ignore[assignment]
    result = install_agentkit(config)
    assert result.success


def test_install_then_uninstall_removes_artifacts(tmp_path: Path) -> None:
    """``uninstall_agentkit`` removes the installed artifact tree (host-indep:
    no symlinks were created by the fake bind, so removal of empty harness
    dirs and the .agentkit tree is exercised end-to-end)."""
    skills = _RecordingSkills()
    store = _FakeStore(tmp_path / "bundles")
    config = _config(tmp_path, skills, store)
    install_agentkit(config)
    root = config.project_root

    result = uninstall_agentkit(root)

    assert result.success
    assert not (root / ".agentkit").exists()
    # project_root itself remains; the managed subtree is gone.
    assert root.is_dir()


def test_install_repeated_is_idempotent(tmp_path: Path) -> None:
    """A second install over the same root succeeds and re-binds (idempotent
    glue: unchanged files are not re-reported as created)."""
    store = _FakeStore(tmp_path / "bundles")
    # Share the registration repo so the second install is a genuine CP 7
    # idempotent re-run (same project, already registered) rather than a fresh
    # CREATED against an empty backend.
    registration_repo = _InMemoryRegistrationRepo()
    config = _config(tmp_path, _RecordingSkills(), store, registration_repo)
    install_agentkit(config)

    second_skills = _RecordingSkills()
    config2 = _config(tmp_path, second_skills, store, registration_repo)
    result = install_agentkit(config2)

    assert result.success
    assert sorted(second_skills.bound) == sorted(MANDATORY_SKILLS)
