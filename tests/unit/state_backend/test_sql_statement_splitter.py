"""Unit tests for ``iter_sql_statements`` (postgres_store SQL splitter).

Reproduces the AG3-031 regression: a ``--`` comment containing ``;`` was
mis-split by the previous naive ``script.split(";")`` and executed as the
bogus statement ``a 3-tuple key collapsed`` (PostgreSQL syntax error).
"""

from __future__ import annotations

from pathlib import Path

from agentkit.backend.state_backend.postgres_store import iter_sql_statements


def test_semicolon_inside_line_comment_does_not_split() -> None:
    """A ``;`` inside a ``--`` comment must stay attached to its statement."""
    script = (
        "CREATE TABLE foo (\n"
        "    -- registers under one matcher (Bash); a 3-tuple key collapsed\n"
        "    id INTEGER PRIMARY KEY\n"
        ");\n"
        "CREATE TABLE bar (id INTEGER);\n"
    )
    statements = list(iter_sql_statements(script))

    assert len(statements) == 2
    assert statements[0].startswith("CREATE TABLE foo")
    assert "a 3-tuple key collapsed" in statements[0]
    assert statements[1].startswith("CREATE TABLE bar")
    # The regression produced a standalone "a 3-tuple key collapsed" fragment.
    assert not any(s.startswith("a 3-tuple") for s in statements)


def test_semicolon_inside_string_literal_does_not_split() -> None:
    """A ``;`` inside a single-quoted literal must not split the statement."""
    script = "INSERT INTO t (msg) VALUES ('a; b; c'); SELECT 1;"
    statements = list(iter_sql_statements(script))

    assert statements == ["INSERT INTO t (msg) VALUES ('a; b; c')", "SELECT 1"]


def test_doubled_quote_escape_inside_literal() -> None:
    """Doubled '' escape keeps the literal open across an inner ``;``."""
    script = "INSERT INTO t (msg) VALUES ('it''s; fine'); SELECT 2;"
    statements = list(iter_sql_statements(script))

    assert statements == ["INSERT INTO t (msg) VALUES ('it''s; fine')", "SELECT 2"]


def test_block_comment_semicolon_does_not_split() -> None:
    """A ``;`` inside a ``/* */`` block comment must not split."""
    script = "CREATE TABLE a (id INT); /* note; with semicolon */ CREATE TABLE b (id INT);"
    statements = list(iter_sql_statements(script))

    assert len(statements) == 2
    assert statements[0] == "CREATE TABLE a (id INT)"
    assert statements[1].endswith("CREATE TABLE b (id INT)")


def test_comment_only_and_whitespace_fragments_are_skipped() -> None:
    """Trailing comment-only / blank fragments must not yield empty queries."""
    script = "SELECT 1;\n-- only a trailing comment\n   \n"
    statements = list(iter_sql_statements(script))

    assert statements == ["SELECT 1"]


def test_empty_script_yields_nothing() -> None:
    assert list(iter_sql_statements("")) == []
    assert list(iter_sql_statements("   \n  -- just a comment\n")) == []


def test_real_postgres_schema_parses_without_bogus_fragment() -> None:
    """The shipped schema must split cleanly with no prose-as-SQL fragment."""
    schema_path = (
        Path(__file__).resolve().parents[3]
        / "src"
        / "agentkit"
        / "backend"
        / "state_backend"
        / "postgres_schema.sql"
    )
    statements = list(iter_sql_statements(schema_path.read_text(encoding="utf-8")))

    assert statements, "schema produced no statements"
    # The regression fragment must never appear as a standalone statement.
    assert not any(s.lstrip().startswith("a 3-tuple key collapsed") for s in statements)
    # Every emitted statement must contain real SQL (not be comment-only).
    for stmt in statements:
        assert stmt.strip()
