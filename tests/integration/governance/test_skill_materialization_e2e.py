"""E2E NO-STUB: Install -> materialized variant -> header THROUGH the real bind point
-> AG3-086 guard allow/block (AG3-111 AC4).

The core acceptance of AG3-111. Against the REAL register-mode installer AND the REAL
AG3-086 prompt-integrity guard on main, with NO stub of the substitution, the
materialization, the manifest or the guard:

  (a) a real install of a PLACEHOLDER-BEARING skill writes ``.installed-manifest.json``
      (AG3-110) AND materializes a substituted variant; the ``SKILL.md`` linked content
      carries NO literal ``{{...}}``;
  (b) the test reads ``SKILL.md`` THROUGH BOTH real harness bind points —
      ``.claude/skills/<skill>/SKILL.md`` AND ``.codex/skills/<skill>/SKILL.md`` — NOT
      from the variant dir directly; at both, the content is placeholder-free and the
      ``story_execution`` header carries the real token;
  (c) the real AG3-086 guard Stage 2 ALLOWS the authorized spawn whose header is read
      from the real bind point (``header.skill_proof == expected_skill_proof``);
  (d) the same guard still BLOCKS a forged token AND a missing token/manifest
      (fail-closed).

Also: idempotent re-install -> byte-identical variant under the same digest dir; the
project bind point is a LINK pointing at the variant in the AK3 install store (no skill
source copied into the repo); the variant lives ONLY in the separate variant store.

A placeholder-FREE skill keeps the raw ``bundle_root`` link (no variant).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest
from tests.integration.governance.test_prompt_integrity_dispatch import (
    _agent_event,
    _publish_story_binding,
)

from agentkit.governance.guard_system import OPAQUE_MESSAGE
from agentkit.governance.runner import _run_prompt_integrity_guard
from agentkit.installer.installed_manifest import SKILL_PROOF_KEY
from agentkit.installer.paths import installed_manifest_path
from agentkit.installer.registration import RuntimeProfile
from agentkit.installer.runner import (
    MANDATORY_SKILLS,
    InstallConfig,
    install_agentkit,
)
from agentkit.skills import (
    Skills,
    is_directory_link,
    read_directory_link_target,
)
from agentkit.skills.bundle_store import SkillBundle, SkillBundleStore, shipped_skill_bundles_root
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

# The dispatch harness pins these (test_prompt_integrity_dispatch) — reuse verbatim so
# the bound story/run/session line up with the published edge binding.
_STORY = "AG3-800"
_BUNDLE_IDS = {name: f"{name}-core" for name in MANDATORY_SKILLS}

# A placeholder-bearing SKILL.md: the four FK-03 placeholders + the manifest-fed
# spawn-proof, plus a story_execution QA header (role=story-qa keeps the spawn EXEMPT
# from Stage 3 so the E2E isolates Stage 2 skill_proof validation), plus the
# non-placeholder spawn tokens <STORY-ID>/<ROUND> which must survive untouched.
_PLACEHOLDER_SKILL = (
    "# Execute User Story (test bundle)\n\n"
    "owner={{gh_owner}} repo={{gh_repo}} key={{project_key}} prefix={{project_prefix}}\n\n"
    "AGENTKIT-SUBAGENT-V1 mode=story_execution role=story-qa "
    f"story_id={_STORY} skill_proof={{{{AGENT_SPAWN_SKILL_PROOF}}}}\n\n"
    "Spawn placeholders the orchestrator fills at spawn time: <STORY-ID> <ROUND>\n"
)


@pytest.fixture(autouse=True)
def _sqlite_backend(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    monkeypatch.delenv("AGENTKIT_STATE_DATABASE_URL", raising=False)
    reset_backend_cache_for_tests()
    yield
    reset_backend_cache_for_tests()


@pytest.fixture(autouse=True)
def _variant_store(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Point the SEPARATE variant store at a tmp dir (never the bundle-store root nor
    # the repo). This proves the variant lives OUTSIDE the project.
    monkeypatch.setenv(
        "AGENTKIT_MATERIALIZED_SKILL_VARIANT_STORE_ROOT", str(tmp_path / "variant-store")
    )


def _bundle_store(
    root: Path, *, placeholder_skill: str | None = "execute-userstory"
) -> SkillBundleStore:
    """Register one real on-disk bundle per mandatory skill.

    ``placeholder_skill`` (when set) receives ``_PLACEHOLDER_SKILL`` content so it is
    materialized; every other mandatory skill stays placeholder-free (raw link).
    """
    store = SkillBundleStore(store_root=root / "skill-bundles")
    for skill_name in MANDATORY_SKILLS:
        bundle_root = root / "skill-bundles" / f"{skill_name}-core" / "4.0.0"
        bundle_root.mkdir(parents=True, exist_ok=True)
        if placeholder_skill is not None and skill_name == placeholder_skill:
            content = _PLACEHOLDER_SKILL
        else:
            content = f"# {skill_name}\nno placeholders here\n"
        (bundle_root / "SKILL.md").write_text(content, encoding="utf-8")
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


def _install(root: Path, *, store: SkillBundleStore | None = None) -> SkillBundleStore:
    root.mkdir(parents=True, exist_ok=True)
    if store is None:
        store = _bundle_store(root.parent)
    result = install_agentkit(_make_config(root, store=store))
    assert result.success, result
    return store


def _materialized_header(content: str) -> str:
    """Return the story_execution header line from a materialized SKILL.md."""
    line = next(
        ln for ln in content.splitlines() if ln.startswith("AGENTKIT-SUBAGENT-V1")
    )
    return line


@pytest.mark.integration
def test_e2e_materialized_variant_through_both_bindpoints(tmp_path: Path) -> None:
    # AC1/AC2/AC4(a,b): real install materializes the placeholder-bearing skill; both
    # real bind points read placeholder-free content with the real token.
    root = tmp_path / "proj"
    _install(root)
    token = read_json_object(installed_manifest_path(root))[SKILL_PROOF_KEY]
    assert isinstance(token, str) and token

    for harness_dir in (".claude", ".codex"):
        bindpoint = root / harness_dir / "skills" / "execute-userstory"
        # The project bind point is a LINK (symlink/junction), not a copied dir.
        assert is_directory_link(bindpoint), harness_dir
        content = (bindpoint / "SKILL.md").read_text(encoding="utf-8")
        # AC2: all five placeholders resolved in the content the harness READS.
        assert "{{" not in content, harness_dir
        assert "owner=acme" in content
        assert f"key={root.stem}" in content
        assert f"prefix={root.stem.upper()}" in content
        # AC3: the story_execution header carries the REAL token, not the placeholder.
        header = _materialized_header(content)
        assert f"skill_proof={token}" in header
        # Non-placeholder spawn tokens survive untouched.
        assert "<STORY-ID>" in content
        assert "<ROUND>" in content

    # AC6 / link-only: the bind point targets the variant in the SEPARATE store, and
    # no skill source is copied into the repo.
    claude_bind = root / ".claude" / "skills" / "execute-userstory"
    variant_target = read_directory_link_target(claude_bind)
    assert "variant-store" in str(variant_target)
    assert str(root) not in str(variant_target.resolve())


@pytest.mark.integration
def test_e2e_placeholder_free_skill_stays_raw_link(tmp_path: Path) -> None:
    # AC1: a placeholder-free skill keeps the raw bundle_root link (no variant).
    root = tmp_path / "proj-raw"
    store = _bundle_store(root.parent)
    _install(root, store=store)

    # 'lookup-userstory' (placeholder-free in the fixture) links straight at its bundle.
    raw_skill = next(s for s in MANDATORY_SKILLS if s != "execute-userstory")
    bindpoint = root / ".claude" / "skills" / raw_skill
    assert is_directory_link(bindpoint)
    target = read_directory_link_target(bindpoint)
    assert "variant-store" not in str(target)
    expected_bundle = (
        root.parent / "skill-bundles" / f"{raw_skill}-core" / "4.0.0"
    ).resolve()
    assert target.resolve() == expected_bundle


@pytest.mark.integration
def test_e2e_guard_allows_authorized_blocks_forged(tmp_path: Path) -> None:
    # AC4(c,d): the real guard ALLOWS the authorized spawn whose header is read from
    # the REAL bind point, and BLOCKS a forged token — NO STUB of the guard.
    root = tmp_path / "proj"
    _install(root)
    token = read_json_object(installed_manifest_path(root))[SKILL_PROOF_KEY]
    assert isinstance(token, str)

    # Read the header THROUGH the real bind point (production read path).
    content = (
        root / ".claude" / "skills" / "execute-userstory" / "SKILL.md"
    ).read_text(encoding="utf-8")
    header = _materialized_header(content)
    assert f"skill_proof={token}" in header

    _publish_story_binding(root, str(root))

    # (c) authorized spawn -> Stage 2 proof match -> ALLOW.
    allow = _run_prompt_integrity_guard(
        _agent_event(root, description=header, prompt="qa round 1"),
        project_root=root,
    )
    assert allow.allowed is True

    # (d.1) forged token (header token != manifest token) -> BLOCK fail-closed.
    forged_header = header.replace(token, "forged-token")
    forged = _run_prompt_integrity_guard(
        _agent_event(root, description=forged_header, prompt="qa round 1"),
        project_root=root,
    )
    assert forged.allowed is False
    assert forged.message == OPAQUE_MESSAGE


@pytest.mark.integration
def test_e2e_guard_blocks_missing_manifest(tmp_path: Path) -> None:
    # (d.2) a missing manifest blocks every story_execution spawn fail-closed.
    root = tmp_path / "proj-nomanifest"
    root.mkdir(parents=True)
    _publish_story_binding(root, str(root))
    assert not installed_manifest_path(root).exists()

    header = (
        "AGENTKIT-SUBAGENT-V1 mode=story_execution role=story-qa "
        f"story_id={_STORY} skill_proof=any-token"
    )
    verdict = _run_prompt_integrity_guard(
        _agent_event(root, description=header, prompt="qa round 1"),
        project_root=root,
    )
    assert verdict.allowed is False
    assert verdict.message == OPAQUE_MESSAGE


@pytest.mark.integration
def test_e2e_reinstall_byte_identical_variant(tmp_path: Path) -> None:
    # AC5 (FK-51): re-install of the SAME project -> byte-identical variant under the
    # same digest dir; the token + linked content stay stable.
    root = tmp_path / "proj-idem"
    store = _bundle_store(root.parent)
    _install(root, store=store)

    claude_bind = root / ".claude" / "skills" / "execute-userstory"
    variant_dir_first = read_directory_link_target(claude_bind).resolve()
    first_bytes = (variant_dir_first / "SKILL.md").read_bytes()
    token_first = read_json_object(installed_manifest_path(root))[SKILL_PROOF_KEY]

    # Re-install (same config + same token via AG3-110 stability).
    assert install_agentkit(_make_config(root, store=store)).success
    variant_dir_second = read_directory_link_target(claude_bind).resolve()
    second_bytes = (variant_dir_second / "SKILL.md").read_bytes()
    token_second = read_json_object(installed_manifest_path(root))[SKILL_PROOF_KEY]

    assert variant_dir_second == variant_dir_first  # same digest dir
    assert second_bytes == first_bytes  # byte-identical
    assert token_second == token_first  # token stable


# ---------------------------------------------------------------------------
# Real-bundle assertions (ERROR 2 fix — Codex gap: the synthetic bundle above
# never exercises the SHIPPED execute-userstory-core/4.0.0 bundle).
# ---------------------------------------------------------------------------

#: Matches a SCALAR placeholder token ``{{<word>}}`` — an identifier immediately
#: inside double braces.  Block/section directives ``{{#...}}``, ``{{/...}}``,
#: ``{{^...}}`` are NOT matched here; they are a different mechanism with a
#: different owner (conditional-section rendering / prompt-runtime FK-44) and
#: are explicitly excepted from the AG3-111 "no literal {{...}}" criterion
#: (FK-43 §43.4.2 mandates "einfaches String-Replace, keine Template-Engine";
#: the substitutor CANNOT and MUST NOT resolve them — AG3-113 vocabulary test
#: also excepts ``{{#...}}``, consistent with this decision).
_SCALAR_PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}")


def _real_bundle_store_for(root: Path) -> SkillBundleStore:
    """Register the REAL shipped bundles, using the live on-disk resources.

    ``execute-userstory-core/4.0.0`` is the only bundle that carries scalar
    placeholders in the shipped tree; all others are registered from the same
    shipped root so the installer satisfies MANDATORY_SKILLS without synthetic
    fixtures.
    """
    shipped = shipped_skill_bundles_root()
    store = SkillBundleStore(store_root=root / "skill-bundles")
    for skill_name in MANDATORY_SKILLS:
        bundle_id = f"{skill_name}-core"
        bundle_root = shipped / bundle_id / "4.0.0"
        manifest_info = read_json_object(bundle_root / "manifest.json")
        store.register_bundle(
            SkillBundle(
                bundle_id=bundle_id,
                bundle_version="4.0.0",
                bundle_root=bundle_root,
                manifest_digest=str(manifest_info.get("manifest_digest", "0" * 64)),
            )
        )
    return store


def _real_bundle_install_config(root: Path, *, store: SkillBundleStore) -> InstallConfig:
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


@pytest.mark.integration
def test_e2e_real_bundle_scalar_placeholders_resolved_at_both_bindpoints(
    tmp_path: Path,
) -> None:
    """Real ``execute-userstory-core/4.0.0`` bundle: all scalar ``{{word}}`` tokens
    resolved through BOTH harness bind points; block/section directives retained.

    Closes the Codex review gap: the synthetic-bundle E2E above never exercises the
    SHIPPED bundle.  This test:

    - materializes the REAL on-disk ``execute-userstory-core/4.0.0`` through the REAL
      installer (no synthetic SKILL.md);
    - reads ``SKILL.md`` through BOTH ``.claude/skills/...`` AND ``.codex/skills/...``
      bind points (the real harness read path);
    - asserts every SCALAR ``{{word}}`` token is resolved (regex sweep — no
      ``{{<identifier>}}`` survives);
    - asserts that the deliberate block directive ``{{#IF_CLARIFICATION_ANSWERS}}`` is
      STILL PRESENT, because block/section directives are NOT substitution placeholders
      (FK-43 §43.4.2 "einfaches String-Replace, keine Template-Engine"; owner:
      conditional-section rendering / prompt-runtime FK-44; AG3-111 §2.2 scopes this
      OUT); AG3-111 resolves only the five SCALAR placeholders;
    - asserts the story_execution spawn header carries the REAL ``agent_spawn_skill_proof``
      token from ``.installed-manifest.json``;
    - asserts the real AG3-086 guard Stage 2 ALLOWS the authorized spawn (token match)
      and BLOCKS a forged token (no mocks of substitutor / manifest / guard).
    """
    root = tmp_path / "real-bundle-proj"
    root.mkdir(parents=True, exist_ok=True)
    store = _real_bundle_store_for(root.parent)
    result = install_agentkit(_real_bundle_install_config(root, store=store))
    assert result.success, result

    token = read_json_object(installed_manifest_path(root))[SKILL_PROOF_KEY]
    assert isinstance(token, str) and token

    # Read through BOTH real harness bind points (production read path).
    for harness_dir in (".claude", ".codex"):
        bindpoint = root / harness_dir / "skills" / "execute-userstory"
        assert is_directory_link(bindpoint), f"{harness_dir} bind point is not a link"
        content = (bindpoint / "SKILL.md").read_text(encoding="utf-8")

        # --- Scalar placeholder sweep ---
        # Every SCALAR ``{{<identifier>}}`` token must be resolved.  The regex
        # ``\{\{(\w+)\}\}`` matches ``{{word}}`` — it does NOT match block
        # directives like ``{{#IF_CLARIFICATION_ANSWERS}}`` (those start with ``#``
        # which is not a ``\w`` character), so the check is correctly scoped.
        remaining_scalar = _SCALAR_PLACEHOLDER_RE.findall(content)
        assert not remaining_scalar, (
            f"{harness_dir}: unresolved scalar placeholders found: {remaining_scalar}"
        )

        # The five substituted FK-03 + manifest-fed tokens.
        assert "{{AGENT_SPAWN_SKILL_PROOF}}" not in content
        assert "{{project_prefix}}" not in content
        assert f"{root.stem.upper()}-" in content or f"prefix={root.stem.upper()}" not in content  # project_prefix value woven in
        assert token in content, f"{harness_dir}: real token not found in content"

        # --- Block/section directives must be RETAINED (NOT substitution placeholders).
        # ``{{#IF_CLARIFICATION_ANSWERS}}`` is a prompt-runtime / FK-44 conditional-
        # section construct; the substitutor is "einfaches String-Replace, keine
        # Template-Engine" (FK-43 §43.4.2) and MUST NOT resolve it.
        assert "{{#IF_CLARIFICATION_ANSWERS}}" in content, (
            f"{harness_dir}: block directive {{{{#IF_CLARIFICATION_ANSWERS}}}} was "
            "incorrectly removed — it must be retained (FK-43 §43.4.2, AG3-111 §2.2)"
        )

        # The story_execution spawn headers in the real SKILL.md appear inside
        # description strings in code blocks, e.g.:
        #   description: "AGENTKIT-SUBAGENT-V1 mode=story_execution ... skill_proof=<token>\n..."
        # After substitution the token is embedded in those strings. We verify the
        # token appears in the content (proven above), and that every line that
        # contains a story_execution spawn header now embeds the real token (not the
        # placeholder literal).
        story_exec_lines = [
            ln for ln in content.splitlines()
            if "AGENTKIT-SUBAGENT-V1" in ln and "mode=story_execution" in ln
        ]
        assert story_exec_lines, f"{harness_dir}: no story_execution spawn reference found"
        assert all(f"skill_proof={token}" in ln or "skill_proof={{" not in ln
                   for ln in story_exec_lines), (
            f"{harness_dir}: at least one story_execution line still has a literal placeholder"
        )

    # --- AG3-086 guard: ALLOW authorized, BLOCK forged (NO stub of guard/manifest).
    # The guard validates the description field of an Agent() call.  Build a clean
    # header string in the canonical format the orchestrator would use at spawn time:
    # the real SKILL.md mandates exactly this format with the substituted token.
    _publish_story_binding(root, str(root))

    # Use role=story-qa so Stage 3 (template_integrity) is skipped — this
    # E2E isolates Stage 2 skill_proof validation, identical to the existing
    # test_e2e_guard_allows_authorized_blocks_forged approach.
    authorized_header = (
        f"AGENTKIT-SUBAGENT-V1 mode=story_execution role=story-qa "
        f"story_id={_STORY} skill_proof={token}"
    )

    allow = _run_prompt_integrity_guard(
        _agent_event(root, description=authorized_header, prompt="worker round 1"),
        project_root=root,
    )
    assert allow.allowed is True, f"guard blocked an authorized spawn: {allow}"

    forged_header = authorized_header.replace(token, "forged-real-bundle-token")
    forged = _run_prompt_integrity_guard(
        _agent_event(root, description=forged_header, prompt="worker round 1"),
        project_root=root,
    )
    assert forged.allowed is False
    assert forged.message == OPAQUE_MESSAGE
