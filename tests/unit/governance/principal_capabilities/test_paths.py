"""Unit tests for PathClass enum + PathClassifier (FK-55 §55.4/§55.7.1/§55.10.2, AK3)."""

from __future__ import annotations

from pathlib import Path

from agentkit.backend.governance.principal_capabilities import PathClass, PathClassifier

_ROOT = Path("/repo")
_STORY = "AG3-001"
#: A real worktree root for the active story (FK-55 §55.7.1 story scope).
_WORKTREE = "/work/wt-AG3-001"
_SCOPE_ROOTS = (_WORKTREE,)
_CLF = PathClassifier()


def _classify(path: str) -> PathClass | None:
    return _CLF.classify(path, _ROOT, _STORY, _SCOPE_ROOTS)


def test_pathclass_has_exactly_eight_canonical_values() -> None:
    # AK3: FK-55 §55.4 defines exactly 8 path classes — no synthetic 9th
    # UNCLASSIFIED wire value (the unclassified sentinel is the None return).
    assert len(PathClass) == 8
    assert {p.value for p in PathClass} == {
        "codebase_story_scope",
        "codebase_out_of_scope",
        "qa_sandbox",
        "control_plane",
        "content_plane",
        "governance_plane",
        "git_internal",
        "repo_admin_surface",
    }


def test_git_internal() -> None:
    assert _classify("/repo/.git/config") is PathClass.GIT_INTERNAL


def test_governance_plane_agentkit_and_temp() -> None:
    assert _classify("/repo/.agentkit/governance/freeze.json") is (
        PathClass.GOVERNANCE_PLANE
    )
    assert _classify("_temp/governance/locks/x.json") is PathClass.GOVERNANCE_PLANE
    assert _classify("/repo/.agent-guard/lock.json") is PathClass.GOVERNANCE_PLANE


def test_governance_plane_self_protection_hook_settings() -> None:
    # AG3-033 / FK-30 §30.5.4 + FK-55 §55.4 (Guardrail-Zustaende → governance_plane):
    # harness hook-settings classify as governance_plane so the capability matrix
    # makes a coherent decision (worker DENY, official principals ALLOW) instead
    # of UNCLASSIFIED_MUTATION hard-blocking ALL principals.
    assert _classify(".claude/settings.json") is PathClass.GOVERNANCE_PLANE
    assert _classify(".codex/config.toml") is PathClass.GOVERNANCE_PLANE
    assert _classify(".codex/hooks.json") is PathClass.GOVERNANCE_PLANE


def test_governance_plane_self_protection_config_and_manifest() -> None:
    # FK-30 §30.5.4: governance config + installer manifest.
    assert _classify(".agentkit/config/project.yaml") is PathClass.GOVERNANCE_PLANE
    assert _classify(".installed-manifest.json") is PathClass.GOVERNANCE_PLANE


def test_governance_plane_self_protection_symlink_dirs() -> None:
    # FK-30 §30.5.4 / FK-15 §15.7.1: CCAG-rule + skill-symlink dirs (any path
    # UNDER them) classify as governance_plane.
    assert _classify(".agentkit/ccag/rules/subagents.yaml") is (
        PathClass.GOVERNANCE_PLANE
    )
    assert _classify(".claude/ccag/rules/subagents.yaml") is PathClass.GOVERNANCE_PLANE
    assert _classify(".claude/skills/create-userstory/SKILL.md") is (
        PathClass.GOVERNANCE_PLANE
    )


def test_self_protection_classification_is_precise_not_over_broad() -> None:
    # AG3-033 (over-classification guard): only the SPECIFIC protected files/dirs
    # are governance_plane. Arbitrary harness working files under .claude/.codex
    # must NOT be swept in — they stay unclassified (None sentinel), exactly as
    # before the AG3-033 change. Over-classifying would lock down legitimate
    # harness working files.
    assert _classify(".claude/other.json") is None
    assert _classify(".codex/scratch.txt") is None
    assert _classify(".claude/settings.local.json") is None
    assert _classify(".agentkit/config/other.yaml") is None
    # A skill-like name OUTSIDE the protected skills dir is not protected.
    assert _classify("docs/skills/notes.md") is None


def test_qa_sandbox() -> None:
    assert _classify(f"_temp/adversarial/{_STORY}/probe.py") is PathClass.QA_SANDBOX


def test_repo_admin_surface() -> None:
    assert _classify(f"stories/{_STORY}/status.yaml") is PathClass.REPO_ADMIN_SURFACE


def test_content_plane() -> None:
    assert _classify(f"var/{_STORY}/context.json") is PathClass.CONTENT_PLANE


def test_control_plane() -> None:
    assert _classify("var/phase_state_projection.json") is PathClass.CONTROL_PLANE


def test_codebase_story_scope_from_worktree_root() -> None:
    # FK-55 §55.7.1: story scope = under a participating worktree root. A real
    # worktree path WITHOUT the story id in it must classify in-scope.
    assert _classify(f"{_WORKTREE}/src/module.py") is PathClass.CODEBASE_STORY_SCOPE


def test_codebase_story_scope_from_project_local_story_dir() -> None:
    # FK-55 §55.7.1 item 2: project-local story working dir.
    assert _classify(f"/repo/{_STORY}/src/module.py") is (
        PathClass.CODEBASE_STORY_SCOPE
    )


def test_arbitrary_path_containing_id_is_not_in_scope() -> None:
    # FK-55 §55.7.1 (ERROR 3): a path that merely CONTAINS the story id as a
    # segment but is not under a bound scope root must NOT be in story scope.
    # ``src`` makes it productive → out-of-scope, not story-scope.
    assert _CLF.classify(f"src/{_STORY}/m.py", _ROOT, _STORY, _SCOPE_ROOTS) is (
        PathClass.CODEBASE_OUT_OF_SCOPE
    )


def test_codebase_out_of_scope() -> None:
    # Productive code with no story scope root match.
    assert _classify("src/other/module.py") is PathClass.CODEBASE_OUT_OF_SCOPE


def test_unclassified_is_none_sentinel() -> None:
    # ERROR 1: an unclassifiable target returns the None sentinel (no 9th enum
    # value); the enforcement turns this into a fail-closed BLOCK (FK-55 §55.10.2).
    assert _classify("README.md") is None


def test_windows_separators_classify_identically() -> None:
    # FK-55 §55.10.2: cheap normalization tolerates OS separators (Win dev vs
    # Linux CI must classify the same).
    assert _CLF.classify(r"\repo\.git\index", _ROOT, _STORY, _SCOPE_ROOTS) is (
        PathClass.GIT_INTERNAL
    )


def test_no_story_id_means_no_story_scope() -> None:
    # Without a bound story id there is no story scope (FK-55 §55.7.1).
    assert _CLF.classify(f"{_WORKTREE}/src/m.py", _ROOT, None, None) is (
        PathClass.CODEBASE_OUT_OF_SCOPE
    )


def test_all_eight_pathclasses_reachable() -> None:
    # AK3: every PathClass value is reachable from the classifier.
    reached = {
        _classify("/repo/.git/x"),
        _classify("/repo/.agentkit/governance/freeze.json"),
        _classify(f"_temp/adversarial/{_STORY}/p.py"),
        _classify(f"stories/{_STORY}/status.yaml"),
        _classify(f"var/{_STORY}/context.json"),
        _classify("var/phase_state_projection.json"),
        _classify(f"{_WORKTREE}/src/m.py"),
        _classify("src/other/m.py"),
    }
    assert reached == set(PathClass)
