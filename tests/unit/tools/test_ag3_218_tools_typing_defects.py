"""Regression tests for the defects that surfaced when mypy first saw tools/.

Every case here type-checked as "fine" for as long as ``[tool.mypy]`` named
``packages = ["agentkit"]``: nothing static ever read these files.
"""

from __future__ import annotations

from typing import Any

import pytest
from concept_ingester.discovery import _bc_for, _DomainProjection
from concept_mcp.filters import build_filter
from concept_mcp.server import _chunk_ordering
from weaviate.classes.query import FilterReturn


class _Doc:
    """Minimal stand-in for the SSOT document shape ``_bc_for`` reads."""

    def __init__(self, concept_id: str, *, is_archived: bool = False) -> None:
        self.concept_id = concept_id
        self.is_archived = is_archived


class _Obj:
    """Minimal stand-in for a Weaviate result object."""

    def __init__(self, properties: dict[str, Any] | None) -> None:
        self.properties = properties


def test_unregistered_document_gets_an_empty_string_surface() -> None:
    """The fallback used to return ``False`` into a ``str`` field."""
    projection = _DomainProjection.empty()
    domain, surface, display = _bc_for(_Doc("FK-99"), projection)

    assert (domain, surface, display) == ("", "", "")
    assert isinstance(surface, str)
    assert surface is not False


def test_archived_and_unregistered_documents_agree() -> None:
    """Both 'no bounded context' paths must project the same empty profile."""
    projection = _DomainProjection(by_doc={}, registry_hash="deadbeef")
    archived = _bc_for(_Doc("FK-01", is_archived=True), projection)
    unregistered = _bc_for(_Doc("FK-99"), projection)

    assert archived == unregistered == ("", "", "")


def test_registered_document_keeps_its_projected_profile() -> None:
    projection = _DomainProjection(
        by_doc={"FK-27": ("verify-system", "contract", "Verify System")},
        registry_hash="cafe",
    )
    assert _bc_for(_Doc("FK-27"), projection) == (
        "verify-system",
        "contract",
        "Verify System",
    )


def test_build_filter_returns_a_weaviate_filter_expression() -> None:
    """``Filter`` is the factory; ``FilterReturn`` is what a build produces."""
    built = build_filter({"op": "equal", "property": "layer", "value": "technical"})

    assert built is not None
    assert isinstance(built, FilterReturn)


def test_build_filter_group_returns_a_filter_expression() -> None:
    built = build_filter(
        {
            "op": "and",
            "operands": [
                {"op": "equal", "property": "layer", "value": "formal"},
                {"op": "contains_any", "property": "tags", "value": ["governance"]},
            ],
        }
    )

    assert isinstance(built, FilterReturn)


def test_build_filter_passes_none_through() -> None:
    assert build_filter(None) is None


@pytest.mark.parametrize(
    ("stored", "expected"),
    [({"ordering": 7}, 7), ({"ordering": "12"}, 12), ({"ordering": 3.9}, 3)],
)
def test_chunk_ordering_reads_the_ordinal(stored: dict[str, Any], expected: int) -> None:
    assert _chunk_ordering(_Obj(stored)) == expected


@pytest.mark.parametrize("properties", [None, {}, {"ordering": None}, {"ordering": 0}])
def test_chunk_ordering_defaults_to_zero(properties: dict[str, Any] | None) -> None:
    assert _chunk_ordering(_Obj(properties)) == 0


def test_chunk_ordering_fails_closed_on_a_non_ordinal_value() -> None:
    """A schema drift must not silently reorder a caller's results."""
    with pytest.raises(TypeError, match="not ordinal"):
        _chunk_ordering(_Obj({"ordering": {"unexpected": "mapping"}}))
