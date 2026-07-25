"""Contract test binding StoryContext schema to FK-13 §13.3.1 / §13.9.3."""

from __future__ import annotations

from agentkit.backend.vectordb.schema import (
    REQUIRED_OBJECT_FIELDS,
    REQUIRED_SEARCH_PROPERTIES,
    SOURCE_TYPES,
    STORY_CONTEXT_COLLECTION,
    StoryContextObject,
    deterministic_uuid,
    property_data_type,
    property_names,
    search_property_spec,
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


def test_schema_carries_the_ownership_marker() -> None:
    """FK-13 §13.3.1 `owning_claim` (D9): filterable, whole-value, NOT embedded."""
    from agentkit.backend.vectordb.schema import (
        FK13_VECTOR_SOURCE_PROPERTIES,
        OWNING_CLAIM_PROPERTY,
        property_spec,
    )

    assert OWNING_CLAIM_PROPERTY in set(property_names())
    spec = property_spec(OWNING_CLAIM_PROPERTY)
    assert spec.data_type == "TEXT"
    assert spec.filterable, "the destructive delete filters on it storage-side"
    assert not spec.vectorized, "an ownership marker must never enter the embedding"
    assert spec.tokenization == "FIELD", "the condition compares the whole value"
    assert OWNING_CLAIM_PROPERTY not in FK13_VECTOR_SOURCE_PROPERTIES
    # It is an operational marker, not part of any tool's return contract.
    for source_type in SOURCE_TYPES:
        names = {name for name, _dt, _ne in search_property_spec(source_type)}
        assert OWNING_CLAIM_PROPERTY not in names


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
    obj = StoryContextObject(uuid="u", chunk_id="c", properties={})
    assert obj.uuid == "u"
    assert obj.chunk_id == "c"


def test_object_carries_its_identity_input_for_verification() -> None:
    """N13: the chunk_id is first class so the uuid derivation is verifiable."""
    import dataclasses

    fields = {f.name for f in dataclasses.fields(StoryContextObject)}
    assert fields == {"uuid", "chunk_id", "properties"}
    obj = StoryContextObject(
        uuid=deterministic_uuid("acme", "concept/x.md", "chunk-1"),
        chunk_id="chunk-1",
        properties={},
    )
    assert obj.uuid == deterministic_uuid("acme", "concept/x.md", obj.chunk_id)


def test_search_profiles_cover_every_source_type() -> None:
    """The retrieval profile is per source_type and part of the schema (N11)."""
    assert set(REQUIRED_SEARCH_PROPERTIES) == set(SOURCE_TYPES)
    schema_names = set(property_names())
    for source_type in SOURCE_TYPES:
        spec = search_property_spec(source_type)
        names = {name for name, _dt, _ne in spec}
        assert names <= schema_names
        # The multi-tenant discriminator and the corpus identity are mandatory.
        mandatory = {name for name, _dt, non_empty in spec if non_empty}
        assert {"project_id", "source_file", "source_type", "content"} <= mandatory
        # Data types come from the schema declaration, never from the caller.
        for name, data_type, _ne in spec:
            assert data_type == property_data_type(name)


def test_concept_profile_requires_the_concept_extension() -> None:
    names = {name for name, _dt, _ne in search_property_spec("concept")}
    assert names >= CONCEPT_PROPS
    # FK-13 §13.9.3: the concept-ONLY properties are populated for concepts only,
    # so a story hit must NOT be required to carry them. (``section_number`` is
    # structural and produced by the chunker for every source type.)
    concept_only = CONCEPT_PROPS - {"section_number"}
    story_names = {name for name, _dt, _ne in search_property_spec("story")}
    assert not (concept_only & story_names)


def test_unknown_source_type_profile_is_fail_closed() -> None:
    import pytest

    with pytest.raises(ValueError, match="unknown source_type"):
        search_property_spec("bogus")
    with pytest.raises(ValueError, match="not a StoryContext property"):
        property_data_type("nope")
