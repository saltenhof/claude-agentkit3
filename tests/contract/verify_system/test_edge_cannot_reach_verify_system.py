"""The evaluation machinery is unreachable from the developer-machine process.

This is the guarantee AG3-241 exists for, and it is not a distribution
nicety: an edge that can import ``verify_system.llm_evaluator`` can run the
Layer-2 evaluation of the very story it is producing, and an edge that can
import ``verify_system.evidence`` can produce the QA artefact it will be judged
by (``CLAUDE.md`` §WORKFLOW- UND STATE-DISZIPLIN).

The test reads the edge membership from the published classification
(``formal.architecture-conformance.entities``) rather than from a hand-kept list,
so a module that changes sides cannot slip past it. It is deliberately an AST
scan and not an import-time probe: an import guard would only prove that the
symbol is not reached on one code path, this proves the edge does not name it.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SRC_ROOT = _REPO_ROOT / "src"
_ENTITIES = (
    _REPO_ROOT
    / "concept"
    / "formal-spec"
    / "architecture-conformance"
    / "entities.md"
)
_FORMAL_BLOCK = re.compile(
    r"<!-- FORMAL-SPEC:BEGIN -->\s*```yaml\n(?P<body>.*?)\n```", re.DOTALL
)
#: The bounded context that must stay out of reach.
_CORE_BC = "agentkit.backend.verify_system"


def _edge_module_prefixes() -> tuple[str, ...]:
    """Return the module prefixes the classification assigns to the edge."""
    match = _FORMAL_BLOCK.search(_ENTITIES.read_text(encoding="utf-8"))
    assert match is not None, f"no formal-spec block in {_ENTITIES}"
    document = yaml.safe_load(match.group("body"))
    for distribution in document["distributions"]:
        if str(distribution["code"]) == "edge":
            prefixes = tuple(str(p) for p in distribution.get("module_prefixes") or ())
            assert prefixes, "the edge distribution claims no module prefixes"
            return prefixes
    pytest.fail("no edge distribution in the classification")


def _module_name(path: Path) -> str:
    """Return the dotted module name of a file below ``src/``."""
    parts = list(path.relative_to(_SRC_ROOT).parts)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1][: -len(".py")]
    return ".".join(parts)


def _is_edge(module: str, prefixes: tuple[str, ...]) -> bool:
    """Return whether ``module`` belongs to the edge distribution."""
    return any(
        module == prefix or module.startswith(prefix + ".") for prefix in prefixes
    )


def _imported_targets(tree: ast.AST, package: str) -> list[tuple[int, str]]:
    """Return ``(lineno, absolute target)`` of every import in a module."""
    targets: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                anchor = package.split(".")
                anchor = anchor[: len(anchor) - (node.level - 1)]
                base = ".".join(anchor + (node.module or "").split("."))
            else:
                base = node.module or ""
            targets.extend((node.lineno, f"{base}.{a.name}") for a in node.names)
    return targets


def test_no_edge_module_names_the_verify_system_bounded_context() -> None:
    """No edge-classified module imports anything from ``verify_system``."""
    prefixes = _edge_module_prefixes()
    offenders: list[str] = []
    for path in sorted(_SRC_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        module = _module_name(path)
        if not _is_edge(module, prefixes):
            continue
        package = (
            module if path.name == "__init__.py" else module.rpartition(".")[0]
        )
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for lineno, target in _imported_targets(tree, package):
            if target == _CORE_BC or target.startswith(_CORE_BC + "."):
                offenders.append(f"{module}:{lineno} -> {target}")
    assert not offenders, (
        "the developer-machine process can reach the verify-system evaluation "
        "machinery again:\n  " + "\n  ".join(offenders)
    )
