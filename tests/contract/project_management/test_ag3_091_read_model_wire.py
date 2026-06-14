"""Contract tests: AG3-091 read-model wire shapes.

Validates the six new AG3-091 wire models against their formal spec
(``frontend-contracts.entity.*``) by parsing the canonical entities.md
and cross-checking field sets.  Any drift — missing OR extra field — fails
the test (FK-72 §72.14.3, AC8).

Additionally validates:
- mode-lock and counters bindings (project_mode_lock, story_counters)
- FK-91 §91.1a catalog endpoint presence for each new endpoint
- 405 contract for mutation attempts on read-only endpoints (AC1/AC5)
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from agentkit.project_management.views import (
    ExecutionLimits,
    ProjectModeLock,
    StoryAreEvidence,
    StoryAreLinkView,
    StoryCounters,
    StoryCoverageAcceptance,
    StoryFlowPhase,
    StoryFlowSnapshot,
    StoryFlowSubstep,
)

# ---------------------------------------------------------------------------
# Parse formal entity definitions from entities.md (MAJOR fix: no hardcoding)
# ---------------------------------------------------------------------------

_ENTITIES_MD = (
    Path(__file__).parents[3]
    / "concept"
    / "formal-spec"
    / "frontend-contracts"
    / "entities.md"
)

_FK91_CATALOG_MD = (
    Path(__file__).parents[3]
    / "concept"
    / "technical-design"
    / "91_api_event_katalog.md"
)


def _parse_entities_md() -> dict[str, frozenset[str]]:
    """Extract required field sets from entities.md YAML block.

    Returns:
        Mapping of entity id -> frozenset of attribute names (required only).
    """
    text = _ENTITIES_MD.read_text(encoding="utf-8")
    # Extract the YAML block between ```yaml ... ```
    match = re.search(r"```yaml\n(.*?)```", text, re.DOTALL)
    assert match, f"No YAML block found in {_ENTITIES_MD}"
    raw_yaml = match.group(1)
    spec = yaml.safe_load(raw_yaml)
    entities: dict[str, frozenset[str]] = {}
    for entity in spec.get("entities", []):
        entity_id = entity["id"]
        attrs = entity.get("attributes", [])
        # We track ALL attribute names (both required and optional)
        # to detect any extra fields the wire model adds beyond the spec.
        # For the contract: wire model fields must be a SUBSET of spec attributes
        # (no undeclared extras), and all required spec fields must be present.
        all_attr_names = frozenset(a["name"] for a in attrs)
        entities[entity_id] = all_attr_names
    return entities


# Build entity map at import time (fast; reads a small file once)
_SPEC_ENTITIES = _parse_entities_md()


def _spec_fields(entity_id: str) -> frozenset[str]:
    """Return the formal attribute set for an entity; fail clearly when absent."""
    assert entity_id in _SPEC_ENTITIES, (
        f"Entity {entity_id!r} not found in entities.md — "
        f"available: {sorted(_SPEC_ENTITIES.keys())}"
    )
    return _SPEC_ENTITIES[entity_id]


# ---------------------------------------------------------------------------
# FK-91 §91.1a catalog verification helpers
# ---------------------------------------------------------------------------

_AG3_091_ENDPOINTS = [
    "/v1/projects/{project_key}/execution-input/limits",
    "/v1/projects/{project_key}/mode-lock",
    "/v1/projects/{project_key}/stories/counters",
    "/v1/projects/{project_key}/stories/{story_id}/flow",
    "/v1/projects/{project_key}/coverage/stories/{story_id}/acceptance",
    "/v1/projects/{project_key}/coverage/stories/{story_id}/are-evidence",
]


def _fk91_catalog_text() -> str:
    return _FK91_CATALOG_MD.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Field-set contract tests (model -> spec)
# ---------------------------------------------------------------------------


def test_execution_limits_fields_match_spec() -> None:
    """ExecutionLimits wire fields must exactly match formal execution_limits entity."""
    spec = _spec_fields("frontend-contracts.entity.execution_limits")
    model = frozenset(ExecutionLimits.model_fields.keys())
    assert model == spec, (
        f"ExecutionLimits field mismatch.\n"
        f"  In model only (extra): {sorted(model - spec)}\n"
        f"  In spec only (missing): {sorted(spec - model)}"
    )


def test_story_flow_snapshot_fields_match_spec() -> None:
    """StoryFlowSnapshot wire fields must exactly match formal story_flow_snapshot entity."""
    spec = _spec_fields("frontend-contracts.entity.story_flow_snapshot")
    model = frozenset(StoryFlowSnapshot.model_fields.keys())
    assert model == spec, (
        f"StoryFlowSnapshot field mismatch.\n"
        f"  In model only (extra): {sorted(model - spec)}\n"
        f"  In spec only (missing): {sorted(spec - model)}"
    )


def test_story_flow_phase_fields_match_spec() -> None:
    """StoryFlowPhase wire fields must exactly match formal story_flow_phase entity."""
    spec = _spec_fields("frontend-contracts.entity.story_flow_phase")
    model = frozenset(StoryFlowPhase.model_fields.keys())
    assert model == spec, (
        f"StoryFlowPhase field mismatch.\n"
        f"  In model only (extra): {sorted(model - spec)}\n"
        f"  In spec only (missing): {sorted(spec - model)}"
    )


def test_story_flow_substep_fields_match_spec() -> None:
    """StoryFlowSubstep wire fields must exactly match formal story_flow_substep entity."""
    spec = _spec_fields("frontend-contracts.entity.story_flow_substep")
    model = frozenset(StoryFlowSubstep.model_fields.keys())
    assert model == spec, (
        f"StoryFlowSubstep field mismatch.\n"
        f"  In model only (extra): {sorted(model - spec)}\n"
        f"  In spec only (missing): {sorted(spec - model)}"
    )


def test_story_coverage_acceptance_fields_match_spec() -> None:
    """StoryCoverageAcceptance wire fields must match formal story_coverage_acceptance entity."""
    spec = _spec_fields("frontend-contracts.entity.story_coverage_acceptance")
    model = frozenset(StoryCoverageAcceptance.model_fields.keys())
    assert model == spec, (
        f"StoryCoverageAcceptance field mismatch.\n"
        f"  In model only (extra): {sorted(model - spec)}\n"
        f"  In spec only (missing): {sorted(spec - model)}"
    )


def test_story_are_evidence_fields_match_spec() -> None:
    """StoryAreEvidence wire fields must match formal story_are_evidence entity."""
    spec = _spec_fields("frontend-contracts.entity.story_are_evidence")
    model = frozenset(StoryAreEvidence.model_fields.keys())
    assert model == spec, (
        f"StoryAreEvidence field mismatch.\n"
        f"  In model only (extra): {sorted(model - spec)}\n"
        f"  In spec only (missing): {sorted(spec - model)}"
    )


def test_mode_lock_fields_match_spec() -> None:
    """ProjectModeLock wire fields must match formal project_mode_lock entity (AC2 binding)."""
    spec = _spec_fields("frontend-contracts.entity.project_mode_lock")
    model = frozenset(ProjectModeLock.model_fields.keys())
    assert model == spec, (
        f"ProjectModeLock field mismatch.\n"
        f"  In model only (extra): {sorted(model - spec)}\n"
        f"  In spec only (missing): {sorted(spec - model)}"
    )


def test_story_counters_fields_match_spec() -> None:
    """StoryCounters wire fields must match formal story_counters entity (AC3 binding)."""
    spec = _spec_fields("frontend-contracts.entity.story_counters")
    model = frozenset(StoryCounters.model_fields.keys())
    assert model == spec, (
        f"StoryCounters field mismatch.\n"
        f"  In model only (extra): {sorted(model - spec)}\n"
        f"  In spec only (missing): {sorted(spec - model)}"
    )


def test_story_are_link_view_is_not_a_formal_entity() -> None:
    """story_are_link_view must NOT be a top-level formal entity (ERROR F fix).

    The inline object shape of story_are_evidence.linked_requirements is
    implemented by StoryAreLinkView in code but must NOT have a separate
    formal entity entry in entities.md (it duplicated AG3-077 StoryAreLink).
    """
    assert "frontend-contracts.entity.story_are_link_view" not in _SPEC_ENTITIES, (
        "story_are_link_view was re-added to entities.md as a top-level entity. "
        "ERROR F: this duplicates the AG3-077 StoryAreLink shape. Remove it."
    )


# ---------------------------------------------------------------------------
# FK-91 §91.1a catalog: every AG3-091 endpoint must appear in the catalog
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("endpoint", _AG3_091_ENDPOINTS)
def test_endpoint_present_in_fk91_catalog(endpoint: str) -> None:
    """Each AG3-091 endpoint must have a catalog entry in FK-91 §91.1a."""
    catalog = _fk91_catalog_text()
    assert endpoint in catalog, (
        f"Endpoint {endpoint!r} not found in FK-91 catalog "
        f"({_FK91_CATALOG_MD}). Every AG3-091 endpoint requires a "
        "catalog entry (FK-72 §72.14.3, AC8)."
    )


# ---------------------------------------------------------------------------
# Wire serialization contract tests (model_dump -> dict)
# ---------------------------------------------------------------------------


def test_execution_limits_zero_caps_wire_shape() -> None:
    model = ExecutionLimits(
        project_key="my-project",
        repo_parallel_cap=0,
        merge_risk_cap=0,
        max_parallel_agent_cap=0,
        llm_pool_cap=0,
        ci_capacity_cap=0,
    )
    wire = model.model_dump(mode="json")
    assert wire == {
        "project_key": "my-project",
        "repo_parallel_cap": 0,
        "merge_risk_cap": 0,
        "max_parallel_agent_cap": 0,
        "llm_pool_cap": 0,
        "ci_capacity_cap": 0,
    }
    assert set(wire.keys()) == _spec_fields("frontend-contracts.entity.execution_limits")


def test_story_flow_snapshot_minimal_wire_shape() -> None:
    snapshot = StoryFlowSnapshot(
        story_id="AG3-001",
        mode="standard",
        phases=[],
    )
    wire = snapshot.model_dump(mode="json")
    assert wire == {
        "story_id": "AG3-001",
        "mode": "standard",
        "phases": [],
    }


def test_story_flow_phase_wire_shape_optional_none() -> None:
    phase = StoryFlowPhase(
        phase="setup",
        state="pending",
        substeps=[],
    )
    wire = phase.model_dump(mode="json")
    assert wire["phase"] == "setup"
    assert wire["state"] == "pending"
    assert wire["state_reason"] is None
    assert wire["iteration"] is None
    assert wire["iteration_loop_group"] is None
    assert wire["substeps"] == []


def test_story_flow_substep_wire_shape_optional_none() -> None:
    substep = StoryFlowSubstep(
        substep="init",
        state="done",
        optional=False,
    )
    wire = substep.model_dump(mode="json")
    assert wire["substep"] == "init"
    assert wire["state"] == "done"
    assert wire["optional"] is False
    assert wire["loop_group"] is None
    assert wire["loop_position"] is None
    assert wire["loop_size"] is None


def test_story_coverage_acceptance_wire_shape() -> None:
    model = StoryCoverageAcceptance(
        story_id="AG3-010",
        project_key="proj-x",
        acceptance_criteria=["AC1"],
        linked_requirements=["ARE-1"],
    )
    wire = model.model_dump(mode="json")
    assert set(wire.keys()) == _spec_fields("frontend-contracts.entity.story_coverage_acceptance")
    assert wire["acceptance_criteria"] == ["AC1"]
    assert wire["linked_requirements"] == ["ARE-1"]


def test_story_are_evidence_wire_shape() -> None:
    link_view = StoryAreLinkView(
        are_item_id="ARE-1",
        kind="addresses",
        coverage_status="covered",
        evidence_paths=["tests/test_foo.py::test_bar", "abc123"],
    )
    model = StoryAreEvidence(
        story_id="AG3-020",
        project_key="proj-y",
        linked_requirements=[link_view],
    )
    wire = model.model_dump(mode="json")
    assert set(wire.keys()) == _spec_fields("frontend-contracts.entity.story_are_evidence")
    assert wire["linked_requirements"] == [
        {
            "are_item_id": "ARE-1",
            "kind": "addresses",
            "coverage_status": "covered",
            "evidence_paths": ["tests/test_foo.py::test_bar", "abc123"],
        }
    ]


def test_story_are_link_view_fields_are_inline_object_fields() -> None:
    """StoryAreLinkView (code class) carries exactly 4 inline fields.

    This is the wire representation used inside story_are_evidence.linked_requirements.
    It is NOT a standalone formal entity (see test_story_are_link_view_is_not_a_formal_entity).

    AG3-091 ERROR 3 fix: ``evidence_paths`` added (FK-40 §40.5b.6 / story §2.1.2).
    """
    expected_fields = frozenset({"are_item_id", "kind", "coverage_status", "evidence_paths"})
    model_fields = frozenset(StoryAreLinkView.model_fields.keys())
    assert model_fields == expected_fields, (
        f"StoryAreLinkView inline fields mismatch.\n"
        f"  In model only (extra): {sorted(model_fields - expected_fields)}\n"
        f"  In expected only (missing): {sorted(expected_fields - model_fields)}"
    )


def test_all_models_are_frozen() -> None:
    """Confirm fail-closed frozen contract: no field mutations allowed post-construction.

    Frozen Pydantic v2 models raise ``ValidationError`` (which subclasses
    ``ValueError``) when the Pydantic ``__setattr__`` is invoked.  We trigger
    that via ``setattr(instance, field, value)`` rather than
    ``object.__setattr__``, which bypasses the Pydantic descriptor entirely.
    """
    from pydantic import ValidationError

    limits = ExecutionLimits(
        project_key="p", repo_parallel_cap=0, merge_risk_cap=0,
        max_parallel_agent_cap=0, llm_pool_cap=0, ci_capacity_cap=0,
    )
    with pytest.raises(ValidationError):
        limits.project_key = "mutated"  # type: ignore[misc]

    snapshot = StoryFlowSnapshot(story_id="x", mode="standard", phases=[])
    with pytest.raises(ValidationError):
        snapshot.story_id = "mutated"  # type: ignore[misc]

    coverage = StoryCoverageAcceptance(
        story_id="x", project_key="p",
        acceptance_criteria=[], linked_requirements=[],
    )
    with pytest.raises(ValidationError):
        coverage.story_id = "mutated"  # type: ignore[misc]

    evidence = StoryAreEvidence(story_id="x", project_key="p", linked_requirements=[])
    with pytest.raises(ValidationError):
        evidence.story_id = "mutated"  # type: ignore[misc]

    link_view = StoryAreLinkView(are_item_id="a", kind="addresses", coverage_status="linked")
    with pytest.raises(ValidationError):
        link_view.are_item_id = "mutated"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# mode-lock and counters SSOT binding contract (AC2, AC3)
# ---------------------------------------------------------------------------


def test_mode_lock_no_holder_count() -> None:
    """ProjectModeLock must NOT contain holder_count (formal spec, AC2)."""
    assert "holder_count" not in ProjectModeLock.model_fields, (
        "ProjectModeLock must not expose holder_count. "
        "The formal spec carries only project_key + mode (FK-24 §24.3.3)."
    )


def test_mode_lock_mode_values() -> None:
    """mode field must accept exactly standard, fast, idle."""
    from typing import get_args

    mode_field = ProjectModeLock.model_fields["mode"]
    # Pydantic Literal stores args in annotation
    literal_args = get_args(mode_field.annotation)
    assert set(literal_args) == {"standard", "fast", "idle"}
