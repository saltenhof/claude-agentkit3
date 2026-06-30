"""Integration: installer CP 7 persists a ProjectRegistration (AG3-039, AC4/5/7).

End-to-end through ``install_agentkit`` against the real Postgres backend (the
integration conftest attaches the per-test ``postgres_isolated_schema`` fixture
to every ``/integration/`` item — AG3-051). Verifies:

- a fresh install registers the project in ``project_registry`` with the
  correct fields and a CP 7 ``CheckpointResult`` (CREATED);
- an idempotent re-run with the SAME config yields CP 7 SKIPPED and does not
  rewrite the row;
- a re-run with a CHANGED config (different digest) upgrades the row
  (``last_upgraded_at`` set, new digest) and yields CP 7 UPDATED.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
from tests.fixtures.git_repo import ensure_git_repo

from agentkit.backend.installer.bootstrap_checkpoints.cp01_to_06 import (
    REASON_MISSING_COORDINATES,
    REASON_REPO_UNREACHABLE,
)
from agentkit.backend.installer.checkpoint_engine import node_ids as nid
from agentkit.backend.installer.checkpoint_engine.node_ids import CP_02_REPO_CHECK
from agentkit.backend.installer.paths import (
    prompt_bundle_lock_path,
    static_prompts_dir,
)
from agentkit.backend.installer.registration import (
    CP7_STATE_BACKEND_REGISTRATION,
    CheckpointStatus,
    RuntimeProfile,
)
from agentkit.backend.installer.runner import (
    _CI_CHECKPOINT_ID,
    MANDATORY_SKILLS,
    PROMPT_MANIFEST_FILENAME,
    InstallConfig,
    install_agentkit,
)
from agentkit.backend.skills import Skills
from agentkit.backend.skills.bundle_store import SkillBundle, SkillBundleStore
from agentkit.backend.state_backend.store.project_management_repository import (
    StateBackendProjectRepository,
)
from agentkit.backend.state_backend.store.project_registration_repository import (
    StateBackendProjectRegistrationRepository,
)
from agentkit.backend.state_backend.store.skill_binding_repository import (
    StateBackendSkillBindingRepository,
)

_BUNDLE_IDS = {name: f"{name}-core" for name in MANDATORY_SKILLS}


def _bundle_store_with_all_skills(root: Path) -> SkillBundleStore:
    store = SkillBundleStore(store_root=root / "skill-bundles")
    for skill_name in MANDATORY_SKILLS:
        bundle_root = root / "skill-bundles" / f"{skill_name}-core" / "4.0.0"
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
    return store


def _make_config(
    root: Path,
    *,
    store: SkillBundleStore,
    registration_repo: StateBackendProjectRegistrationRepository,
    extra_repo: dict[str, str] | None = None,
) -> InstallConfig:
    # AG3-088 CI regression (Jenkins #314): CP 11 (cp11_to_12.py, FK-50 §50.3)
    # runs ``git config core.hooksPath`` and hard-aborts (reason
    # ``git_config_failed``) when the target is not a git repo. Real AgentKit
    # targets ARE git repos; a clean Linux CI agent puts ``tmp_path`` under
    # ``/tmp`` (no ambient parent repo), so git-init the project root first via
    # the shared helper. Tests that assert an EARLY fail-closed abort (CP 2/CP 7,
    # before CP 11) are unaffected; the completing installs that gate on
    # ``result.success`` now reach CP 11 with a real repo.
    ensure_git_repo(root)
    skills = Skills(
        bundle_store=store,
        binding_repo=StateBackendSkillBindingRepository(root),
    )
    return InstallConfig(
        project_key=root.stem,
        project_name=root.stem,
        project_root=root,
        github_owner="acme",
        github_repo=root.stem,
        repositories=[extra_repo] if extra_repo is not None else None,
        skills=skills,
        skill_bundle_store=store,
        skill_bundle_ids=_BUNDLE_IDS,
        registration_repo=registration_repo,
        runtime_profile=RuntimeProfile.CORE,
        # No live SonarQube here => conscious opt-out so CP 10d is SKIPPED.
        sonarqube_available=False,
        # No live Jenkins here => conscious opt-out so the CI preflight SKIPS
        # (AG3-056 FIX-5).
        ci_available=False,
    )


class _OrderingSpyRepo(StateBackendProjectRegistrationRepository):
    """Captures the filesystem skill-bind-point state observed AT save() time.

    Proves ``installer.invariant.state_backend_registration_precedes_bundle_binding``
    (E2): when CP 7 ``save`` runs, no project-local skill link must exist yet —
    skill binding (CP 8) is ordered strictly after registration.
    """

    def __init__(self, store_dir: Path, project_root: Path) -> None:
        super().__init__(store_dir)
        self._project_root = project_root
        self.skills_dir_present_at_save: bool | None = None

    def save(self, registration: object) -> None:
        claude_skills = self._project_root / ".claude" / "skills"
        codex_skills = self._project_root / ".codex" / "skills"
        self.skills_dir_present_at_save = (
            claude_skills.exists() or codex_skills.exists()
        )
        super().save(registration)  # type: ignore[arg-type]


@pytest.mark.integration
def test_cp7_registration_precedes_bundle_binding(tmp_path: Path) -> None:
    """E2: state-backend registration (CP 7) completes BEFORE skill bindings."""
    root = tmp_path / "proj-order"
    root.mkdir()
    store = _bundle_store_with_all_skills(tmp_path)
    repo = _OrderingSpyRepo(root, root)

    result = install_agentkit(_make_config(root, store=store, registration_repo=repo))
    assert result.success
    # The CP 7 save must have observed NO skill bind point yet (binding is later).
    assert repo.skills_dir_present_at_save is False
    # And after the full install, the skill links DO exist (binding ran after).
    assert (root / ".claude" / "skills").exists()


@pytest.mark.integration
@pytest.mark.parametrize("bad_owner", [None, "", "   "])
def test_install_aborts_on_failed_cp2_no_bindings(
    tmp_path: Path, bad_owner: str | None
) -> None:
    """B1 (AG3-088): missing/empty GitHub coordinates abort at CP 2 (fail-closed).

    With the checkpoint engine (AG3-088), CP 2 (the GitHub-repo check) is the
    fail-closed coordinate gate ordered BEFORE CP 5 (scaffold) and CP 7. Missing
    or empty coordinates FAIL at CP 2 (``reason=missing_github_coordinates``), the
    engine aborts, and NO scaffold / registration / binding is written — an even
    earlier abort than the legacy CP 7 gate. ``success=False`` is returned with
    the FAILED CheckpointResult propagated.
    """
    root = tmp_path / "proj-failclosed"
    root.mkdir()
    store = _bundle_store_with_all_skills(tmp_path)
    repo = StateBackendProjectRegistrationRepository(root)
    config = dataclasses.replace(
        _make_config(root, store=store, registration_repo=repo),
        github_owner=bad_owner,
        github_repo=None if bad_owner is None else "demo",
    )

    result = install_agentkit(config)

    # Install aborts: not successful, FAILED CP 2 propagated with its reason.
    assert result.success is False
    assert result.checkpoint_results is not None
    cp2 = next(
        r for r in result.checkpoint_results if r.checkpoint == CP_02_REPO_CHECK
    )
    assert cp2.status is CheckpointStatus.FAILED
    assert cp2.reason == REASON_MISSING_COORDINATES
    # CP 7 never ran (CP 2 aborted earlier) — no registration was persisted.
    assert all(
        r.checkpoint != CP7_STATE_BACKEND_REGISTRATION
        for r in result.checkpoint_results
    )
    # No registration was persisted, and no skill bindings ran (no bind points).
    assert repo.get(root.stem) is None
    assert not (root / ".claude" / "skills").exists()
    assert not (root / ".codex" / "skills").exists()

    # B1-Rest (AG3-039 R4): NO ACTIVE projectlocal harness binding may exist when
    # CP 7 FAILED. The active harness bindings are deployed STRICTLY AFTER the CP 7
    # gate, so a FAILED CP 7 must leave none of them on disk
    # (formal.installer.invariant.state_backend_registration_precedes_bundle_binding;
    # story §2.1.4; FK-50 §50.3/§50.4). Concretely: no Codex hook config, no Claude
    # Code PreToolUse hook settings, no prompt-lock / prompt / skill-binding
    # artefacts.
    assert not (root / ".codex" / "config.toml").exists()
    assert not (root / ".claude" / "settings.json").exists()
    assert not (root / ".agentkit" / "hooks" / "pre_tool_use.py").exists()
    assert not prompt_bundle_lock_path(root).exists()
    assert not static_prompts_dir(root).joinpath(PROMPT_MANIFEST_FILENAME).exists()
    assert StateBackendSkillBindingRepository(root).list_for_project(root.stem) == []


@pytest.mark.integration
@pytest.mark.parametrize(
    ("bad_owner", "bad_repo"),
    [
        ("..", "demo"),  # path-traversal owner
        ("acme", ".git"),  # leading-dot / ".git"-style bare repo
        ("-bad", "demo"),  # leading-hyphen owner
        ("acme\n", "demo"),  # trailing-newline owner (ERROR-1)
    ],
)
def test_install_aborts_on_invalid_cp2_coordinates_no_bindings(
    tmp_path: Path, bad_owner: str, bad_repo: str
) -> None:
    """AG3-088: a direct install with MALFORMED GitHub coordinates fails closed.

    The SSOT coordinate validation (``validate_github_coordinate``) is enforced at
    the CP 2 port (ordered before CP 5/CP 7), so a present-but-invalid coordinate
    FAILs at CP 2 (``reason=repo_unreachable`` — the malformed-coordinate case),
    the engine aborts and binds nothing. CP 7 never runs.
    """
    root = tmp_path / "proj-invalidcoords"
    root.mkdir()
    store = _bundle_store_with_all_skills(tmp_path)
    repo = StateBackendProjectRegistrationRepository(root)
    config = dataclasses.replace(
        _make_config(root, store=store, registration_repo=repo),
        github_owner=bad_owner,
        github_repo=bad_repo,
    )

    result = install_agentkit(config)

    assert result.success is False
    assert result.checkpoint_results is not None
    cp2 = next(
        r for r in result.checkpoint_results if r.checkpoint == CP_02_REPO_CHECK
    )
    assert cp2.status is CheckpointStatus.FAILED
    assert cp2.reason == REASON_REPO_UNREACHABLE
    assert all(
        r.checkpoint != CP7_STATE_BACKEND_REGISTRATION
        for r in result.checkpoint_results
    )
    # No invalid registration persisted, no harness/skill bindings deployed.
    assert repo.get(root.stem) is None
    assert not (root / ".claude" / "skills").exists()
    assert not (root / ".codex" / "skills").exists()
    assert not (root / ".codex" / "config.toml").exists()
    assert not (root / ".claude" / "settings.json").exists()
    assert not (root / ".agentkit" / "hooks" / "pre_tool_use.py").exists()
    assert not prompt_bundle_lock_path(root).exists()
    assert StateBackendSkillBindingRepository(root).list_for_project(root.stem) == []


@pytest.mark.integration
def test_install_persists_project_registration(tmp_path: Path) -> None:
    root = tmp_path / "proj-register"
    root.mkdir()
    store = _bundle_store_with_all_skills(tmp_path)
    repo = StateBackendProjectRegistrationRepository(root)

    result = install_agentkit(_make_config(root, store=store, registration_repo=repo))
    assert result.success

    # B1-Rest (AG3-039 R4): after a SUCCESSFUL CP 7, the active harness bindings
    # ARE deployed (counterpart to the FAILED-CP7 assertion that none exist).
    assert (root / ".codex" / "config.toml").is_file()
    assert (root / ".claude" / "settings.json").is_file()
    assert (root / ".agentkit" / "hooks" / "pre_tool_use.py").is_file()
    assert prompt_bundle_lock_path(root).is_file()

    # AC7: checkpoint_results carries the CP 7 entry (CREATED on first install).
    assert result.checkpoint_results is not None
    cp7 = [
        r for r in result.checkpoint_results if r.checkpoint == CP7_STATE_BACKEND_REGISTRATION
    ]
    assert len(cp7) == 1
    assert cp7[0].status is CheckpointStatus.CREATED

    # AG3-056 WARNING-2: the orthogonal CI preflight result is RECORDED by the
    # install façade. This config opts out of CI (ci_available=False) => SKIPPED
    # with a machine-readable reason.
    ci_cp = [r for r in result.checkpoint_results if r.checkpoint == _CI_CHECKPOINT_ID]
    assert len(ci_cp) == 1
    assert ci_cp[0].status is CheckpointStatus.SKIPPED
    assert ci_cp[0].reason == "not_applicable"
    # AG3-088: CP 10d is a branch-gated checkpoint (branch_sonarqube_enabled). With
    # sonarqube_available=False the sonar branch does NOT fire, so CP 10d never runs
    # and contributes no result (the applicability decision is now the flow branch).
    sonar_cp = [
        r for r in result.checkpoint_results if r.checkpoint == nid.CP_10D_SONARQUBE
    ]
    assert sonar_cp == []

    # AC4-ish: the registration is persisted with the correct fields.
    stored = repo.get(root.stem)
    assert stored is not None
    assert stored.project_key == root.stem
    assert stored.project_root == root
    assert stored.github_owner == "acme"
    assert stored.github_repo == root.stem
    assert stored.runtime_profile is RuntimeProfile.CORE
    assert stored.config_version == "1"
    assert len(stored.config_digest) == 64
    assert stored.last_verified_at is None
    assert stored.last_upgraded_at is None

    visible_project = StateBackendProjectRepository(root).get(root.stem)
    assert visible_project is not None
    assert visible_project.key == root.stem
    assert visible_project.name == root.stem
    assert visible_project.story_id_prefix == "PR"
    assert visible_project.configuration.repositories == ["."]


@pytest.mark.integration
def test_idempotent_rerun_skips_cp7(tmp_path: Path) -> None:
    root = tmp_path / "proj-idem"
    root.mkdir()
    store = _bundle_store_with_all_skills(tmp_path)
    repo = StateBackendProjectRegistrationRepository(root)

    install_agentkit(_make_config(root, store=store, registration_repo=repo))
    digest_after_first = repo.get(root.stem)
    assert digest_after_first is not None

    # Identical config -> idempotent CP 7 SKIP, row unchanged.
    result = install_agentkit(_make_config(root, store=store, registration_repo=repo))
    cp7 = next(
        r for r in result.checkpoint_results or () if r.checkpoint == CP7_STATE_BACKEND_REGISTRATION
    )
    assert cp7.status is CheckpointStatus.SKIPPED
    after_second = repo.get(root.stem)
    assert after_second is not None
    assert after_second.config_digest == digest_after_first.config_digest
    assert after_second.last_upgraded_at is None


@pytest.mark.integration
def test_relative_project_root_install_persists_absolute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AG3-123 r2 (MAJOR 1): a RELATIVE ``--project-root`` install still registers.

    The productive CLI passes ``--project-root .`` verbatim, so the install entry
    receives a RELATIVE ``project_root``. The model-floor
    ``_validate_project_root_absolute`` would reject that on the CP 7 persist; the
    single canonical resolution point (``run_checkpoint_install``) resolves the
    install boundary to an ABSOLUTE backend anchor FIRST, so the install registers
    successfully AND the persisted ``project_root`` is absolute (no relative anchor
    can ever reach ``project_registry``).
    """
    root = tmp_path / "proj-relative"
    root.mkdir()
    store = _bundle_store_with_all_skills(tmp_path)
    repo = StateBackendProjectRegistrationRepository(root)
    # The CLI passes the operator's ``--project-root`` verbatim; ``.`` (relative)
    # is the common productive invocation. Run it from inside ``root`` so ``.``
    # resolves to ``root``.
    monkeypatch.chdir(root)
    config = dataclasses.replace(
        _make_config(root, store=store, registration_repo=repo),
        project_root=Path("."),
    )

    result = install_agentkit(config)

    assert result.success
    # The install result root is the resolved ABSOLUTE anchor, not the relative ``.``.
    assert result.project_root.is_absolute()
    assert result.project_root == root.resolve()

    # The persisted registration carries the ABSOLUTE canonical anchor.
    stored = repo.get(config.project_key)
    assert stored is not None
    assert stored.project_root.is_absolute()
    assert stored.project_root == root.resolve()


@pytest.mark.integration
def test_changed_config_upgrades_registration(tmp_path: Path) -> None:
    root = tmp_path / "proj-upgrade"
    root.mkdir()
    store = _bundle_store_with_all_skills(tmp_path)
    repo = StateBackendProjectRegistrationRepository(root)

    install_agentkit(_make_config(root, store=store, registration_repo=repo))
    first = repo.get(root.stem)
    assert first is not None

    # Re-run with an extra repository entry -> different project.yaml -> different
    # config_digest -> UPGRADED.
    result = install_agentkit(
        _make_config(
            root,
            store=store,
            registration_repo=repo,
            extra_repo={"name": "extra", "path": "extra"},
        )
    )
    cp7 = next(
        r for r in result.checkpoint_results or () if r.checkpoint == CP7_STATE_BACKEND_REGISTRATION
    )
    assert cp7.status is CheckpointStatus.UPDATED
    after = repo.get(root.stem)
    assert after is not None
    assert after.config_digest != first.config_digest
    assert after.last_upgraded_at is not None
