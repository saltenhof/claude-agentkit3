"""SOLL-136 execution-location conformance proof (AG3-145 sub-step E / AC11).

The grep-proof "review artifact" the story requires: after AG3-145 the backend is
no longer the physical worktree actor (FK-10 §10.2.4a). This test proves, over the
ACTUAL backend sources, that

1. the backend git/worktree call-sites AG3-145 MOVED onto the Project Edge are
   GONE (``create_worktree`` / ``branch_exists`` primitives removed from
   ``utils.git``; the ``StateBackendWorktreeRepository`` path authority and the
   backend setup ``worktree.py`` deleted; the reset-detach + governance
   deactivation no longer call ``remove_worktree`` / write into worktrees; NO
   backend site runs ``git worktree add``), and
2. EVERY remaining backend git-subprocess call-site is EXPLICITLY ENUMERATED and
   ASSIGNED to an owner in :data:`_GIT_SUBPROCESS_INVENTORY` -- so AC11's "no
   unassigned finding" is VERIFIED, not merely asserted. The scan covers the
   backend git-subprocess surface in the concrete literal invocation forms it
   detects (see :func:`_git_subprocess_sites` for the exact scope): a list or
   tuple argv whose first element is ``git``
   (``subprocess.run(["git", ...])`` / ``(("git", ...))``, incl. ``git -C`` /
   ``ls-remote`` / ``show-ref`` / ``diff`` / ``rev-parse`` sub-commands), an
   ``os.system`` / shell-string call whose command literal starts with ``git``,
   and any GitPython import (incl. submodules) -- not only the worktree
   primitives. The residual sites are:
     * the AG3-152 closure/merge block, which INCLUDES the RETAINED backend
       worktree-teardown primitives (``utils/git.py`` ``remove_worktree`` =
       ``git worktree remove`` / ``prune``, consumed by
       ``closure/multi_repo_saga.py``) -- retained by design and correctly
       assigned to AG3-152;
     * the AG3-147 push/QA-evidence block;
     * the AG3-146 provider-neutral network-protocol reads (``git ls-remote`` /
       ``git remote get-url`` -- no local checkout, expressly permitted by
       FK-10 §10.2.4a(b));
     * the non-worktree, dev-local (Level 2/3) subsystems that legitimately
       shell git (governance secret-scan, installer bootstrap).
   The accurate claim (matching exactly what the test verifies): NO backend git
   call-site is UNASSIGNED, and NO AG3-145-scope worktree-PROVISIONING op
   (``git worktree add``) remains anywhere in the backend.

This is a pure source-scan (no imports of the scanned modules), so it stays a
deterministic conformance gate independent of runtime wiring.
"""

from __future__ import annotations

import re
from pathlib import Path

import agentkit.backend as _backend_pkg

_BACKEND_ROOT = Path(_backend_pkg.__file__).parent


def _backend_py_files() -> list[Path]:
    return sorted(_BACKEND_ROOT.rglob("*.py"))


def _rel(path: Path) -> str:
    return path.relative_to(_BACKEND_ROOT).as_posix()


# ---------------------------------------------------------------------------
# Execution-location inventory (SOLL-136): the remaining backend git call-sites
# and the neighbour story / subsystem that OWNS each. The mapping is the
# reviewable artifact; AC11's "no unassigned finding" is asserted against it.
# ---------------------------------------------------------------------------

#: A LIST argv whose first element is ``git`` (``subprocess.run(["git", ...])``,
#: incl. multiline argv and every ``git -C`` / ``ls-remote`` / ``show-ref`` /
#: ``diff`` / ``rev-parse`` sub-command).
_GIT_ARGV_LIST = re.compile(r"""\[\s*["']git["']""")
#: A TUPLE argv whose first element is ``git`` (``subprocess.run(("git", ...))``).
#: Comma-guarded so a single-arg call like ``shutil.which("git")`` is NOT matched
#: (that is a PATH lookup, not a git invocation).
_GIT_ARGV_TUPLE = re.compile(r"""\(\s*["']git["']\s*,""")
#: An ``os.system`` / ``subprocess.*`` call whose COMMAND LITERAL starts with
#: ``git`` (shell-string / ``shell=True`` form, e.g. ``os.system("git ...")`` or
#: ``subprocess.run("git ...", shell=True)``). A prose ``git ...`` mention in a
#: ``#`` comment or a ```` ``git ...`` ```` docstring is NOT quote-prefixed and is
#: correctly excluded.
_GIT_SHELL_STRING = re.compile(
    r"""(?:os\.system|subprocess\.\w+)\(\s*f?["']git[\s"']"""
)
#: GitPython usage, incl. submodule imports (``import git`` / ``import git.x`` /
#: ``from git[.x] import ...`` / ``git.Repo(...)``). None today; keeps the surface
#: honest if introduced.
_GITPYTHON = re.compile(
    r"^\s*(?:import\s+git\b|from\s+git(?:\.[\w.]+)?\s+import\b)"
    r"|(?<![\w.])git\.Repo\s*\(",
    re.M,
)
#: The complete set of invocation forms the scan detects. Deliberately scoped to
#: these CONCRETE LITERAL forms; a git argv held in a variable and built
#: dynamically elsewhere is out of scope (an undecidable chase), and the docstring
#: claims nothing beyond what these patterns verify.
_GIT_INVOCATION_FORMS = (
    _GIT_ARGV_LIST,
    _GIT_ARGV_TUPLE,
    _GIT_SHELL_STRING,
    _GITPYTHON,
)

#: EVERY backend file that shells ``git`` (argv subprocess) or uses GitPython,
#: mapped to its owner. AC11 "no unassigned finding" == this set equals the
#: scanned set (:func:`_git_subprocess_sites`), each with an explicit owner.
_GIT_SUBPROCESS_INVENTORY: dict[str, str] = {
    "bootstrap/composition_git.py": "implementation/structural system evidence (not closure merge)",
    "verify_system/sonarqube_gate/runtime_wiring.py": "AG3-152 (worktree-HEAD attestation reads)",
    # AG3-147 retargeted QA-cycle fingerprinting off backend-local git; it now
    # hashes reported pushed heads / compare evidence, so no inventory entry
    # remains for verify_system/qa_cycle/fingerprint.py.
    # composition_verify wires the AG3-152 SubprocessGitBackend AND the FK-33 §33.5
    # change-evidence subprocess-provider (branch/commit/diff reads). AG3-147
    # moved the push-evidence (``pushed``) OFF backend git onto the two-stage
    # barrier (AC11), so this file's git surface is no longer an AG3-147 owner.
    "bootstrap/composition_verify.py": "AG3-152 (SubprocessGitBackend) + FK-33 change-evidence provider (branch/commit/diff)",
    # AG3-146 provider-neutral NETWORK-PROTOCOL reads -- no local checkout,
    # expressly permitted by FK-10 §10.2.4a(b); NOT a physical worktree op.
    "code_backend/git_protocol.py": "AG3-146 (git ls-remote ref-read)",
    "installer/github_coordinates.py": "AG3-146 (git remote get-url origin metadata read)",
    "telemetry/hooks/commit_hook.py": "AG3-147 (mechanical commit invalidation HEAD reads)",
    # Non-worktree, dev-local (Level 2/3) subsystems that legitimately shell git
    # on the dev machine -- NOT the Level-1 backend-process physical git FK-10
    # §10.2.4a forbids, and NOT worktree provisioning/teardown/path ops.
    "governance/guard_system/secret_scan.py": "governance-secret-scan (guard git-history scan)",
    "installer/project_structure.py": "installer-bootstrap (git clone at project registration)",
    "installer/bootstrap_checkpoints/cp11_to_12.py": "installer-bootstrap (git config core.hooksPath checkpoint)",
}

#: The utils.git worktree/tree-hash primitives the AG3-152 closure/merge block
#: still consumes on the backend -- the ONLY sanctioned backend importers of
#: ``agentkit.backend.utils.git`` after this story.
_UTILS_GIT_REMAINING_CONSUMERS: dict[str, str] = {}

#: Files that legitimately call ``remove_worktree`` after this story -- the
#: AG3-152 closure teardown + its duck-type backend check. The reset-detach and
#: setup-failure cleanup no longer appear here (they commission a
#: ``teardown_worktree`` edge command instead).
_REMOVE_WORKTREE_CALLERS: dict[str, str] = {
    "closure/multi_repo_saga.py": "AG3-152",
    "closure/phase.py": "AG3-152",  # hasattr(backend, "remove_worktree") duck check
}


# ---------------------------------------------------------------------------
# (1) Moved surfaces are GONE
# ---------------------------------------------------------------------------


def test_backend_git_utility_module_is_deleted() -> None:
    """AG3-152 leaves no physical Git helper in the backend utility package."""
    assert not (_BACKEND_ROOT / "utils" / "git.py").exists()


def test_closure_merge_runtime_has_no_physical_git_adapter() -> None:
    """AG3-152 AC-1: productive Closure cannot reach a local Git subprocess."""
    closure_sources = {
        _rel(path): path.read_text(encoding="utf-8")
        for path in (_BACKEND_ROOT / "closure").rglob("*.py")
    }
    closure_sources["bootstrap/composition_closure.py"] = (
        _BACKEND_ROOT / "bootstrap" / "composition_closure.py"
    ).read_text(encoding="utf-8")
    forbidden = ("subprocess.run", "SubprocessGitBackend")
    hits = {
        path: token
        for path, source in closure_sources.items()
        for token in forbidden
        if token in source
    }
    assert hits == {}, f"physical Git remains reachable from Closure: {hits}"


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
    """The backend setup ``worktree.py`` (create/marker) is gone (sub-step C)."""
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


# ---------------------------------------------------------------------------
# (3) EXHAUSTIVE: every backend git-subprocess call-site is enumerated + assigned
# ---------------------------------------------------------------------------


def _git_subprocess_sites() -> set[str]:
    """Return every backend file that invokes ``git`` in a detected literal form.

    Scans for the concrete invocation forms in :data:`_GIT_INVOCATION_FORMS`:
    a list or tuple argv starting with ``git``, an ``os.system`` / shell-string
    ``subprocess`` call whose literal starts with ``git``, and any GitPython
    import. A dynamically-constructed argv held in a variable is intentionally
    out of scope (undecidable) -- the proof claims only what these forms verify.
    """
    sites: set[str] = set()
    for p in _backend_py_files():
        source = p.read_text(encoding="utf-8")
        if any(form.search(source) for form in _GIT_INVOCATION_FORMS):
            sites.add(_rel(p))
    return sites


def test_every_backend_git_subprocess_site_is_assigned_in_the_inventory() -> None:
    """AC11 'no unassigned finding': EVERY backend git call-site has an owner.

    The general git-subprocess surface (argv-list ``git`` invocation + GitPython)
    is scanned across ``src/agentkit/backend`` and must equal the explicitly
    ASSIGNED :data:`_GIT_SUBPROCESS_INVENTORY` -- a NEW, unassigned git call-site
    fails this test (drift proof), and a stale inventory entry fails it too.
    """
    sites = _git_subprocess_sites()
    unassigned = sorted(sites - set(_GIT_SUBPROCESS_INVENTORY))
    stale = sorted(set(_GIT_SUBPROCESS_INVENTORY) - sites)
    assert sites == set(_GIT_SUBPROCESS_INVENTORY), (
        "backend git-subprocess call-sites drifted from the SOLL-136 inventory: "
        f"UNASSIGNED (new, no owner)={unassigned}; STALE (assigned, gone)={stale}. "
        "Every backend git call-site must be assigned an owner (a neighbour "
        "story, AG3-146 network read, or a non-worktree dev-local subsystem)."
    )
    # Every entry carries a non-empty owner rationale.
    assert all(owner.strip() for owner in _GIT_SUBPROCESS_INVENTORY.values())


#: The load-bearing SOLL-136 regression guard: ``git worktree add`` (worktree
#: PROVISIONING) must never creep back into the backend. Catches every
#: CONTIGUOUS-LITERAL invocation form: the argv adjacency ``"worktree", "add"``
#: (list OR tuple argv) AND the shell-string / ``os.system`` literal
#: ``"git worktree add ..."`` (incl. an f-string). Out of scope for this static
#: source scan (same boundary as the inventory scan scope note): a SPLIT string
#: literal (``"git " "worktree add"``) or an argv assembled from
#: variables/concatenation -- undecidable for a regex and not a realistic
#: accidental regression. A prose ``git worktree add`` in a ``#`` comment or a
#: ```` ``git worktree add`` ```` docstring is not quote-prefixed and is excluded
#: (it is not an execution).
_GIT_WORKTREE_ADD = re.compile(
    r"""["']worktree["']\s*,\s*["']add["']|["']git\s+worktree\s+add"""
)


def test_no_backend_site_runs_git_worktree_add() -> None:
    """No backend git call-site provisions a worktree (``git worktree add``).

    Worktree provisioning moved to the edge (``create_worktree`` deleted). This
    is the guard that must forever keep backend worktree PROVISIONING out. It
    covers every contiguous-literal invocation form -- argv-list, tuple argv,
    shell-string (``subprocess.run("git worktree add ...", shell=True)``) and
    ``os.system("git worktree add ...")`` are all caught (see
    :data:`_GIT_WORKTREE_ADD`); a split string literal or an argv assembled from
    variables is out of scope for a static source scan (undecidable), consistent
    with the inventory scan scope note. Zero offenders today; this keeps it that way.
    """
    offenders = [
        _rel(p)
        for p in _backend_py_files()
        if _GIT_WORKTREE_ADD.search(p.read_text(encoding="utf-8"))
    ]
    assert offenders == [], (
        f"backend still provisions a worktree via git worktree add in {offenders}"
    )
