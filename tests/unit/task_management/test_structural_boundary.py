"""Structural boundary tests for the task-management bounded context."""

from __future__ import annotations

import ast
from pathlib import Path


def test_task_management_imports_no_pipeline_phase_or_gate_modules() -> None:
    package_root = Path("src/agentkit/backend/task_management")
    forbidden_prefixes = (
        "agentkit.backend.pipeline_engine",
        "agentkit.pipeline",
        "agentkit.backend.story_exit",
    )
    forbidden_fragments = (".phase", ".gate")
    offenders: list[str] = []

    for path in package_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            module: str | None = None
            if isinstance(node, ast.Import):
                for alias in node.names:
                    module = alias.name
                    if _is_forbidden(module, forbidden_prefixes, forbidden_fragments):
                        offenders.append(f"{path}:{node.lineno}:{module}")
            elif isinstance(node, ast.ImportFrom):
                module = node.module
                if module is not None and _is_forbidden(
                    module,
                    forbidden_prefixes,
                    forbidden_fragments,
                ):
                    offenders.append(f"{path}:{node.lineno}:{module}")

    assert offenders == []


def _is_forbidden(
    module: str,
    prefixes: tuple[str, ...],
    fragments: tuple[str, ...],
) -> bool:
    return module.startswith(prefixes) or any(fragment in module for fragment in fragments)
