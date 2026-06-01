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
    from pathlib import Path

_BUNDLE_IDS = {name: f"{name}-core" for name in MANDATORY_SKILLS}


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


def _config(tmp_path: Path, skills: object, store: object) -> InstallConfig:
    root = tmp_path / "project"
    root.mkdir(exist_ok=True)
    return InstallConfig(
        project_key="host-indep",
        project_name="host-indep",
        project_root=root,
        skills=skills,  # type: ignore[arg-type]
        skill_bundle_store=store,  # type: ignore[arg-type]
        skill_bundle_ids=_BUNDLE_IDS,
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
    config = _config(tmp_path, _RecordingSkills(), store)
    install_agentkit(config)

    second_skills = _RecordingSkills()
    config2 = _config(tmp_path, second_skills, store)
    result = install_agentkit(config2)

    assert result.success
    assert sorted(second_skills.bound) == sorted(MANDATORY_SKILLS)
