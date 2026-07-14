"""Strict three-stage W2 response parser tests."""

from __future__ import annotations

import pytest
from concept_governance.parser import ResponseParseError, parse_response


def test_regex_fallback_recovers_structured_fields_without_deciding_policy() -> None:
    parsed = parse_response(
        'has\\_normative\\_statements: true; '
        '"assertion": "The system must retain locks.", "scopes": ["lock.lifecycle"]'
    )
    assert parsed.has_normative_statements is True
    assert parsed.assertions[0].scopes == ("lock.lifecycle",)


def test_escaped_underscore_json_is_strictly_revalidated() -> None:
    parsed = parse_response('{"has\\_normative\\_statements":false,"assertions":[]}')
    assert parsed.has_normative_statements is False


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
