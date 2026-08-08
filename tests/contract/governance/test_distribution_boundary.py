"""The governance distribution boundary, pinned as a property (AG3-239).

These are not signature pins. They are the architectural invariants the AG3-239
symbol cut established, expressed so that a later change that re-mixes the two
distributions fails here instead of being discovered by the next measurement.

The rule they enforce (FK-01 section 1.1a, FK-10 section 10.1.0 I1): the guard
engine decides synchronously inside the short-lived hook process on the developer
machine; canonical state and its repositories belong to the core; and no module
may hold symbols of both sides at once.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_GOVERNANCE = Path(__file__).resolve().parents[3] / "src" / "agentkit" / "backend" / "governance"
_RUNNER = _GOVERNANCE / "runner.py"
_ADMINISTRATION = _GOVERNANCE / "administration.py"
_INIT = _GOVERNANCE / "__init__.py"

#: Repository types that own canonical state. A module of the hook process must
#: not name any of them -- naming one is how a database reaches the laptop.
_CANONICAL_REPOSITORIES = frozenset(
    {
        "FreezeRepository",
        "HookRegistrationRepository",
        "LockRecordRepository",
        "StateBackendHookRegistrationRepository",
    }
)


def _imported_names(path: Path) -> set[str]:
    """Return every name the module binds through an import, at any nesting."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import | ast.ImportFrom):
            names.update(alias.asname or alias.name for alias in node.names)
    return names


def _module_level_symbols(path: Path) -> set[str]:
    """Return the classes and functions the module itself defines."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.name
        for node in tree.body
        if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
    }


@pytest.mark.contract
class TestHookDispatcherHoldsNoCanonicalRepository:
    """The hook process must not be able to reach a repository at all."""

    def test_runner_names_no_canonical_repository(self) -> None:
        leaked = _imported_names(_RUNNER) & _CANONICAL_REPOSITORIES
        assert leaked == set(), (
            f"{_RUNNER.name} imports canonical repositories {sorted(leaked)}. "
            "The hook process runs on the developer machine and reaches the core "
            "only over /v1 (FK-10 section 10.1.0 I1)."
        )

    def test_runner_does_not_define_the_administration_surface(self) -> None:
        assert "Governance" not in _module_level_symbols(_RUNNER)


@pytest.mark.contract
class TestAdministrationHoldsNoEdgeWork:
    """The core administration surface must not write on a developer machine."""

    def test_administration_does_not_reach_the_harness_settings_writers(self) -> None:
        text = _ADMINISTRATION.read_text(encoding="utf-8")
        assert "harness_adapters" not in text, (
            "governance.administration reaches into the harness settings writers. "
            "Those write .claude/settings.json on the DEVELOPER machine; a core "
            "module cannot do that in a split deployment."
        )

    def test_administration_does_not_define_the_dispatcher(self) -> None:
        defined = _module_level_symbols(_ADMINISTRATION)
        assert "GuardRunner" not in defined
        assert "run_hook" not in defined


@pytest.mark.contract
class TestPackageRootIsNotAFacade:
    """The core package root must not re-export the edge hook dispatch."""

    def test_root_does_not_reexport_the_dispatcher(self) -> None:
        names = _imported_names(_INIT)
        assert "GuardRunner" not in names
        assert "HookDecision" not in names
        assert "run_hook" not in names

    def test_root_does_not_reexport_the_administration_surface(self) -> None:
        assert "Governance" not in _imported_names(_INIT)


@pytest.mark.contract
class TestDuplicatedLayoutConstantsDoNotDrift:
    """The two copies of the project layout must stay byte-identical.

    ``core_types.project_layout`` and ``installer.paths`` hold the same layout
    knowledge on the two machines (AG3-239 / FK-10 copy-set pattern). Duplication
    is the deliberate answer to "a path helper has no wire home"; silent drift
    between the copies is not, and it would be invisible until a story directory
    resolved to two different places.
    """

    def test_stories_dir_matches_the_edge_copy(self) -> None:
        import agentkit.backend.core_types.project_layout as core_layout
        import agentkit.backend.installer.paths as edge_layout

        assert core_layout.STORIES_DIR == edge_layout.STORIES_DIR

    def test_story_dir_resolves_identically(self) -> None:
        from pathlib import Path

        from agentkit.backend.core_types.project_layout import story_dir as core_story_dir
        from agentkit.backend.installer.paths import story_dir as edge_story_dir

        root = Path("/tmp/project")
        assert core_story_dir(root, "AG3-239") == edge_story_dir(root, "AG3-239")
