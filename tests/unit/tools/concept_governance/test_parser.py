"""Strict three-stage W2 response parser tests."""

from __future__ import annotations

import pytest
from concept_governance.parser import ResponseContractError, ResponseParseError, parse_response


def test_regex_fallback_recovers_source_references_without_deciding_policy() -> None:
    parsed = parse_response(
        'has\\_normative\\_statements: true; "source\\_id": "chunk-1", '
        '"start\\_id": "s000001", "end\\_id": "s000004", '
        '"scopes": ["lock.lifecycle"]'
    )
    assert parsed.has_normative_statements is True
    assert parsed.assertions[0].source_id == "chunk-1"
    assert parsed.assertions[0].start_id == "s000001"
    assert parsed.assertions[0].end_id == "s000004"
    assert parsed.assertions[0].scopes == ("lock.lifecycle",)


def test_regex_fallback_rejects_valid_reference_followed_by_incomplete_reference() -> None:
    raw = (
        'has_normative_statements: true; "source_id": "chunk-1", '
        '"start_id": "s000001", "end_id": "s000004", '
        '"scopes": ["lock.lifecycle"]; "source_id": "chunk-2", '
        '"start_id": "s000005"'
    )

    with pytest.raises(
        ResponseParseError,
        match="normative response contains an incomplete source reference",
    ):
        parse_response(raw)


@pytest.mark.parametrize(
    "raw",
    (
        'has_normative_statements: true; "source_id": "chunk-1", '
        '"start_id": "s000001", "end_id": "s000004", '
        '"scopes": ["lock.lifecycle"]; "source_id"',
        'has_normative_statements: true; "source_id"',
    ),
)
def test_regex_fallback_rejects_every_residual_reference_field_token(raw: str) -> None:
    with pytest.raises(ResponseContractError, match="incomplete source reference"):
        parse_response(raw)


def test_escaped_underscore_json_is_strictly_revalidated() -> None:
    parsed = parse_response('{"has\\_normative\\_statements":false,"assertions":[]}')
    assert parsed.has_normative_statements is False


def test_prefaced_escaped_json_is_extracted_then_strictly_revalidated() -> None:
    parsed = parse_response(
        'Worked for 12s\n\n{"has\\_normative\\_statements":false,"assertions":[]}'
    )
    assert parsed.has_normative_statements is False


def test_regex_fallback_rejects_contradictory_json_and_verdict() -> None:
    raw = (
        '{"has_normative_statements":false,"assertions":'
        '[{"source_id":"chunk-1","start_id":"s000001","end_id":"s000004",'
        '"scopes":["lock.lifecycle"]}],"verdict":"PASS"}'
    )
    with pytest.raises(ResponseParseError):
        parse_response(raw)


def test_regex_fallback_rejects_duplicate_classification_flags() -> None:
    with pytest.raises(ResponseParseError):
        parse_response("has_normative_statements: false; has_normative_statements: true")


def test_two_keys_for_one_field_end_as_a_named_rejection_not_a_traceback() -> None:
    backslash = chr(92)
    alias = '"has' + backslash * 2 + "_normative" + backslash * 2 + '_statements"'
    raw = '{"has_normative_statements":true,' + alias + ':false,"assertions":[]}'

    with pytest.raises(
        ResponseParseError,
        match="carries two keys for field 'has_normative_statements'",
    ):
        parse_response(raw)
