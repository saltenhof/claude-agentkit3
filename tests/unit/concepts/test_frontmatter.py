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


def test_deferral_override_note_is_strictly_typed() -> None:
    fm = _GOOD.replace("    reason: base", "    reason: base\n    override_note: freeze moved")
    model = ConceptFrontmatter.from_mapping(parse_frontmatter_block(fm))
    entry = model.defers_to[0]
    assert not isinstance(entry, str)
    assert entry.override_note == "freeze moved"


def test_deferral_override_note_rejects_non_string() -> None:
    fm = _GOOD.replace("    reason: base", "    reason: base\n    override_note: 23")
    with pytest.raises(FrontmatterError):
        ConceptFrontmatter.from_mapping(parse_frontmatter_block(fm))


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


def test_unmodelled_field_is_ignored_not_rejected() -> None:
    """N20: FK-13 §13.9.6 fixes the MANDATORY fields, it does not close the key set.

    FK-13's own document carries ``cross_cutting``/``formal_scope`` and the
    formal-spec corpus adds ``spec_kind``/``version``/``prose_refs``; rejecting
    unmodelled keys made the parser unable to read the very corpus it governs.
    Unmodelled keys are therefore IGNORED -- while every MODELLED field stays
    strictly typed (see the tests below).
    """
    fm = _GOOD + "cross_cutting: true\nformal_scope: prose-only\nspec_kind: entities\n"
    parsed = ConceptFrontmatter.from_mapping(parse_frontmatter_block(fm))
    assert parsed.concept_id == "FK-13"
    assert not hasattr(parsed, "cross_cutting")


def test_typo_in_a_mandatory_field_still_fails_closed() -> None:
    """Ignoring unmodelled keys must not hide a misspelled MANDATORY field."""
    fm = _GOOD.replace("title:", "titel:")
    with pytest.raises(FrontmatterError, match="title"):
        ConceptFrontmatter.from_mapping(parse_frontmatter_block(fm))


@pytest.mark.parametrize("field_name", ["parent_concept_id", "superseded_by", "section_number"])
def test_explicit_null_for_an_optional_field_means_empty(field_name: str) -> None:
    """N20: FK-13 §13.9.6's own example writes ``parent_concept_id:`` with no value.

    An explicit YAML null for an OPTIONAL string field is the documented way to say
    "absent"; it is not a wrong type. A null in a MANDATORY field still fails.
    """
    fm = _GOOD + f"{field_name}:\n"
    parsed = ConceptFrontmatter.from_mapping(parse_frontmatter_block(fm))
    assert getattr(parsed, field_name) == ""


def test_explicit_null_in_a_mandatory_field_still_fails_closed() -> None:
    fm = _GOOD.replace("status: active", "status:")
    with pytest.raises(FrontmatterError):
        ConceptFrontmatter.from_mapping(parse_frontmatter_block(fm))


def test_non_string_in_tags_fails_closed() -> None:
    fm = _GOOD.replace("tags: [vektordb]", "tags: [vektordb, 42]")
    with pytest.raises(FrontmatterError, match="must be a string"):
        ConceptFrontmatter.from_mapping(parse_frontmatter_block(fm))


def test_supersedes_accepts_simple_and_scope_qualified_canonical_forms() -> None:
    fm = (
        _GOOD
        + "supersedes:\n"
        + "  - FK-00\n"
        + "  - target: FK-01\n"
        + "    scope: freeze-position\n"
        + "    reason: freeze moved\n"
    )
    model = ConceptFrontmatter.from_mapping(parse_frontmatter_block(fm))
    assert model.supersedes_targets == ("FK-00", "FK-01")
    assert model.supersedes_full == (
        ("FK-00", "", ""),
        ("FK-01", "freeze-position", "freeze moved"),
    )


@pytest.mark.parametrize(
    "entry",
    (
        "scope: missing-target",
        "target: 23",
        "target: FK-01\n    unknown: forbidden",
    ),
)
def test_malformed_scope_qualified_supersedes_fails_closed(entry: str) -> None:
    fm = _GOOD + f"supersedes:\n  - {entry}\n"
    with pytest.raises(FrontmatterError):
        ConceptFrontmatter.from_mapping(parse_frontmatter_block(fm))
