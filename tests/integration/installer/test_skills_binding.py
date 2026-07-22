"""Integration: installer binds the FK-43 §43.3.1 mandatory skills (AG3-048, AK#5-7).

End-to-end through ``install_agentkit`` with a real ``SkillBundleStore`` +
productive ``StateBackendSkillBindingRepository`` (the integration backend is
real Postgres via the per-test ``postgres_isolated_schema`` fixture the
integration conftest attaches to every ``/integration/`` item — AG3-051):

- all four mandatory skills are bound
- the harness bind points (``.claude/skills/`` AND ``.codex/skills/``) hold
  thin LINKS — a symlink on POSIX, a directory junction on Windows (FK-43
  §43.4.1.1 multi-harness) — not file copies
- the installer no longer pre-creates an empty ``.claude/skills`` directory
- the target project ``.gitignore`` ignores the link bind points (FK-43
  §43.4.1.1)
- fail-closed: a missing mandatory bundle aborts install with
  ``InstallationError(cause=BundleNotFound)`` and no partial links

The Windows junction needs no Developer Mode, so binding works on every
supported platform — these tests no longer skip on Windows. The probe only
guards an exotic filesystem that rejects both link kinds.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from tests.fixtures.git_repo import ensure_git_repo

from agentkit.backend.exceptions import InstallationError
from agentkit.backend.installer.runner import (
    MANDATORY_SKILLS,
    InstallConfig,
    install_agentkit,
)
from agentkit.backend.skills import Skills
from agentkit.backend.skills.bundle_store import SkillBundle, SkillBundleStore
from agentkit.backend.skills.links import create_directory_link, is_directory_link
from agentkit.backend.skills.repository import InMemorySkillBindingRepository
from agentkit.backend.state_backend.store.skill_binding_repository import (
    StateBackendSkillBindingRepository,
)


def _directory_links_supported() -> bool:
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


def _bundle_store_with_all_skills(root: Path) -> SkillBundleStore:
    """Register one real on-disk bundle per mandatory skill in a fresh store."""
    store = SkillBundleStore(store_root=root / "skill-bundles")
    for skill_name in MANDATORY_SKILLS:
        bundle_root = root / "skill-bundles" / f"{skill_name}-core" / "4.0.0"
        bundle_root.mkdir(parents=True, exist_ok=True)
        (bundle_root / "SKILL.md").write_text(
            f"# {skill_name}\n", encoding="utf-8"
        )
        store.register_bundle(
            SkillBundle(
                bundle_id=f"{skill_name}-core",
                bundle_version="4.0.0",
                bundle_root=bundle_root,
                manifest_digest="0" * 64,
            )
        )
    return store


def _make_config(
    root: Path,
    *,
    skills: Skills | None = None,
    skill_bundle_store: SkillBundleStore | None = None,
    skill_bundle_ids: dict[str, str] | None = None,
) -> InstallConfig:
    return InstallConfig(
        weaviate_host="weaviate.test.local",
        weaviate_http_port=19903,
        weaviate_grpc_port=50051,
        project_key="skills-it",
        project_name="skills-it",
        project_root=root,
        # CP 7 (AG3-039) requires mandatory GitHub coordinates; without them the
        # install fails closed at CP 7 BEFORE skill binding. These tests exercise
        # the binding path, so they must satisfy CP 7's precondition.
        github_owner="acme",
        github_repo="skills-it",
        skills=skills,
        skill_bundle_store=skill_bundle_store,
        skill_bundle_ids=skill_bundle_ids,
        # AG3-052 Design-Decision: scaffold default is ``available: true``
        # (FK-03 §3). No live SonarQube here => declare the conscious opt-out
        # so the completing install's CP 10d is SKIPPED (not fail-closed).
        sonarqube_available=False,
        # No live Jenkins here => conscious opt-out so the CI preflight SKIPS
        # (AG3-056 FIX-5).
        ci_available=False,
    )


@pytest.mark.integration
@pytest.mark.skipif(
    not _LINKS_AVAILABLE,
    reason="Filesystem supports neither symlinks nor directory junctions",
)
def test_install_binds_all_mandatory_skills_as_links(tmp_path: Path) -> None:
    # Distinct project stem per test: the binding project_key is project_root.stem
    # and the integration backend (Postgres) is shared across the session, so a
    # shared "project" stem would leak rows between tests.
    root = tmp_path / "proj-binds-all"
    root.mkdir()
    # AG3-088 CI regression (Jenkins #314): this COMPLETING install reaches CP 11
    # (cp11_to_12.py, FK-50 §50.3), which runs ``git config core.hooksPath`` and
    # hard-aborts (reason ``git_config_failed``) when the target is not a git
    # repo. Real AgentKit targets ARE git repos; a clean Linux CI agent puts
    # ``tmp_path`` under ``/tmp`` (no ambient parent repo). Git-init only HERE,
    # not in ``_make_config`` — the fail-closed tests in this module abort before
    # CP 11 and assert the project root stays EMPTY (no partial scaffold), so a
    # ``.git`` dir must not be created for them.
    ensure_git_repo(root)
    store = _bundle_store_with_all_skills(tmp_path)
    skills = Skills(
        bundle_store=store,
        binding_repo=StateBackendSkillBindingRepository(root),
    )

    result = install_agentkit(
        _make_config(
            root,
            skills=skills,
            skill_bundle_store=store,
            skill_bundle_ids=_BUNDLE_IDS,
        )
    )
    assert result.success

    for skill_name in MANDATORY_SKILLS:
        claude_link = root / ".claude" / "skills" / skill_name
        codex_link = root / ".codex" / "skills" / skill_name
        # Multi-harness links — symlink on POSIX, junction on Windows (FK-43
        # §43.4.1.1 AK4) — NOT file copies.
        assert is_directory_link(claude_link), f"{skill_name}: .claude link missing"
        assert is_directory_link(codex_link), f"{skill_name}: .codex link missing"
        # The link resolves to the systemwide bundle root (single source).
        expected = (
            tmp_path / "skill-bundles" / f"{skill_name}-core" / "4.0.0"
        ).resolve()
        assert claude_link.resolve() == expected
        assert codex_link.resolve() == expected

    # Persistence: every mandatory binding is recorded VERIFIED in the repo.
    bound = {b.skill_name: b for b in skills.list_bound_skills(root)}
    assert set(bound) == set(MANDATORY_SKILLS)

    # FK-43 §43.4.1.1: the target project .gitignore ignores the link bind
    # points so a junction/symlink is never committed as bundle content.
    gitignore = (root / ".gitignore").read_text(encoding="utf-8")
    assert ".claude/skills/" in gitignore
    assert ".codex/skills/" in gitignore


@pytest.mark.integration
def test_no_skill_config_fails_closed_when_bundles_unprovisioned(
    tmp_path: Path,
) -> None:
    """A normal install with no injected skills MUST bind the four mandatory
    skills (AC#5). When the systemwide bundle store is not provisioned with
    them the install FAILS CLOSED with ``BundleNotFound`` — it does NOT
    silently succeed and skip binding (AG3-048 Codex review ERROR 1, AC#7).

    The default-built ``SkillBundleStore`` points at the platform store root
    (overridden here to an empty dir) and has no registered bundles, so the
    first mandatory bundle is missing.
    """
    import os

    from agentkit.backend.skills.bundle_store import SKILL_BUNDLE_STORE_ENV

    root = tmp_path / "proj-no-config"
    root.mkdir()
    # Point the default systemwide store at an empty dir (no provisioned
    # bundles) so the default-built store resolves nothing.
    prev = os.environ.get(SKILL_BUNDLE_STORE_ENV)
    os.environ[SKILL_BUNDLE_STORE_ENV] = str(tmp_path / "empty-system-store")
    try:
        with pytest.raises(InstallationError) as exc_info:
            install_agentkit(_make_config(root))
    finally:
        if prev is None:
            os.environ.pop(SKILL_BUNDLE_STORE_ENV, None)
        else:
            os.environ[SKILL_BUNDLE_STORE_ENV] = prev

    assert exc_info.value.detail.get("cause") == "BundleNotFound"
    # No partial install: no harness skill directories were created.
    assert not (root / ".claude" / "skills").exists()
    assert not (root / ".codex" / "skills").exists()


@pytest.mark.integration
def test_fail_closed_missing_bundle_no_partial_install(tmp_path: Path) -> None:
    """A missing mandatory bundle aborts with InstallationError(cause=BundleNotFound)
    BEFORE any link is created (no partial install)."""
    root = tmp_path / "proj-missing-bundle"
    root.mkdir()
    # Store with NO registered bundles -> first mandatory bundle is missing.
    empty_store = SkillBundleStore(store_root=tmp_path / "empty-bundles")
    skills = Skills(
        bundle_store=empty_store,
        binding_repo=InMemorySkillBindingRepository(),
    )

    with pytest.raises(InstallationError) as exc_info:
        install_agentkit(
            _make_config(
                root,
                skills=skills,
                skill_bundle_store=empty_store,
                skill_bundle_ids=_BUNDLE_IDS,
            )
        )
    assert exc_info.value.detail.get("cause") == "BundleNotFound"
    # Codex-r7 FINDING: the skill-bundle resolution is a PREFLIGHT that runs
    # BEFORE any project write, so a missing bundle leaves the project ENTIRELY
    # untouched — not just the skill bind points, but no scaffold/resource/prompt
    # artifacts at all (no half-scaffolded project).
    assert sorted(root.iterdir()) == []


@pytest.mark.integration
@pytest.mark.skipif(
    not _LINKS_AVAILABLE,
    reason="Filesystem supports neither symlinks nor directory junctions",
)
def test_bind_failure_after_first_skill_rolls_back_all(tmp_path: Path) -> None:
    """Bundle resolution succeeds for all four, but ``bind_skill`` fails on the
    SECOND skill — after the first skill already created its links AND
    persisted its binding. The installer rolls back EVERYTHING: no leftover
    links and no persisted bindings (AG3-048 Codex review ERROR 2, AC#7,
    FK-50 §50.5).

    Trigger: the second mandatory skill's bundle dir holds a malformed
    ``manifest.json`` (parses to a non-object), which passes the store
    resolution (Phase 1) but makes ``bind_skill`` raise during Phase 2.
    """
    root = tmp_path / "proj-rollback"
    root.mkdir()
    store = _bundle_store_with_all_skills(tmp_path)
    # Corrupt the SECOND mandatory skill's manifest so bind_skill fails AFTER
    # the first skill is fully bound.
    second = MANDATORY_SKILLS[1]
    bad_manifest = (
        tmp_path / "skill-bundles" / f"{second}-core" / "4.0.0" / "manifest.json"
    )
    bad_manifest.write_text("[]", encoding="utf-8")  # JSON array, not an object

    repo = StateBackendSkillBindingRepository(root)
    skills = Skills(bundle_store=store, binding_repo=repo)

    with pytest.raises(InstallationError) as exc_info:
        install_agentkit(
            _make_config(
                root,
                skills=skills,
                skill_bundle_store=store,
                skill_bundle_ids=_BUNDLE_IDS,
            )
        )
    assert exc_info.value.detail.get("cause") == "BindFailed"
    assert exc_info.value.detail.get("skill_name") == second

    # No leftover links for ANY skill (including the first, fully-bound one).
    for skill_name in MANDATORY_SKILLS:
        for harness_dir in (".claude", ".codex"):
            link = root / harness_dir / "skills" / skill_name
            assert not is_directory_link(link), f"leftover link: {link}"
            assert not link.exists(), f"leftover path: {link}"

    # No persisted bindings remain in the repository.
    assert skills.list_bound_skills(root) == []


@pytest.mark.integration
def test_partial_skill_injection_rejected(tmp_path: Path) -> None:
    """Injecting only ``skills`` (without the store) is rejected fail-closed."""
    root = tmp_path / "proj-partial"
    root.mkdir()
    store = _bundle_store_with_all_skills(tmp_path)
    skills = Skills(
        bundle_store=store,
        binding_repo=InMemorySkillBindingRepository(),
    )
    with pytest.raises(InstallationError) as exc_info:
        install_agentkit(
            _make_config(root, skills=skills, skill_bundle_ids=_BUNDLE_IDS)
        )
    assert exc_info.value.detail.get("cause") == "InvalidConfig"
