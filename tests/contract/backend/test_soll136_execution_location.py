"""SOLL-136 execution-location conformance proof (AG3-145 Teilschritt E / AC11).

The grep-proof "review artifact" the story requires: after AG3-145 the backend is
no longer the physical worktree actor (FK-10 §10.2.4a). This test proves, over the
ACTUAL backend sources, that

1. the backend git/worktree call-sites AG3-145 MOVED onto the Project Edge are
   GONE (``create_worktree`` / ``branch_exists`` primitives removed from
   ``utils.git``; the ``StateBackendWorktreeRepository`` path authority and the
   backend setup ``worktree.py`` deleted; the reset-detach + governance
   deactivation no longer call ``remove_worktree`` / write into worktrees), and
2. the REMAINING backend git call-sites are EXACTLY the ones the story's
   "Ausführungsort-Inventar" assigns to the neighbour stories -- the AG3-152
   closure/merge block (``remove_worktree`` / ``tree_hash_of_commit`` primitives)
   and the AG3-147 push/QA-evidence block. There is NO unassigned finding.

This is a pure source-scan (no imports of the scanned modules), so it stays a
deterministic conformance gate independent of runtime wiring.
"""

from __future__ import annotations

from pathlib import Path

import agentkit.backend as _backend_pkg

_BACKEND_ROOT = Path(_backend_pkg.__file__).parent


def _backend_py_files() -> list[Path]:
    return sorted(_BACKEND_ROOT.rglob("*.py"))


def _rel(path: Path) -> str:
    return path.relative_to(_BACKEND_ROOT).as_posix()


# ---------------------------------------------------------------------------
# Ausführungsort-Inventar (SOLL-136): the remaining backend git call-sites and
# the neighbour story that OWNS each. Encoded verbatim from the story table so
# the mapping is the reviewable artifact.
# ---------------------------------------------------------------------------

#: The utils.git worktree/tree-hash primitives the AG3-152 closure/merge block
#: still consumes on the backend -- the ONLY sanctioned backend importers of
#: ``agentkit.backend.utils.git`` after this story.
_UTILS_GIT_REMAINING_CONSUMERS: dict[str, str] = {
    "closure/multi_repo_saga.py": "AG3-152",  # remove_worktree (teardown_worktrees)
    "verify_system/pre_merge_runner/scan_runner.py": "AG3-152",  # tree_hash_of_commit
}

#: Files that legitimately call ``remove_worktree`` after this story -- the
#: AG3-152 closure teardown + its duck-type backend check. The reset-detach and
#: setup-failure cleanup no longer appear here (they commission a
#: ``teardown_worktree`` edge command instead).
_REMOVE_WORKTREE_CALLERS: dict[str, str] = {
    "utils/git.py": "primitive-definition",
    "closure/multi_repo_saga.py": "AG3-152",
    "closure/phase.py": "AG3-152",  # hasattr(backend, "remove_worktree") duck check
}


# ---------------------------------------------------------------------------
# (1) Moved surfaces are GONE
# ---------------------------------------------------------------------------


def test_utils_git_no_longer_defines_worktree_provisioning_primitives() -> None:
    """``create_worktree`` / ``branch_exists`` were removed from ``utils.git``."""
    source = (_BACKEND_ROOT / "utils" / "git.py").read_text(encoding="utf-8")
    assert "def create_worktree(" not in source
    assert "def branch_exists(" not in source
    # The AG3-152 primitives it still owns are retained.
    assert "def remove_worktree(" in source
    assert "def tree_hash_of_commit(" in source


def test_state_backend_worktree_repository_is_deleted() -> None:
    """The backend worktree PATH-authority module is gone (FK-10 §10.2.4a)."""
    assert not (
        _BACKEND_ROOT / "state_backend" / "store" / "worktree_repository.py"
    ).exists()
    hits = [
        _rel(p)
        for p in _backend_py_files()
        if "StateBackendWorktreeRepository" in p.read_text(encoding="utf-8")
    ]
    assert hits == [], f"StateBackendWorktreeRepository still referenced in {hits}"


def test_backend_setup_worktree_module_is_deleted() -> None:
    """The backend setup ``worktree.py`` (create/marker) is gone (Teilschritt C)."""
    assert not (
        _BACKEND_ROOT / "governance" / "setup_preflight_gate" / "worktree.py"
    ).exists()


def test_write_story_marker_has_no_backend_definition() -> None:
    """``write_story_marker`` is materialized dev-locally by the edge, not backend."""
    hits = [
        _rel(p)
        for p in _backend_py_files()
        if "def write_story_marker(" in p.read_text(encoding="utf-8")
    ]
    assert hits == [], f"backend still defines write_story_marker in {hits}"


def test_governance_deactivation_has_no_worktree_agent_guard_write() -> None:
    """Governance deactivation no longer writes ``.agent-guard`` into worktrees."""
    source = (_BACKEND_ROOT / "governance" / "runner.py").read_text(encoding="utf-8")
    # The removed per-worktree physical projection wrote these two files.
    assert '.agent-guard" / "lock.json"' not in source
    assert '.agent-guard" / "mode.json"' not in source
    assert "list_worktree_paths" not in source


# ---------------------------------------------------------------------------
# (2) Remaining backend git call-sites == exactly the neighbour-story inventory
# ---------------------------------------------------------------------------


def test_utils_git_importers_are_exactly_the_ag3152_consumers() -> None:
    """Only the AG3-152 closure/merge primitives still import ``utils.git``."""
    importers = {
        _rel(p)
        for p in _backend_py_files()
        if p.name != "git.py"
        and "agentkit.backend.utils.git" in p.read_text(encoding="utf-8")
    }
    assert importers == set(_UTILS_GIT_REMAINING_CONSUMERS), (
        "backend utils.git importers drifted from the SOLL-136 inventory: "
        f"actual={sorted(importers)} expected={sorted(_UTILS_GIT_REMAINING_CONSUMERS)}"
    )
    # Every remaining importer is assigned to a neighbour story (no unassigned).
    assert all(
        _UTILS_GIT_REMAINING_CONSUMERS[i] == "AG3-152" for i in importers
    )


def test_remove_worktree_callers_are_only_the_ag3152_closure_block() -> None:
    """The reset-detach + setup cleanup no longer call ``remove_worktree``."""
    callers = {
        _rel(p)
        for p in _backend_py_files()
        if "remove_worktree" in p.read_text(encoding="utf-8")
    }
    assert callers == set(_REMOVE_WORKTREE_CALLERS), (
        "backend remove_worktree call-sites drifted from the SOLL-136 inventory: "
        f"actual={sorted(callers)} expected={sorted(_REMOVE_WORKTREE_CALLERS)}"
    )
    # The bootstrap reset adapter is NOT among them (it commissions the edge).
    assert "bootstrap/story_reset_adapters.py" not in callers


def test_inventory_neighbour_sites_still_exist() -> None:
    """The neighbour-owned git call-sites are intact (moved-not-deleted proof)."""
    for rel_path in _UTILS_GIT_REMAINING_CONSUMERS:
        assert (_BACKEND_ROOT / rel_path).exists(), rel_path
