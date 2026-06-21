"""Contract: the governance freeze-export path has ONE source of truth (ERROR E).

AG3-032 ERROR E / CLAUDE.md SINGLE SOURCE OF TRUTH: the canonical
``.agentkit/governance/freeze.json`` governance-plane path literal lives exactly
once, in ``core_types.plane_artifact_names``. The governance and state_backend
modules that need it MUST source it from there and never re-hardcode the literal.

This pins:

1. The two derived forms (parts tuple / relpath string) agree.
2. ``principal_capabilities.freeze.FREEZE_EXPORT_RELPATH`` (governance),
   ``state_backend.store.freeze_repository._FREEZE_EXPORT_RELPATH`` and
   ``guard_system.protected_paths.PROTECTED_GOVERNANCE_FREEZE_EXPORT`` all equal
   the canonical core_types constant.
3. No governance / state_backend production module re-hardcodes the path literal
   as a string/Path expression (only the core_types owner and docstrings may
   mention it).
"""

from __future__ import annotations

import ast
from pathlib import Path

from agentkit.backend.core_types.plane_artifact_names import (
    GOVERNANCE_FREEZE_EXPORT_PARTS,
    GOVERNANCE_FREEZE_EXPORT_RELPATH,
)
from agentkit.backend.governance.guard_system.protected_paths import (
    PROTECTED_GOVERNANCE_FREEZE_EXPORT,
)
from agentkit.backend.governance.principal_capabilities.freeze import FREEZE_EXPORT_RELPATH
from agentkit.backend.state_backend.store.freeze_repository import _FREEZE_EXPORT_RELPATH

_LITERAL = ".agentkit/governance/freeze.json"
_SRC_ROOT = Path(__file__).resolve().parents[3] / "src" / "agentkit"


def test_core_types_parts_and_relpath_agree() -> None:
    assert "/".join(GOVERNANCE_FREEZE_EXPORT_PARTS) == GOVERNANCE_FREEZE_EXPORT_RELPATH
    assert GOVERNANCE_FREEZE_EXPORT_RELPATH == _LITERAL


def test_governance_and_backend_source_the_same_truth() -> None:
    # Governance overlay constant (Path) == canonical relpath.
    assert FREEZE_EXPORT_RELPATH.as_posix() == GOVERNANCE_FREEZE_EXPORT_RELPATH
    # State-backend export adapter constant (Path) == canonical relpath.
    assert _FREEZE_EXPORT_RELPATH.as_posix() == GOVERNANCE_FREEZE_EXPORT_RELPATH
    # Guard-system protected-path string == canonical relpath.
    assert PROTECTED_GOVERNANCE_FREEZE_EXPORT == GOVERNANCE_FREEZE_EXPORT_RELPATH


def _string_literals(tree: ast.AST) -> list[str]:
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


def _is_path_literal(value: str) -> bool:
    """Whether ``value`` is the freeze path *used as a path literal*.

    The single source of truth is violated only by a string literal that IS the
    governance freeze path (a path expression), not by prose / SQL comments that
    merely MENTION the path inside a larger blob (e.g. a schema DDL comment). A
    real path literal is short and is exactly (or a clean tail of) the canonical
    relpath. We therefore flag a literal whose stripped value equals the relpath,
    or a short single-line literal that ends with it.
    """
    stripped = value.strip()
    if stripped == _LITERAL:
        return True
    return (
        "\n" not in value
        and len(value) <= 80
        and stripped.endswith(_LITERAL)
    )


def test_no_governance_or_backend_module_rehardcodes_the_literal() -> None:
    # The path literal may appear ONLY in the core_types owner. Any executable
    # string literal that IS the governance freeze path (a path expression) in a
    # governance or state_backend production module is a SINGLE SOURCE OF TRUTH
    # violation. Docstrings are excluded (ast docstring literals are skipped); a
    # SQL-comment mention inside a multi-line DDL blob is prose, not a path.
    offenders: list[str] = []
    scan_dirs = (
        _SRC_ROOT / "governance",
        _SRC_ROOT / "state_backend",
    )
    owner = (_SRC_ROOT / "core_types" / "plane_artifact_names.py").resolve()
    for scan_dir in scan_dirs:
        for py_file in scan_dir.rglob("*.py"):
            if py_file.resolve() == owner:
                continue
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
            docstrings = _collect_docstrings(tree)
            for value in _string_literals(tree):
                if value in docstrings:
                    continue
                if _is_path_literal(value):
                    offenders.append(f"{py_file}: {value!r}")
    assert offenders == [], (
        "governance/state_backend modules must source the freeze path from "
        f"core_types.plane_artifact_names, not hardcode it: {offenders}"
    )


def _collect_docstrings(tree: ast.AST) -> set[str]:
    docstrings: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(
            node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            doc = ast.get_docstring(node, clean=False)
            if doc is not None:
                docstrings.add(doc)
    return docstrings
