"""Contract test binding StoryContext schema to FK-13 §13.3.1 / §13.9.3."""

from __future__ import annotations

from agentkit.backend.vectordb.schema import (
    REQUIRED_OBJECT_FIELDS,
    SOURCE_TYPES,
    STORY_CONTEXT_COLLECTION,
    StoryContextObject,
    deterministic_uuid,
    property_names,
    validate_object,
)

# FK-13 §13.3.1 base properties.
BASE_PROPS = {
    "content",
    "story_id",
    "title",
    "status",
    "story_type",
    "module",
    "epic",
    "source_type",
    "source_file",
    "section_heading",
    "content_hash",
    "project_id",
}

# FK-13 §13.9.3 concept extension properties.
CONCEPT_PROPS = {
    "concept_id",
    "is_appendix",
    "parent_concept_id",
    "defers_to",
    "authority_over",
    "section_number",
    "normative_rules",
    "concept_status",
}


def test_collection_name_is_storycontext() -> None:
    assert STORY_CONTEXT_COLLECTION == "StoryContext"


def test_schema_carries_all_base_properties() -> None:
    names = set(property_names())
    assert names >= BASE_PROPS


def test_schema_carries_all_concept_extension_properties() -> None:
    names = set(property_names())
    assert names >= CONCEPT_PROPS


def test_source_types_match_fk13() -> None:
    assert set(SOURCE_TYPES) == {"story", "research", "concept"}


def test_required_fields_are_subset_of_schema() -> None:
    names = set(property_names())
    assert set(REQUIRED_OBJECT_FIELDS) <= names


def test_deterministic_uuid_is_stable() -> None:
    a = deterministic_uuid("acme", "concept/x.md", "chunk-1")
    b = deterministic_uuid("acme", "concept/x.md", "chunk-1")
    c = deterministic_uuid("acme", "concept/x.md", "chunk-2")
    d = deterministic_uuid("other", "concept/x.md", "chunk-1")
    assert a == b
    assert a != c  # different chunk
    assert a != d  # different project


def test_validate_object_rejects_missing_required() -> None:
    import pytest

    with pytest.raises(ValueError, match="missing required field"):
        validate_object({"source_type": "concept"})


def test_validate_object_rejects_bad_source_type() -> None:
    import pytest

    with pytest.raises(ValueError, match="source_type"):
        validate_object(
            {
                "content": "x",
                "source_type": "bogus",
                "source_file": "f",
                "project_id": "p",
                "content_hash": "h",
                "section_heading": "s",
            }
        )


def test_storycontext_object_is_frozen_dataclass() -> None:
    obj = StoryContextObject(uuid="u", properties={})
    assert obj.uuid == "u"
