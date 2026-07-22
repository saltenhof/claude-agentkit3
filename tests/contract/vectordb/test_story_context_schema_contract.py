"""Contract: StoryContext properties bind to FK-13 §13.3.1 / §13.9.3 (R14)."""

from __future__ import annotations

import pytest

from agentkit.backend.vectordb.schema import (
    STORY_CONTEXT_PROPERTIES,
    SchemaDriftError,
    ensure_story_context_schema,
    property_names,
)

FK13_REQUIRED = {
    # §13.3.1
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
    # §13.9.3
    "concept_id",
    "is_appendix",
    "parent_concept_id",
    "defers_to",
    "authority_over",
    "section_number",
    "normative_rules",
    "concept_status",
}


def test_schema_contains_all_fk13_properties() -> None:
    names = set(property_names())
    missing = FK13_REQUIRED - names
    assert not missing, f"missing FK-13 properties: {sorted(missing)}"


def test_content_and_title_are_vectorized() -> None:
    by_name = {p.name: p for p in STORY_CONTEXT_PROPERTIES}
    assert by_name["content"].vectorize is True
    assert by_name["title"].vectorize is True
    assert by_name["section_heading"].vectorize is True
    assert by_name["project_id"].vectorize is False
    assert by_name["concept_id"].vectorize is False


def _full_props() -> list[object]:
    class _Prop:
        def __init__(self, name: str, data_type: str, skip: bool, tok: str | None) -> None:
            self.name = name
            self.data_type = data_type
            self.skip_vectorization = skip
            self.tokenization = tok

    return [
        _Prop(p.name, p.data_type, skip=not p.vectorize, tok=p.tokenization)
        for p in STORY_CONTEXT_PROPERTIES
    ]


def test_ensure_schema_create_then_verify_idempotent() -> None:
    """R14: create path, then verify with full introspection (no fail-open)."""

    class _Cfg:
        def __init__(self) -> None:
            self.properties = _full_props()
            self.vector_config = {"vectorizer": "text2vec-transformers"}

    class _CollObj:
        def __init__(self) -> None:
            self.config = self

        def get(self) -> _Cfg:
            return _Cfg()

    class _Coll:
        def __init__(self) -> None:
            self.names: set[str] = set()
            self.created = 0

        def exists(self, name: str) -> bool:
            return name in self.names

        def create(self, **kwargs: object) -> None:
            self.names.add(str(kwargs["name"]))
            self.created += 1

        def get(self, name: str) -> _CollObj:
            return _CollObj()

    class _Client:
        def __init__(self) -> None:
            self.collections = _Coll()

    client = _Client()
    assert ensure_story_context_schema(client) is True
    assert ensure_story_context_schema(client) is False
    assert client.collections.created == 1


def test_ensure_schema_without_introspection_is_error() -> None:
    """R14: exists=True without get/config.get must not silently pass."""

    class _Coll:
        def exists(self, name: str) -> bool:
            return True

        def create(self, **kwargs: object) -> None:
            raise AssertionError("must not create")

    class _Client:
        collections = _Coll()

    with pytest.raises(SchemaDriftError):
        ensure_story_context_schema(_Client())


def test_r14_missing_skip_vectorization_rejected() -> None:
    class _Prop:
        def __init__(self, name: str, data_type: str) -> None:
            self.name = name
            self.data_type = data_type
            # intentionally no skip_vectorization
            self.tokenization = "field"

    props = [_Prop(p.name, p.data_type) for p in STORY_CONTEXT_PROPERTIES]

    class _Cfg:
        properties = props
        vectorizer = "text2vec-transformers"

    class _CollObj:
        config = type("CfgAPI", (), {"get": staticmethod(lambda: _Cfg())})()

    class _Coll:
        def exists(self, name: str) -> bool:
            return True

        def get(self, name: str) -> _CollObj:
            return _CollObj()

    with pytest.raises(SchemaDriftError, match="skip_vectorization"):
        ensure_story_context_schema(type("C", (), {"collections": _Coll()})())


def test_r14_missing_tokenization_rejected() -> None:
    class _Prop:
        def __init__(self, name: str, data_type: str, skip: bool) -> None:
            self.name = name
            self.data_type = data_type
            self.skip_vectorization = skip
            # no tokenization

    props = [
        _Prop(p.name, p.data_type, skip=not p.vectorize)
        for p in STORY_CONTEXT_PROPERTIES
    ]

    class _Cfg:
        properties = props
        vectorizer = "text2vec-transformers"

    class _CollObj:
        config = type("CfgAPI", (), {"get": staticmethod(lambda: _Cfg())})()

    class _Coll:
        def exists(self, name: str) -> bool:
            return True

        def get(self, name: str) -> _CollObj:
            return _CollObj()

    with pytest.raises(SchemaDriftError, match="tokenization"):
        ensure_story_context_schema(type("C", (), {"collections": _Coll()})())


def test_r14_missing_vectorizer_metadata_rejected() -> None:
    class _Cfg:
        properties = _full_props()
        # no vectorizer / vector_config

    class _CollObj:
        config = type("CfgAPI", (), {"get": staticmethod(lambda: _Cfg())})()

    class _Coll:
        def exists(self, name: str) -> bool:
            return True

        def get(self, name: str) -> _CollObj:
            return _CollObj()

    with pytest.raises(SchemaDriftError, match="vectorizer|vector_config"):
        ensure_story_context_schema(type("C", (), {"collections": _Coll()})())
