"""The wire package must stay a pure, I/O-free contract leaf (AG3-239).

``agentkit_wire`` is the only vocabulary both distributions import. If it ever
reaches back into ``agentkit`` -- or opens a file, or pulls a third party beyond
pydantic -- it stops being a contract and becomes a shared-code dump that drags
one side of the deployment into the other.

These are enforcement tests, not documentation. Each failure names the symbol and
the rule it broke.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_WIRE_ROOT = Path(__file__).resolve().parents[3] / "src" / "agentkit_wire"

#: Standard-library modules a pure data contract may legitimately need.
_ALLOWED_STDLIB = frozenset(
    {"__future__", "datetime", "decimal", "enum", "types", "typing", "uuid"}
)
#: The single permitted third party (FK-10: "einzige Drittabhaengigkeit pydantic").
_ALLOWED_THIRD_PARTY = frozenset({"pydantic"})
#: Modules whose mere presence proves the leaf does I/O.
_FORBIDDEN = frozenset(
    {
        "os",
        "pathlib",
        "io",
        "socket",
        "subprocess",
        "shutil",
        "tempfile",
        "sqlite3",
        "urllib",
        "http",
        "requests",
        "httpx",
        "psycopg",
        "yaml",
    }
)


def _wire_modules() -> list[Path]:
    return sorted(p for p in _WIRE_ROOT.rglob("*.py") if "__pycache__" not in p.parts)


def _roots(tree: ast.AST) -> set[str]:
    """Return the top-level package of every import in the module."""
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative import inside agentkit_wire
                found.add("agentkit_wire")
            elif node.module:
                found.add(node.module.split(".")[0])
    return found


def test_wire_package_is_not_empty() -> None:
    """Guard the guard: an empty package would make every rule below vacuous."""
    modules = _wire_modules()
    assert len(modules) >= 2, f"expected wire modules under {_WIRE_ROOT}"


@pytest.mark.contract
@pytest.mark.parametrize("module", _wire_modules(), ids=lambda p: p.name)
class TestWirePurity:
    """Every module of the contract package obeys the wire rule."""

    def test_never_imports_agentkit(self, module: Path) -> None:
        """The arrow points AT the wire package and never out of it."""
        roots = _roots(ast.parse(module.read_text(encoding="utf-8")))
        assert "agentkit" not in roots, (
            f"{module.name} imports from `agentkit`. The wire package is a leaf: "
            "if it depends on either distribution, both distributions depend on "
            "that one through it."
        )

    def test_no_io_capable_import(self, module: Path) -> None:
        """No filesystem, network, database or subprocess reach."""
        leaked = _roots(ast.parse(module.read_text(encoding="utf-8"))) & _FORBIDDEN
        assert leaked == set(), (
            f"{module.name} imports {sorted(leaked)}. A /v1 contract type "
            "describes data; it must not be able to perform I/O."
        )

    def test_only_pydantic_and_allowed_stdlib(self, module: Path) -> None:
        """No third party beyond pydantic, no surprising stdlib reach."""
        roots = _roots(ast.parse(module.read_text(encoding="utf-8")))
        unexpected = roots - _ALLOWED_STDLIB - _ALLOWED_THIRD_PARTY - {"agentkit_wire"}
        assert unexpected == set(), (
            f"{module.name} imports {sorted(unexpected)}, which is neither "
            "pydantic nor an allowed standard-library module."
        )

    def test_declares_its_public_surface(self, module: Path) -> None:
        """Every module names ``__all__`` so the wire surface is enumerable."""
        tree = ast.parse(module.read_text(encoding="utf-8"))
        names = {
            target.id
            for node in tree.body
            if isinstance(node, ast.Assign)
            for target in node.targets
            if isinstance(target, ast.Name)
        } | {
            node.target.id
            for node in tree.body
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
        }
        assert "__all__" in names, f"{module.name} does not declare __all__"


@pytest.mark.contract
class TestMigratedSymbolsHaveExactlyOneHome:
    """A migrated symbol must not resolve at its old location any more.

    This is the difference between a move and a compatibility layer: after a
    move there is one import path, and the old one is gone (CLAUDE.md, KEINE
    KOMPATIBILITAETSSCHICHTEN).
    """

    @pytest.mark.parametrize(
        ("old_module", "symbol"),
        [
            ("agentkit.backend.governance.hook_registration", "HookDefinition"),
            ("agentkit.backend.governance.hook_registration", "HookEventName"),
            ("agentkit.backend.config.models", "TelemetryConfig"),
            ("agentkit.backend.config", "TelemetryConfig"),
            (
                "agentkit.backend.control_plane.models",
                "GuardCounterMutationRequest",
            ),
        ],
    )
    def test_old_location_no_longer_resolves_it(
        self, old_module: str, symbol: str
    ) -> None:
        """``hasattr``, not ``__all__`` -- the latter cannot see the violation.

        A module that imports the migrated symbol still BINDS the public name,
        so ``from <old_module> import <symbol>`` keeps working even when
        ``__all__`` no longer lists it. Checking ``__all__`` therefore passes on
        exactly the arrangement it is supposed to forbid; AG3-239 review round 1
        found ``TelemetryConfig`` reachable at three paths under a green
        ``__all__`` assertion. ``hasattr`` is what the promise "exactly one
        import path" actually means.

        A module that genuinely needs the type at runtime imports it under a
        private alias (see ``config/models.py``), which binds no public name.
        """
        import importlib

        module = importlib.import_module(old_module)
        assert not hasattr(module, symbol), (
            f"`from {old_module} import {symbol}` still resolves. The symbol "
            "moved to the wire package; a second import path is a compatibility "
            "layer. If the module needs the type at runtime, import it under a "
            "leading-underscore alias."
        )

    @pytest.mark.parametrize(
        ("wire_module", "symbol"),
        [
            ("agentkit_wire.governance_registration", "HookDefinition"),
            ("agentkit_wire.governance_registration", "HookEventName"),
            ("agentkit_wire.project_config", "TelemetryConfig"),
            (
                "agentkit_wire.control_plane_mutations",
                "GuardCounterMutationRequest",
            ),
            ("agentkit_wire.story_lifecycle", "StorySplitMutationRequest"),
            ("agentkit_wire.story_lifecycle", "StorySplitMutationResponse"),
            ("agentkit_wire.story_lifecycle", "StoryResetMutationRequest"),
            ("agentkit_wire.story_lifecycle", "StoryResetMutationResponse"),
            ("agentkit_wire.story_lifecycle", "StoryExitMutationRequest"),
            ("agentkit_wire.story_lifecycle", "StoryExitMutationResponse"),
        ],
    )
    def test_new_location_defines_it(self, wire_module: str, symbol: str) -> None:
        import importlib

        module = importlib.import_module(wire_module)
        assert hasattr(module, symbol)
        assert symbol in getattr(module, "__all__", ())

    @pytest.mark.parametrize(
        "dissolved_module",
        [
            "agentkit.backend.story_split.http_models",
            "agentkit.backend.story_reset.http_models",
            "agentkit.backend.story_exit.http_models",
        ],
    )
    def test_a_dissolved_source_module_is_gone(self, dissolved_module: str) -> None:
        """``module_dissolves: true`` means the file no longer exists (AG3-240).

        The three story-lifecycle ``http_models`` modules had NO remainder: their
        whole public surface is ``/v1`` vocabulary. Leaving the module behind as
        a re-export would be the compatibility layer the move exists to avoid,
        and ``hasattr`` on a surviving module cannot tell the two apart.
        """
        import importlib

        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(dissolved_module)
