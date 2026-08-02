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
    ("raw", "expected", "verbatim", "why"),
    [
        (BACKSLASH + "|", BACKSLASH * 2 + "|", True, "markdown escapes table pipes; JSON has no such escape"),
        (BACKSLASH + "_", BACKSLASH * 2 + "_", True, "the case fixed before this one, still repaired"),
        (BACKSLASH + "*", BACKSLASH * 2 + "*", True, "markdown emphasis escape"),
        (BACKSLASH + "[", BACKSLASH * 2 + "[", True, "markdown link escape"),
        (BACKSLASH + "u12", BACKSLASH * 2 + "u12", True, "a truncated unicode escape is not an escape either"),
        (BACKSLASH * 2, BACKSLASH * 2, False, "a valid escaped backslash is kept verbatim"),
        (BACKSLASH + '"', BACKSLASH + '"', False, "a valid escaped quote is kept verbatim"),
        (BACKSLASH + "n", BACKSLASH + "n", False, "a valid newline escape is kept verbatim"),
        (BACKSLASH + "u0041", BACKSLASH + "u0041", False, "a valid unicode escape is kept verbatim"),
        (BACKSLASH * 2 + "|", BACKSLASH * 2 + "|", False, "escaped backslash THEN a bare pipe: nothing to repair"),
        (BACKSLASH * 2 + "_", BACKSLASH * 2 + "_", False, "the same, one character class over"),
    ],
)
def test_only_invalid_escapes_are_repaired(raw: str, expected: str, verbatim: bool, why: str) -> None:
    """A stray backslash is ESCAPED, never dropped.

    ``verbatim`` is the contract that matters: a repaired escape must
    decode to ITSELF, character for character. Dropping the backslash also
    produces valid JSON — but one that decodes to different text than the
    model sent, which is how a mis-escaped answer turns into a silently
    wrong one. A genuine escape (``verbatim=False``) keeps meaning what
    JSON says it means and is therefore not expected to decode to itself.
    """
    repaired = repair_markdown_escapes(raw)
    assert repaired == expected, why
    if verbatim:
        assert json.loads('"' + repaired + '"') == raw, f"the repair changed the text it claims to preserve: {why}"


def test_a_quoted_markdown_cell_survives_the_repair_word_for_word() -> None:
    """The exact chunk quotation the W2 run of 2026-08-02 had to reject.

    W2 asks a model to quote a chunk VERBATIM. The chunk carries markdown
    escapes, so the quotation does too. If the repair drops them, the
    assertion no longer matches the chunk it quotes — W2 accepts it (it
    does not compare against the chunk) and W3 then rejects it, correctly,
    for a corruption the toolchain introduced itself.
    """
    cell = "`LIGHT" + BACKSLASH + "_INCUBATION` " + BACKSLASH + "| `FULL" + BACKSLASH + "_ATOM`"
    raw = '{"assertion":"' + cell + '"}'
    with pytest.raises(json.JSONDecodeError):
        json.loads(raw)
    assert json.loads(repair_markdown_escapes(raw))["assertion"] == cell, "the quotation must survive word for word"


def test_a_windows_path_is_not_silently_shortened() -> None:
    """``C:\\Program`` must not come back as ``C:Program``.

    Same defect class as the markdown cell, and the one where the damage is
    least likely to be noticed by a reader of the finding.
    """
    path = "C:" + BACKSLASH + "Program" + BACKSLASH + "Files"
    raw = '{"path":"' + path + '"}'
    with pytest.raises(json.JSONDecodeError):
        json.loads(raw)
    assert json.loads(repair_markdown_escapes(raw))["path"] == path


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
    assert decoded["a"] == "L " + stray + " F", "the stray escape must survive as the two characters it was"
    assert decoded["b"] == "git " + BACKSLASH + "| digest"


def test_text_without_escapes_is_returned_unchanged() -> None:
    """The repair is only ever offered as an ADDITIONAL parse candidate."""
    clean = '{"a":"nothing to repair"}'
    assert repair_markdown_escapes(clean) == clean
