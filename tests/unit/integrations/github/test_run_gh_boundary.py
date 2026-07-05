"""AG3-146 AC6: no consumer imports the ``gh`` CLI mechanics outside the adapter.

Regression guard (FK-12 §12.1, SOLL-182): ``run_gh``/``run_gh_json``/
``run_gh_graphql``/``resolve_token_for_owner`` are ADAPTER-INTERNAL to
``agentkit.integration_clients.github``. No module anywhere else under
``src/agentkit`` may import them — the code-backend port
(``agentkit.backend.code_backend.provider_port.CodeBackendPort``) is the ONLY
way backend code reaches GitHub.
"""

from __future__ import annotations

import ast
from pathlib import Path

import agentkit

_ADAPTER_PACKAGE = "agentkit.integration_clients.github"
_FORBIDDEN_NAMES = frozenset(
    {"run_gh", "run_gh_json", "run_gh_graphql", "resolve_token_for_owner"}
)
_SRC_ROOT = Path(agentkit.__file__).resolve().parent
_SRC_PARENT = _SRC_ROOT.parent


def _module_name_for(path: Path) -> str:
    parts = list(path.relative_to(_SRC_PARENT).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _is_inside_adapter_package(module_name: str) -> bool:
    return module_name == _ADAPTER_PACKAGE or module_name.startswith(
        f"{_ADAPTER_PACKAGE}."
    )


def _violations_in(path: Path) -> list[str]:
    module_name = _module_name_for(path)
    if _is_inside_adapter_package(module_name):
        return []
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    hits: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.module is None:
            continue
        if not _is_inside_adapter_package(node.module):
            continue
        for alias in node.names:
            if alias.name in _FORBIDDEN_NAMES:
                hits.append(f"{module_name}: from {node.module} import {alias.name}")
    return hits


def test_no_consumer_outside_the_github_adapter_imports_run_gh() -> None:
    violations: list[str] = []
    for path in _SRC_ROOT.rglob("*.py"):
        violations.extend(_violations_in(path))
    assert violations == [], (
        "run_gh/run_gh_json/run_gh_graphql/resolve_token_for_owner must stay "
        "adapter-internal to agentkit.integration_clients.github (AG3-146 "
        f"AC1/AC6); found: {violations}"
    )
