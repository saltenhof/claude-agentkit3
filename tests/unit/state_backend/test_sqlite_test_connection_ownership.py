"""Guards against test-owned SQLite connections being left to the GC."""

from __future__ import annotations

import ast
from pathlib import Path


def _is_raw_sqlite_connect(expression: ast.expr) -> bool:
    return (
        isinstance(expression, ast.Call)
        and isinstance(expression.func, ast.Attribute)
        and expression.func.attr == "connect"
        and isinstance(expression.func.value, ast.Name)
        and expression.func.value.id == "sqlite3"
    )


def test_sqlite_connections_are_not_used_as_closing_context_managers() -> None:
    """A sqlite connection context commits/rolls back but does not close."""
    tests_root = Path(__file__).resolve().parents[2]
    offenders: list[str] = []

    for path in tests_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.With, ast.AsyncWith)):
                continue
            if any(_is_raw_sqlite_connect(item.context_expr) for item in node.items):
                offenders.append(f"{path.relative_to(tests_root)}:{node.lineno}")

    assert offenders == [], (
        "sqlite3.Connection.__exit__ does not close the handle; wrap the "
        f"connection in contextlib.closing: {offenders}"
    )
