"""Strict three-stage W2 response parser tests."""

from __future__ import annotations

import pytest
from concept_governance.parser import ResponseParseError, parse_response


def test_regex_fallback_recovers_structured_fields_without_deciding_policy() -> None:
    parsed = parse_response(
        'has\\_normative\\_statements: true; "assertion": "The system must retain locks.", "scopes": ["lock.lifecycle"]'
    )
    assert parsed.has_normative_statements is True
    assert parsed.assertions[0].scopes == ("lock.lifecycle",)


def test_escaped_underscore_json_is_strictly_revalidated() -> None:
    parsed = parse_response('{"has\\_normative\\_statements":false,"assertions":[]}')
    assert parsed.has_normative_statements is False


def test_prefaced_escaped_json_is_extracted_then_strictly_revalidated() -> None:
    parsed = parse_response('Worked for 12s\n\n{"has\\_normative\\_statements":false,"assertions":[]}')
    assert parsed.has_normative_statements is False


def test_escaped_table_pipe_json_is_strictly_revalidated() -> None:
    """AG3-179: a markdown-escaped pipe used to end a whole W2 run.

    Our concept prose is markdown, and markdown escapes the pipes inside
    tables. A model that quotes such a cell back emits ``\\|``, which JSON
    rejects as an invalid escape — the same failure class as ``\\_``, one
    table over. Repairing one character at a time only postpones the next
    one, so every non-JSON escape is repaired.

    The assertion is a VERBATIM quotation of the chunk, so the repair has
    to give back the cell exactly as it stands there, escapes included. An
    earlier fix dropped the backslashes: W2 accepted the altered quotation
    (it does not compare against the chunk) and W3 then rejected it,
    correctly, for a corruption the toolchain had introduced itself.
    """
    cell = "`LIGHT\\_INCUBATION` \\| `FULL\\_ATOM`"
    parsed = parse_response(
        '{"has_normative_statements":true,"assertions":' + f'[{{"assertion":"{cell}","scopes":["lock.lifecycle"]}}]}}'
    )
    assert parsed.has_normative_statements is True
    assert parsed.assertions[0].assertion == cell, "the quoted chunk must survive word for word"


def test_a_genuinely_escaped_backslash_survives_the_repair() -> None:
    """The repair must not eat a backslash the model meant to send.

    ``\\\\|`` is a VALID escape followed by a pipe. Treating its second
    backslash as stray would silently corrupt the quoted assertion — and a
    corrupted quote is worse than a rejected one, because it parses.

    The stray ``\\|`` in the same string survives as the two characters it
    was; the genuine ``\\\\\\\\`` still decodes to one backslash.
    """
    parsed = parse_response(
        '{"has_normative_statements":true,"assertions":'
        '[{"assertion":"path C:\\\\\\\\dir \\| next","scopes":["lock.lifecycle"]}]}'
    )
    assert parsed.assertions[0].assertion == "path C:\\\\dir \\| next"


def test_regex_fallback_rejects_contradictory_json_and_verdict() -> None:
    raw = (
        '{"has_normative_statements":false,"assertions":'
        '[{"assertion":"The system must retain locks.","scopes":["lock.lifecycle"]}],'
        '"verdict":"PASS"}'
    )
    with pytest.raises(ResponseParseError):
        parse_response(raw)


def test_regex_fallback_rejects_duplicate_classification_flags() -> None:
    with pytest.raises(ResponseParseError):
        parse_response("has_normative_statements: false; has_normative_statements: true")
