"""SQL script splitting helpers for Postgres bootstrap scripts."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator


def _consume_sql_comment(script: str, i: int) -> int | None:
    """Return the index just after a ``--`` or ``/* */`` comment opened at ``i``.

    Returns ``None`` when no comment starts at ``i``. The comment text (which
    may itself contain ``;``) is consumed wholesale so it never triggers a
    statement split.

    Args:
        script: The full SQL script.
        i: Candidate comment-start index.

    Returns:
        Index after the comment, or ``None``.
    """
    two = script[i : i + 2]
    n = len(script)
    if two == "--":
        newline = script.find("\n", i)
        return n if newline == -1 else newline + 1
    if two == "/*":
        end = script.find("*/", i + 2)
        return n if end == -1 else end + 2
    return None


def _consume_sql_string(script: str, i: int, quote: str) -> int:
    """Return the index just after a quoted literal/identifier opened at ``i``.

    Handles doubled-quote escapes (``''`` / ``""``); an unterminated literal
    consumes the rest of the script.

    Args:
        script: The full SQL script.
        i: Index of the opening quote.
        quote: The quote character (``'`` or ``"``).

    Returns:
        Index after the closing quote (or end of script).
    """
    n = len(script)
    j = i + 1
    while j < n:
        if script[j] != quote:
            j += 1
        elif j + 1 < n and script[j + 1] == quote:  # doubled escape stays inside
            j += 2
        else:
            return j + 1
    return n


def iter_sql_statements(script: str) -> Iterator[str]:
    """Yield individual SQL statements from a multi-statement script.

    Splits on top-level ``;`` only, ignoring semicolons inside single-quoted
    string literals, double-quoted identifiers, ``--`` line comments or
    ``/* */`` block comments (the scanning of those spans is delegated to
    :func:`_consume_sql_comment` / :func:`_consume_sql_string`). psycopg's
    ``execute`` accepts a single statement at a time, so a naive
    ``str.split(";")`` mis-splits any script whose comment or literal contains a
    ``;`` (FIX THE MODEL: the AG3-031 governance hotfix added a ``--`` comment
    containing ``;``, which the naive splitter executed as the bogus statement
    ``a 3-tuple key collapsed``).

    Comment-only / whitespace-only fragments are skipped so psycopg never
    receives an empty query.

    Args:
        script: One or more ``;``-separated SQL statements.

    Yields:
        Each non-empty statement, stripped of surrounding whitespace, with its
        original comments and literals intact (psycopg ignores them).
    """
    buf: list[str] = []
    has_code = False
    i, n = 0, len(script)
    while i < n:
        comment_end = _consume_sql_comment(script, i)
        if comment_end is not None:
            buf.append(script[i:comment_end])
            i = comment_end
            continue
        ch = script[i]
        if ch in {"'", '"'}:
            end = _consume_sql_string(script, i, ch)
            buf.append(script[i:end])
            has_code = True
            i = end
            continue
        if ch == ";":
            if has_code:
                yield "".join(buf).strip()
            buf = []
            has_code = False
        else:
            has_code = has_code or not ch.isspace()
            buf.append(ch)
        i += 1
    if has_code:
        yield "".join(buf).strip()
