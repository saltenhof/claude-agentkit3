"""Repair of markdown escapes that leak into LLM JSON responses (W2/W3)."""

from __future__ import annotations

import re

#: JSON's complete escape alphabet (RFC 8259 section 7).
_VALID_ESCAPE = re.compile(r'\\(?:u[0-9a-fA-F]{4}|["\\/bfnrt])')

#: Any backslash sequence, valid or not. ``re.S`` so a stray backslash before
#: a newline is matched too instead of being left behind.
_ANY_ESCAPE = re.compile(r"\\(?:u[0-9a-fA-F]{4}|.)", re.S)


def repair_markdown_escapes(text: str) -> str:
    """Drop backslashes that JSON does not recognise as escapes.

    Our concept prose is markdown, and markdown escapes the pipes and
    underscores inside tables (``\\|``, ``\\_``). Models quote those cells
    back verbatim, where the backslash is no longer an escape but a syntax
    error: ``Invalid JSON: invalid escape``. A single such cell used to end
    a whole governance run (AG3-179), and patching one character class at a
    time only moves the next failure one table over — ``\\_`` was fixed
    before, ``\\|`` came next.

    Valid escapes are matched FIRST and kept verbatim, so a legitimately
    escaped backslash (``\\\\``) is never mistaken for a stray one and the
    character after it is never touched.

    This repairs FORM, never content: it is applied to an additional parse
    candidate, and the repaired text still has to satisfy the strict schema.
    A response that is wrong rather than merely mis-escaped stays rejected.

    Args:
        text: The raw response text.

    Returns:
        The text with non-JSON escapes reduced to their bare character.
    """

    def repair(match: re.Match[str]) -> str:
        token = match.group(0)
        return token if _VALID_ESCAPE.fullmatch(token) else token[1:]

    return _ANY_ESCAPE.sub(repair, text)
