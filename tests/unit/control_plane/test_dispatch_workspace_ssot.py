"""SSOT static regression: no dev-local ``project_root`` FS coupling (AG3-123 AC2).

The canonical phase dispatch + its composition wiring must derive the
story-workspace filesystem anchor / project-config root ONLY from the Backend
``StoryWorkspaceLocator`` -- never from the dev-supplied ``StoryContext.project_root``.

This AST regression fails closed if ANY productive ``<story-context>.project_root``
read flows into a filesystem-anchor / config-root deriving callee (e.g.
``story_dir(...)``, ``load_project_config(...)``, ``build_pre_start_guard(...)``)
in the productive dispatch / runtime / composition modules. It covers the BLOCKER
class the adversarial review found (the eager closure pre-merge wiring that read
``ctx.project_root`` during engine construction) and resists simple one-hop
aliasing (``root = ctx.project_root; story_dir(root, ...)``).

It deliberately does NOT flag:
* ``workspace.project_root`` reads (the locator result -- the SINGLE source);
* benign carrier reads/projections (e.g. the dispatcher hydration comparison
  ``ctx.project_root != workspace.project_root`` and the ``model_copy`` that
  mirrors the workspace anchor onto the run carrier);
* ``config.project_root`` reads (a typed Config object, not the StoryContext);
* the locator module itself.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from agentkit.backend.bootstrap import composition_root as composition_root_module
from agentkit.backend.control_plane import dispatch as dispatch_module
from agentkit.backend.control_plane import runtime as runtime_module

#: Identifiers that denote the dev-supplied ``StoryContext`` carrier. Reading
#: ``<carrier>.project_root`` to derive an FS anchor is the forbidden coupling.
_STORY_CONTEXT_CARRIERS = frozenset({"ctx", "story_ctx", "story_context"})

#: Callees that derive a filesystem anchor or a project-config root from a
#: ``project_root`` argument. A ``<carrier>.project_root`` (or a one-hop alias of
#: it) reaching ANY of these is the dev-local coupling AG3-123 removed.
_FS_DERIVING_CALLEES = frozenset(
    {
        "story_dir",
        "resolve_story_dir",
        "qa_story_dir",
        "qa_dir",
        "temp_dir",
        "load_project_config",
        "_project_config_present",
        "build_pre_start_guard",
    }
)


def _callee_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _is_carrier_project_root(node: ast.expr) -> bool:
    """Whether ``node`` is ``<story-context-carrier>.project_root``."""
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "project_root"
        and isinstance(node.value, ast.Name)
        and node.value.id in _STORY_CONTEXT_CARRIERS
    )


def _tainted_aliases(tree: ast.AST) -> set[str]:
    """Local names bound directly to ``<carrier>.project_root`` (one-hop alias)."""
    aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and _is_carrier_project_root(node.value):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    aliases.add(target.id)
        elif (
            isinstance(node, ast.AnnAssign)
            and node.value is not None
            and _is_carrier_project_root(node.value)
            and isinstance(node.target, ast.Name)
        ):
            aliases.add(node.target.id)
    return aliases


def _arg_is_coupled(arg: ast.expr, aliases: set[str]) -> bool:
    if _is_carrier_project_root(arg):
        return True
    return isinstance(arg, ast.Name) and arg.id in aliases


def _coupling_offenders(source: str) -> list[str]:
    """Return dumps of FS-deriving calls anchored on a dev-local ``project_root``."""
    tree = ast.parse(source)
    aliases = _tainted_aliases(tree)
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _callee_name(node) not in _FS_DERIVING_CALLEES:
            continue
        candidate_args: list[ast.expr] = list(node.args)
        candidate_args.extend(kw.value for kw in node.keywords)
        if any(_arg_is_coupled(arg, aliases) for arg in candidate_args):
            offenders.append(ast.dump(node))
    return offenders


@pytest.mark.parametrize(
    "module",
    [dispatch_module, runtime_module, composition_root_module],
    ids=["dispatch", "runtime", "composition_root"],
)
def test_no_fs_anchor_from_story_context_project_root(module: object) -> None:
    """No FS/config root is derived from a dev-supplied ``ctx.project_root``."""
    source = Path(module.__file__).read_text(encoding="utf-8")  # type: ignore[attr-defined]

    offenders = _coupling_offenders(source)

    assert offenders == [], (
        "A productive story-context project_root -> FS/config-root coupling "
        "reappeared. The workspace FS anchor must be resolved Backend-side via "
        "StoryWorkspaceLocator and threaded down only (AG3-123 AC2). Offending "
        f"call(s) in {module.__name__}: {offenders}"  # type: ignore[attr-defined]
    )


def test_guard_detects_the_blocker_class_and_aliasing() -> None:
    """The detector flags the pre-fix coupling class AND a one-hop alias of it.

    Proves the guard would have FAILED before the AG3-123 fix: the eager closure
    pre-merge wiring read ``ctx.project_root`` to load the project config, and a
    trivially-aliased ``story_dir`` call must be caught too.
    """
    reintroduced = (
        "def f(story_dir, ctx):\n"
        "    cfg = load_project_config(ctx.project_root)\n"  # BLOCKER class
        "    present = _project_config_present(ctx.project_root)\n"  # BLOCKER class
        "    root = ctx.project_root\n"  # one-hop alias
        "    sd = story_dir(root, ctx.story_id)\n"  # aliased FS anchor
        "    return cfg, present, sd\n"
    )
    offenders = _coupling_offenders(reintroduced)
    assert len(offenders) == 3, offenders


def test_guard_ignores_workspace_and_carrier_projection() -> None:
    """The detector does NOT flag the locator result or benign carrier reads."""
    benign = (
        "def g(ctx, workspace):\n"
        "    sd = story_dir(workspace.project_root, ctx.story_id)\n"  # locator result
        "    if ctx.project_root != workspace.project_root:\n"  # projection compare
        "        ctx = ctx.model_copy(update={'project_root': workspace.project_root})\n"
        "    cfg = load_project_config(config.project_root)\n"  # typed Config, not ctx
        "    return sd, ctx, cfg\n"
    )
    assert _coupling_offenders(benign) == []
