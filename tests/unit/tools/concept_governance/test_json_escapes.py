"""Escape repair for markdown that leaked into LLM JSON (AG3-179).

Every case is written with explicit character lists rather than string
literals: the whole subject is backslash counting, and a literal that is
itself mis-escaped would test the wrong thing while looking right.
"""

from __future__ import annotations

import json

import pytest
from concept_governance.json_escapes import (
    SchemaKeyCollisionError,
    normalize_schema_keys,
    repair_markdown_escapes,
)

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
    """Retain the AG3-179 repair invariant for generic JSON value consumers.

    W2/W3 v2 no longer copy evidence text, but this shared repair must still
    never change ordinary response values while making invalid escapes parseable.
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


ALIAS_KEY = '"has' + BACKSLASH * 2 + "_normative" + BACKSLASH * 2 + '_statements"'
PLAIN_KEY = '"has_normative_statements"'


@pytest.mark.parametrize(
    ("first", "second", "why"),
    [
        (PLAIN_KEY + ":true", ALIAS_KEY + ":false", "the alias arrives second and would win last-wins"),
        (ALIAS_KEY + ":false", PLAIN_KEY + ":true", "the alias arrives first and would win first-wins"),
        (PLAIN_KEY + ":true", PLAIN_KEY + ":false", "no alias at all: json.loads collapses this on its own"),
    ],
)
def test_two_keys_for_one_field_are_rejected_fail_closed(first: str, second: str, why: str) -> None:
    """Normalization must never MERGE two contradictory statements.

    Both orders are tested on purpose. "Last wins" and "first wins" are
    equally arbitrary, and the point of the finding is that neither is a
    decision anyone made: the response says two things about one field, and
    the reader of a W2 finding cannot see that one of them was dropped.

    The third case needs no backslash at all — :func:`json.loads` collapses
    a literal duplicate key silently, and the repair is the only place in
    the chain that still sees both.
    """
    candidate = "{" + first + "," + second + ',"assertions":[]}'

    with pytest.raises(SchemaKeyCollisionError, match="carries two keys for field 'has_normative_statements'"):
        normalize_schema_keys(candidate)


def test_a_populated_list_cannot_be_replaced_by_an_aliased_empty_one() -> None:
    """The same defect in W3, where it erases evidence instead of a flag.

    ``contradictions`` carries the found contradictions. An alias with
    ``[]`` beside it would turn a reported contradiction into a clean
    sweep — a governance gate reporting PASS on evidence it was given.
    """
    alias = '"contra' + BACKSLASH * 2 + 'dictions"'
    candidate = '{"contradictions":[{"loci":[]}],' + alias + ":[]}"

    with pytest.raises(SchemaKeyCollisionError, match="carries two keys for field 'contradictions'"):
        normalize_schema_keys(candidate)


def test_a_collision_inside_a_nested_object_is_found_too() -> None:
    """Every object is checked, not only the top-level one.

    The schema nests: assertions and contradiction loci are objects of
    their own, and a merged boundary field there changes the referenced
    source range rather than a flag.
    """
    alias = '"start' + BACKSLASH * 2 + '_id"'
    candidate = '{"assertions":[{"start_id":"a","scopes":[],' + alias + ':"b"}]}'

    with pytest.raises(SchemaKeyCollisionError, match="carries two keys for field 'start_id'"):
        normalize_schema_keys(candidate)


def test_an_aliased_key_without_a_twin_is_still_repaired() -> None:
    """The counter-probe: the collision check must not break the repair.

    A single escaped key is what :func:`normalize_schema_keys` exists for.
    It normalizes, the values stay untouched, and nothing is rejected.
    """
    candidate = "{" + ALIAS_KEY + ':false,"assertions":[]}'

    assert json.loads(normalize_schema_keys(candidate)) == {
        "has_normative_statements": False,
        "assertions": [],
    }


def test_text_that_is_not_json_is_still_returned_unchanged() -> None:
    """A decode failure means "not JSON" and stays a no-op, not a finding."""
    assert normalize_schema_keys("Worked for 29s") == "Worked for 29s"
