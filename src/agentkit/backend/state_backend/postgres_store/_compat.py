"""psycopg compatibility wrapper for sqlite-shaped repository SQL."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence

    import psycopg

from ._sql_script import iter_sql_statements


class _CompatConnection:
    """Compatibility wrapper translating sqlite-style queries to psycopg."""

    def __init__(self, conn: psycopg.Connection[Any]) -> None:
        self._conn = conn

    def execute(
        self,
        query: str,
        params: Sequence[object] = (),
    ) -> psycopg.Cursor[dict[str, Any]]:
        normalized = query.replace("?", "%s")
        return self._conn.execute(normalized, params)

    def executescript(self, script: str) -> None:
        for statement in iter_sql_statements(script):
            self._conn.execute(statement)
