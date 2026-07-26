"""Contract test binding the MCP tool surface to FK-13 §13.4.1 / §13.9.5 (AC8).

The expectations below are transcribed from the FK-13 parameter/return tables, so
a drift in either direction (code or concept) breaks this test. The ADVERTISED
``inputSchema`` is asserted against the same table, because the schema and the
strict validators are generated from one contract SSOT.
"""

from __future__ import annotations

import pytest

from agentkit.backend.vectordb.contracts import (
    CONCEPT_STATUSES,
    DEFAULT_LIMIT,
    MAX_LIMIT,
    TOOL_NAMES,
    contract_for,
)
from agentkit.integration_clients.vectordb.weaviate_adapter import SEARCH_MODES

# FK-13 §13.4.1 (story_search / story_list_sources / story_sync) and §13.9.5
# (concept_search / concept_sync): (required, optional, return fields).
FK13_TOOL_TABLES: dict[str, tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]] = {
    "story_search": (
        ("query",),
        ("search_mode", "project_id", "status", "story_type", "limit"),
        (
            "story_id", "title", "status", "story_type", "source_type", "module",
            "epic", "section_heading", "score", "snippet",
        ),
    ),
    "story_list_sources": (
        (),
        ("project_id",),
        # D1 (po-decisions.md) fixed a MINIMAL, provable shape ("Mindestens ...").
        # AG3-177 adds the non-authoritative subset as a contract-conforming
        # extension: the ratified residual has to be detectable where an agent or an
        # operator actually looks, and the completion set this listing already reads
        # makes it free.
        (
            "project_id", "source_type", "producer", "source_count",
            "chunk_count", "last_revision", "stale_chunk_count",
        ),
    ),
    "story_sync": (
        (),
        ("project_id", "full_reindex"),
        ("project_id", "synced_sources", "written", "deleted", "corpus_revision"),
    ),
    "concept_search": (
        ("query",),
        (
            # `authority_scope` is the ratified §13.9.5 ranking input (D7).
            "search_mode", "project_id", "concept_id", "module", "authority_scope",
            "is_appendix", "concept_status", "limit",
        ),
        (
            "concept_id", "title", "module", "section_heading", "section_number",
            "is_appendix", "parent_concept_id", "defers_to", "authority_over",
            "normative_rules", "concept_status", "score", "snippet",
        ),
    ),
    "concept_sync": (
        (),
        ("project_id", "full_reindex", "concept_path"),
        ("project_id", "synced_sources", "written", "deleted", "corpus_revision"),
    ),
}

#: FK-13 parameter types (String / Boolean / Integer) as JSON-Schema types.
FK13_PARAM_TYPES: dict[str, str] = {
    "query": "string",
    "search_mode": "string",
    "project_id": "string",
    "status": "string",
    "story_type": "string",
    "limit": "integer",
    "full_reindex": "boolean",
    "concept_id": "string",
    "module": "string",
    "authority_scope": "string",
    "is_appendix": "boolean",
    # D8: a status SET, not a single value.
    "concept_status": "array",
    "concept_path": "string",
}


def test_exactly_the_five_fk13_tools_exist() -> None:
    assert set(TOOL_NAMES) == set(FK13_TOOL_TABLES)


@pytest.mark.parametrize("name", sorted(FK13_TOOL_TABLES))
def test_tool_parameters_and_return_fields_match_fk13(name: str) -> None:
    required, optional, return_fields = FK13_TOOL_TABLES[name]
    contract = contract_for(name)
    assert contract.required_params == required
    assert set(contract.optional_params) == set(optional)
    assert set(contract.return_fields) == set(return_fields)


@pytest.mark.parametrize("name", sorted(FK13_TOOL_TABLES))
def test_advertised_input_schema_matches_fk13(name: str) -> None:
    required, optional, _returns = FK13_TOOL_TABLES[name]
    schema = contract_for(name).input_schema()
    assert schema["type"] == "object"
    assert schema["required"] == list(required)
    assert set(schema["properties"]) == set(required) | set(optional)
    # Unknown arguments are refused by the advertised contract itself.
    assert schema["additionalProperties"] is False
    for param, advertised in schema["properties"].items():
        assert advertised["type"] == FK13_PARAM_TYPES[param], param
        # An optional parameter is NEVER nullable: an explicit JSON null is a
        # named error, only an ABSENT key falls back to the default (R13).
        assert "null" not in str(advertised["type"])


def test_enum_and_bound_defaults_match_fk13() -> None:
    search_mode = contract_for("story_search").input_schema()["properties"]["search_mode"]
    assert search_mode["enum"] == list(SEARCH_MODES) == ["hybrid", "vector", "keyword"]
    concept_status = contract_for("concept_search").input_schema()["properties"]["concept_status"]
    # D8: the enum moved to the ITEM schema; the parameter itself is a set with at
    # least one entry and no duplicates -- exactly what the strict validator enforces.
    assert concept_status["type"] == "array"
    assert concept_status["items"] == {
        "type": "string",
        "enum": list(CONCEPT_STATUSES),
    }
    assert list(CONCEPT_STATUSES) == ["active", "draft", "archived"]
    assert concept_status["minItems"] == 1
    assert concept_status["uniqueItems"] is True
    limit = contract_for("story_search").input_schema()["properties"]["limit"]
    assert limit["minimum"] == 1
    assert limit["maximum"] == MAX_LIMIT
    assert DEFAULT_LIMIT == 10  # FK-13 §13.4.1 "Max Ergebnisse (Default: 10)"
