"""Escape repair for markdown that leaked into LLM JSON (AG3-179).

Every case is written with explicit character lists rather than string
literals: the whole subject is backslash counting, and a literal that is
itself mis-escaped would test the wrong thing while looking right.
"""

from __future__ import annotations

import json

import pytest
from concept_governance.json_escapes import repair_markdown_escapes

BACKSLASH = chr(92)


@pytest.mark.parametrize(
    ("raw", "expected", "why"),
    [
        (BACKSLASH + "|", "|", "markdown escapes table pipes; JSON has no such escape"),
        (BACKSLASH + "_", "_", "the case fixed before this one, still repaired"),
        (BACKSLASH + "*", "*", "markdown emphasis escape"),
        (BACKSLASH + "[", "[", "markdown link escape"),
        (BACKSLASH * 2, BACKSLASH * 2, "a valid escaped backslash is kept verbatim"),
        (BACKSLASH + '"', BACKSLASH + '"', "a valid escaped quote is kept verbatim"),
        (BACKSLASH + "n", BACKSLASH + "n", "a valid newline escape is kept verbatim"),
        (BACKSLASH + "u0041", BACKSLASH + "u0041", "a valid unicode escape is kept verbatim"),
        (BACKSLASH * 2 + "|", BACKSLASH * 2 + "|", "escaped backslash THEN a bare pipe: nothing to repair"),
        (BACKSLASH * 2 + "_", BACKSLASH * 2 + "_", "the same, one character class over"),
    ],
)
def test_only_invalid_escapes_are_repaired(raw: str, expected: str, why: str) -> None:
    assert repair_markdown_escapes(raw) == expected, why


def test_a_repaired_payload_decodes_to_the_text_the_model_meant() -> None:
    """End to end: the exact shape that ended the W2 run of 2026-08-02.

    One cell carries a stray ``\\|`` (invalid JSON, must be repaired) and
    the next a genuine ``\\\\`` followed by a pipe (valid JSON, must
    survive). Repairing the first while corrupting the second would trade
    a rejected answer for a silently wrong one.
    """
    stray = BACKSLASH + "|"
    genuine = BACKSLASH * 2 + "|"
    raw = '{"a":"L ' + stray + ' F","b":"git ' + genuine + ' digest"}'
    with pytest.raises(json.JSONDecodeError):
        json.loads(raw)
    decoded = json.loads(repair_markdown_escapes(raw))
    assert decoded["a"] == "L | F"
    assert decoded["b"] == "git " + BACKSLASH + "| digest"


def test_text_without_escapes_is_returned_unchanged() -> None:
    """The repair is only ever offered as an ADDITIONAL parse candidate."""
    clean = '{"a":"nothing to repair"}'
    assert repair_markdown_escapes(clean) == clean
