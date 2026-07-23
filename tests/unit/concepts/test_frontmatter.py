"""Strict frontmatter parsing tests (FK-13 §13.9.6, AC10 frontmatter axis).

Each AC10 negativematrix case proves fail-closed: NO coercion, NO last-wins,
NO type repair. Real PyYAML + real Pydantic strict model.
"""

from __future__ import annotations

import pytest

from agentkit.concepts.frontmatter import (
    ConceptFrontmatter,
    FrontmatterError,
    parse_frontmatter_block,
    split_frontmatter,
)

_GOOD = """\
concept_id: FK-13
title: Retrieval
module: vectordb
status: active
doc_kind: core
authority_over:
  - scope: vectordb
defers_to:
  - target: FK-11
    scope: llm-evaluator
    reason: base
tags: [vektordb]
"""


def _wrap(fm: str) -> str:
    return f"---\n{fm}---\nbody"


def test_good_frontmatter_parses() -> None:
    fm, body = split_frontmatter(_wrap(_GOOD))
    data = parse_frontmatter_block(fm)
    model = ConceptFrontmatter.from_mapping(data)
    assert model.concept_id == "FK-13"
    assert model.authority_scopes == ("vectordb",)
    assert model.defers_to_targets == ("FK-11",)
    assert model.doc_kind == "core"
    assert body.startswith("body")


def test_missing_frontmatter_returns_empty() -> None:
    fm, body = split_frontmatter("no frontmatter here")
    assert fm == ""
    assert body == "no frontmatter here"


def test_unterminated_frontmatter_fails_closed() -> None:
    with pytest.raises(FrontmatterError, match="never terminated"):
        split_frontmatter("---\nconcept_id: X\nbody without close")


def test_empty_frontmatter_block_fails_closed() -> None:
    with pytest.raises(FrontmatterError, match="empty"):
        split_frontmatter("---\n---\nbody")


def test_duplicate_keys_fails_closed_no_last_wins() -> None:
    fm = "status: active\nstatus: draft\n"
    with pytest.raises(FrontmatterError, match="duplicate YAML key"):
        parse_frontmatter_block(fm)


def test_duplicate_nested_keys_fails_closed() -> None:
    fm = "authority_over:\n  - scope: a\n  - scope: a\n"
    # Nested duplicate scope values are NOT duplicate YAML keys (different list
    # items) -- this parses fine; duplicate-key detection is about YAML mapping
    # keys, validated separately by the authority validator (E-AUTH-001).
    data = parse_frontmatter_block(fm)
    assert len(data["authority_over"]) == 2


def test_duplicate_yaml_mapping_key_in_defers_to() -> None:
    fm = "defers_to:\n  - target: A\n    target: B\n"
    with pytest.raises(FrontmatterError, match="duplicate YAML key"):
        parse_frontmatter_block(fm)


def test_unknown_yaml_tag_fails_closed() -> None:
    fm = "concept_id: !!python/object/apply:os.system ['echo hi']\n"
    with pytest.raises(FrontmatterError, match="not valid YAML"):
        parse_frontmatter_block(fm)


def test_non_finite_number_fails_closed() -> None:
    fm = "title: .inf\n"
    with pytest.raises(FrontmatterError, match="non-finite"):
        parse_frontmatter_block(fm)


def test_nan_number_fails_closed() -> None:
    fm = "title: .nan\n"
    with pytest.raises(FrontmatterError, match="non-finite"):
        parse_frontmatter_block(fm)


def test_lone_surrogate_fails_closed() -> None:
    fm = 'title: "bad\\ud83d"\n'
    with pytest.raises(FrontmatterError, match="surrogate"):
        parse_frontmatter_block(fm)


def test_wrong_scalar_type_for_enum_fails_closed() -> None:
    fm = _GOOD.replace("status: active", "status: [active, draft]")
    with pytest.raises(FrontmatterError, match="active|draft|archived"):
        ConceptFrontmatter.from_mapping(parse_frontmatter_block(fm))


def test_disallowed_enum_value_fails_closed() -> None:
    fm = _GOOD.replace("status: active", "status: published")
    with pytest.raises(FrontmatterError, match="active|draft|archived"):
        ConceptFrontmatter.from_mapping(parse_frontmatter_block(fm))


def test_bool_as_status_rejected_not_coerced() -> None:
    # PyYAML parses 'yes'/'true' to bool; a bool is not a valid status string.
    fm = _GOOD.replace("status: active", "status: yes")
    with pytest.raises(FrontmatterError, match="active|draft|archived"):
        ConceptFrontmatter.from_mapping(parse_frontmatter_block(fm))


def test_missing_required_field_fails_closed() -> None:
    fm = "concept_id: FK-13\ntitle: X\nstatus: active\n"
    with pytest.raises(FrontmatterError, match="doc_kind"):
        ConceptFrontmatter.from_mapping(parse_frontmatter_block(fm))


def test_extra_unknown_field_fails_closed() -> None:
    fm = _GOOD + "bogus_field: nope\n"
    with pytest.raises(FrontmatterError):
        ConceptFrontmatter.from_mapping(parse_frontmatter_block(fm))


def test_non_string_in_tags_fails_closed() -> None:
    fm = _GOOD.replace("tags: [vektordb]", "tags: [vektordb, 42]")
    with pytest.raises(FrontmatterError, match="must be a string"):
        ConceptFrontmatter.from_mapping(parse_frontmatter_block(fm))
