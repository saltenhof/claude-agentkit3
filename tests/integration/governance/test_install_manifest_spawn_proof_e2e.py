"""E2E NO-STUB: Install -> Header -> AG3-086 guard allow/block (AG3-110 AC4).

The core acceptance of AG3-110. Against the REAL register-mode installer AND the REAL
AG3-086 prompt-integrity guard now on main, with NO stubbing of the manifest or the
token:

  (a) a real install writes ``.installed-manifest.json`` with a non-empty
      ``agent_spawn_skill_proof`` token;
  (b) a real ``story_execution`` spawn header (SKILL.md shape) carries the RESOLVED
      token after read-time substitution (``PlaceholderSubstitutor.substitute_spawn_header``)
      — not the literal ``{{AGENT_SPAWN_SKILL_PROOF}}`` placeholder;
  (c) the real AG3-086 guard Stage 2 ALLOWS that authorized spawn
      (``expected_skill_proof`` == header token);
  (d) the same guard still BLOCKS a forged token and a missing token/manifest
      (fail-closed).

Also: idempotent re-install keeps the token unchanged (FK-51) and dry_run/verify do
NOT mutate the manifest (FK-50 §50.2/§50.3).

Runs on a real ``tmp_path`` project against a real SQLite state-backend (the installer
registration + skill-binding repos honour ``AGENTKIT_STATE_BACKEND=sqlite``); the guard
emitter uses the same backend. No mock of the manifest/token/guard.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

# Reuse the productive guard-dispatch harness helpers (real edge binding + real event)
from tests.integration.governance.test_prompt_integrity_dispatch import (
    _agent_event,
    _publish_story_binding,
)

from agentkit.config.models import (
    SUPPORTED_CONFIG_VERSION,
    Features,
    JenkinsConfig,
    PipelineConfig,
    ProjectConfig,
    RepositoryConfig,
    SonarQubeConfig,
)
from agentkit.governance.guard_system import OPAQUE_MESSAGE
from agentkit.governance.runner import (
    _installed_skill_proof,
    _run_prompt_integrity_guard,
)
from agentkit.installer.bootstrap_checkpoints.orchestrator import run_checkpoint_install
from agentkit.installer.checkpoint_engine.execution_mode import ExecutionMode
from agentkit.installer.installed_manifest import SKILL_PROOF_KEY
from agentkit.installer.paths import installed_manifest_path
from agentkit.installer.registration import RuntimeProfile
from agentkit.installer.runner import (
    MANDATORY_SKILLS,
    InstallConfig,
    install_agentkit,
)
from agentkit.skills import PlaceholderSubstitutor
from agentkit.skills.bundle_store import SkillBundle, SkillBundleStore
from agentkit.state_backend.store import reset_backend_cache_for_tests
from agentkit.state_backend.store.project_registration_repository import (
    StateBackendProjectRegistrationRepository,
)
from agentkit.state_backend.store.skill_binding_repository import (
    StateBackendSkillBindingRepository,
)
from agentkit.utils.io import read_json_object

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

_STORY = "AG3-800"
_BUNDLE_IDS = {name: f"{name}-core" for name in MANDATORY_SKILLS}

_OPT_OUT_PIPELINE = PipelineConfig(  # type: ignore[call-arg]
    config_version=SUPPORTED_CONFIG_VERSION,
    features=Features(multi_llm=False),
    sonarqube=SonarQubeConfig(available=False, enabled=False),
    ci=JenkinsConfig(available=False, enabled=False),
)


@pytest.fixture(autouse=True)
def _sqlite_backend(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    monkeypatch.delenv("AGENTKIT_STATE_DATABASE_URL", raising=False)
    reset_backend_cache_for_tests()
    yield
    reset_backend_cache_for_tests()


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


def _make_config(root: Path, *, store: SkillBundleStore) -> InstallConfig:
    from agentkit.skills import Skills

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
        skills=skills,
        skill_bundle_store=store,
        skill_bundle_ids=_BUNDLE_IDS,
        registration_repo=StateBackendProjectRegistrationRepository(root),
        runtime_profile=RuntimeProfile.CORE,
        sonarqube_available=False,
        ci_available=False,
    )


def _project_config(root: Path) -> ProjectConfig:
    return ProjectConfig(
        project_key=root.stem,
        project_name=root.stem,
        repositories=[RepositoryConfig(name="app", path=root)],
        github_owner="acme",
        github_repo=root.stem,
        pipeline=_OPT_OUT_PIPELINE,
    )


def _qa_header(token: str) -> str:
    # role=story-qa keeps the spawn EXEMPT from Stage 3 (dynamic prompts) so the test
    # isolates Stage 2 skill_proof validation — the AG3-110 scope (FK-31 §31.7.2).
    return (
        "AGENTKIT-SUBAGENT-V1 mode=story_execution role=story-qa "
        f"story_id={_STORY} skill_proof={token}"
    )


def _git_init(root: Path) -> None:
    # Hermeticity (Jenkins #325 fix): production CP11 runs
    # ``git -C <root> config core.hooksPath tools/hooks/``, which REQUIRES a real
    # git repo AT ``root``. Without this, git walks UP to any ambient parent repo
    # (non-hermetic, can pollute the real repo) and on CI's parent-less tmp dir
    # fails with ``git_config_failed``. Initialise an isolated repo at ``root``.
    subprocess.run(  # noqa: S603 - fixed argv, no shell
        ["git", "init", str(root)],
        capture_output=True,
        check=True,
    )


def _install(root: Path) -> SkillBundleStore:
    root.mkdir(parents=True, exist_ok=True)
    _git_init(root)
    store = _bundle_store_with_all_skills(root.parent)
    result = install_agentkit(_make_config(root, store=store))
    assert result.success, result
    return store


@pytest.mark.integration
def test_real_install_writes_manifest_with_token(tmp_path: Path) -> None:
    # AC1/AC4(a): a real register-mode install writes the manifest with a non-empty
    # agent_spawn_skill_proof token (and the real AG3-086 reader reads it non-empty).
    root = tmp_path / "proj"
    _install(root)

    manifest_path = installed_manifest_path(root)
    assert manifest_path.is_file()
    data = read_json_object(manifest_path)
    token = data[SKILL_PROOF_KEY]
    assert isinstance(token, str) and token
    assert "authorized_prompt_paths" in data
    assert "template_manifest_hash" in data
    # The real consumer reader resolves the SAME token (no shadow reader).
    assert _installed_skill_proof(root) == token


@pytest.mark.integration
def test_e2e_install_header_guard_allows_and_blocks(tmp_path: Path) -> None:
    # AC4 (Kernkriterium): Install -> resolved header -> real guard allows authorized,
    # blocks forged + missing — all NO-STUB.
    root = tmp_path / "proj"
    _install(root)
    token = read_json_object(installed_manifest_path(root))[SKILL_PROOF_KEY]
    assert isinstance(token, str)

    # (b) the real read-time substitutor resolves the header token (not the literal).
    raw_header = _qa_header("{{AGENT_SPAWN_SKILL_PROOF}}")
    resolved_header = PlaceholderSubstitutor().substitute_spawn_header(
        raw_header, _project_config(root), root
    )
    assert f"skill_proof={token}" in resolved_header
    assert "{{AGENT_SPAWN_SKILL_PROOF}}" not in resolved_header

    _publish_story_binding(root, str(root))

    # (c) the real AG3-086 guard ALLOWS the authorized spawn (Stage 2 proof match).
    allow_verdict = _run_prompt_integrity_guard(
        _agent_event(root, description=resolved_header, prompt="qa round 1"),
        project_root=root,
    )
    assert allow_verdict.allowed is True

    # (d.1) a FORGED token (header token != manifest token) is blocked fail-closed.
    forged_verdict = _run_prompt_integrity_guard(
        _agent_event(root, description=_qa_header("forged-token"), prompt="qa round 1"),
        project_root=root,
    )
    assert forged_verdict.allowed is False
    assert forged_verdict.message == OPAQUE_MESSAGE


@pytest.mark.integration
def test_e2e_guard_blocks_missing_manifest(tmp_path: Path) -> None:
    # (d.2) a missing manifest (no installed token) blocks every story_execution
    # spawn fail-closed — even one carrying a syntactically valid header.
    root = tmp_path / "proj-nomanifest"
    root.mkdir(parents=True)
    _publish_story_binding(root, str(root))
    assert not installed_manifest_path(root).exists()

    verdict = _run_prompt_integrity_guard(
        _agent_event(root, description=_qa_header("any-token"), prompt="qa round 1"),
        project_root=root,
    )
    assert verdict.allowed is False
    assert verdict.message == OPAQUE_MESSAGE


@pytest.mark.integration
def test_idempotent_reinstall_keeps_token(tmp_path: Path) -> None:
    # AC5 (FK-51): a second install of the SAME project leaves the token UNCHANGED.
    root = tmp_path / "proj-idem"
    store = _bundle_store_with_all_skills(tmp_path)
    root.mkdir()
    _git_init(root)  # hermetic isolated repo for CP11 git config (Jenkins #325)
    assert install_agentkit(_make_config(root, store=store)).success
    first = read_json_object(installed_manifest_path(root))[SKILL_PROOF_KEY]

    assert install_agentkit(_make_config(root, store=store)).success
    second = read_json_object(installed_manifest_path(root))[SKILL_PROOF_KEY]
    assert second == first


@pytest.mark.integration
def test_dry_run_does_not_write_manifest(tmp_path: Path) -> None:
    # AC6 (FK-50 §50.2/§50.3): dry_run and verify modes MUST NOT mutate — no manifest
    # is written.
    root = tmp_path / "proj-dry"
    root.mkdir()
    store = _bundle_store_with_all_skills(tmp_path)
    config = _make_config(root, store=store)

    for mode in (ExecutionMode.DRY_RUN, ExecutionMode.VERIFY):
        run_checkpoint_install(config, mode=mode)
        assert not installed_manifest_path(root).exists(), mode
