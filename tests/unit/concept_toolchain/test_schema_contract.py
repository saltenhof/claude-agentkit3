"""Parity contract: shipped JSON Schemas mirror the runmodel catalogs (FK-78 78.14).

The Python validators are the single source of truth; the schema files
are documenting artifacts kept congruent by this test (required key
sets, enum values, and fail-closed additionalProperties).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from concept_toolchain import runmodel
from tests.unit.concept_toolchain.conftest import TOOLS_DIR

if TYPE_CHECKING:
    from collections.abc import Mapping

SCHEMAS_DIR = TOOLS_DIR / "concept_toolchain" / "schemas"

#: schema file -> (top-level required keys, {json-pointer: enum tuple}).
CASES: dict[str, tuple[tuple[str, ...], dict[str, tuple[str, ...]]]] = {
    "run.schema.json": (
        runmodel.RUN_KEYS,
        {
            "properties.state.enum": runmodel.RUN_STATES,
            "properties.profile.enum": runmodel.RUN_PROFILES,
            "properties.data_class.enum": runmodel.DATA_CLASSES,
            "properties.participants.items.properties.spawn_mode.enum": runmodel.SPAWN_MODES,
            "properties.participants.items.properties.status.enum": runmodel.PARTICIPANT_STATUSES,
        },
    ),
    "lease.schema.json": (runmodel.LEASE_KEYS, {}),
    "round.schema.json": (
        runmodel.ROUND_KEYS,
        {"properties.participants.items.properties.outcome.enum": runmodel.ROUND_OUTCOMES},
    ),
    "coverage-plan.schema.json": (runmodel.COVERAGE_PLAN_KEYS, {}),
    "promotion-manifest.schema.json": (
        runmodel.MANIFEST_KEYS,
        {
            "properties.scopes.items.properties.promotion_disposition.enum": runmodel.PROMOTION_DISPOSITIONS,
            "properties.scope_locks.items.properties.backend.enum": runmodel.LOCK_BACKENDS,
            "properties.semantic_gates.items.properties.gate.enum": runmodel.SEMANTIC_GATES,
            "properties.semantic_gates.items.properties.status.enum": runmodel.SEMANTIC_GATE_STATUSES,
            "properties.required_registry_edges.items.oneOf.1.properties.kind.enum": runmodel.REGISTRY_EDGE_KINDS,
        },
    ),
    "lock-evidence.schema.json": (
        runmodel.LOCK_EVIDENCE_KEYS,
        {"properties.backend.enum": ("git-remote",)},
    ),
    "mutex.schema.json": (runmodel.MUTEX_KEYS, {}),
    "projection-receipt.schema.json": (
        runmodel.RECEIPT_KEYS,
        {"properties.verdict.enum": runmodel.RECEIPT_VERDICTS},
    ),
    "declassification-receipt.schema.json": (
        runmodel.DECLASSIFICATION_KEYS,
        {"properties.target_class.enum": ("open", "internal")},
    ),
    "scope-lock.schema.json": (
        runmodel.SCOPE_LOCK_KEYS,
        {"properties.backend.enum": runmodel.LOCK_BACKENDS},
    ),
    "projection-manifest.schema.json": (
        runmodel.PROJECTION_MANIFEST_KEYS,
        {
            "properties.entries.items.properties.lifecycle.enum": runmodel.LIFECYCLES,
            "properties.entries.items.properties.assertion_status.enum": runmodel.ASSERTION_STATUSES,
            "properties.entries.items.properties.lifecycle_source.properties.status.enum": runmodel.DECISION_STATUSES,
            "properties.entries.items.properties.required_projections.items.properties.kind.enum": runmodel.PROJECTION_KINDS,
            "properties.entries.items.properties.required_projections.items.properties.target_mode.enum": (
                runmodel.TARGET_MODES
            ),
            "properties.entries.items.properties.required_projections.items.properties.equivalence_status.enum": (
                runmodel.EQUIVALENCE_STATUSES
            ),
        },
    ),
    "request-pack.schema.json": (
        runmodel.REQUEST_PACK_KEYS,
        {"properties.gate.enum": runmodel.SEMANTIC_GATES},
    ),
    "semantic-receipt.schema.json": (
        runmodel.SEMANTIC_RECEIPT_KEYS,
        {
            "properties.gate.enum": runmodel.SEMANTIC_GATES,
            "properties.status.enum": runmodel.SEMANTIC_RECEIPT_STATUSES,
        },
    ),
}


def load_schema(name: str) -> dict[str, object]:
    payload = json.loads((SCHEMAS_DIR / name).read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def resolve_pointer(schema: Mapping[str, object], pointer: str) -> object:
    node: object = schema
    for part in pointer.split("."):
        if part.isdigit() and isinstance(node, list):
            node = node[int(part)]
            continue
        assert isinstance(node, dict), f"cannot descend into {pointer!r} at {part!r}"
        node = node[part]
    return node


def test_every_catalog_case_has_a_schema_file_and_vice_versa() -> None:
    shipped = {entry.name for entry in SCHEMAS_DIR.glob("*.schema.json")}
    assert shipped == set(CASES)


@pytest.mark.parametrize("name", sorted(CASES))
def test_schema_matches_runmodel_catalog(name: str) -> None:
    required, enums = CASES[name]
    schema = load_schema(name)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert sorted(schema["required"]) == sorted(required), name  # type: ignore[arg-type]
    properties = schema["properties"]
    assert isinstance(properties, dict)
    assert set(required) <= set(properties), name
    for pointer, expected in enums.items():
        assert resolve_pointer(schema, pointer) == list(expected), f"{name}: {pointer}"


def test_projection_entry_required_keys_match_catalog() -> None:
    schema = load_schema("projection-manifest.json".replace(".json", ".schema.json"))
    entry = resolve_pointer(schema, "properties.entries.items")
    assert isinstance(entry, dict)
    assert sorted(entry["required"]) == sorted(runmodel.PROJECTION_ENTRY_KEYS)
    properties = entry["properties"]
    assert isinstance(properties, dict)
    assert "covered_scope_ids" in properties  # optional field documented but not required
