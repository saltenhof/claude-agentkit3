"""Tests for the dependency-rebinding invariants (formal.dependency-rebinding)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agentkit.backend.core_types import StoryDependencyKind
from agentkit.backend.execution_planning.entities import StoryDependency
from agentkit.backend.story_split.rebinding import (
    RebindingError,
    plan_rebinding,
)

NOW = datetime(2026, 6, 12, 12, 0, tzinfo=UTC)
HARD = StoryDependencyKind.HARD_STORY_DEPENDENCY


def _edge(story_id: str, depends_on: str, kind: StoryDependencyKind = HARD) -> StoryDependency:
    return StoryDependency(
        story_id=story_id,
        depends_on_story_id=depends_on,
        kind=kind,
        created_at=NOW,
    )


def test_happy_path_rebinds_edge_to_successor() -> None:
    plan = plan_rebinding(
        source_story_id="AK3-042",
        successor_ids=("AK3-107", "AK3-108"),
        rebinding_entries=(("AK3-051", "AK3-042", ("AK3-107",)),),
        existing_edges=(_edge("AK3-051", "AK3-042"),),
    )
    assert plan.removals[0].story_id == "AK3-051"
    assert plan.removals[0].depends_on_story_id == "AK3-042"
    assert plan.additions[0].depends_on_story_id == "AK3-107"
    assert plan.additions[0].kind is HARD


def test_no_stale_cancelled_target_unhandled_inbound_edge_fails() -> None:
    # AK3-060 still points at the cancelled source but the plan rebinds nothing.
    with pytest.raises(RebindingError, match="no_stale_cancelled_target"):
        plan_rebinding(
            source_story_id="AK3-042",
            successor_ids=("AK3-107",),
            rebinding_entries=(("AK3-051", "AK3-042", ("AK3-107",)),),
            existing_edges=(
                _edge("AK3-051", "AK3-042"),
                _edge("AK3-060", "AK3-042"),
            ),
        )


def test_no_silent_drop_rebinding_without_existing_edge_fails() -> None:
    with pytest.raises(RebindingError, match="no_silent_drop"):
        plan_rebinding(
            source_story_id="AK3-042",
            successor_ids=("AK3-107",),
            rebinding_entries=(("AK3-051", "AK3-042", ("AK3-107",)),),
            existing_edges=(),
        )


def test_deterministic_target_selection_is_reproducible() -> None:
    args = {
        "source_story_id": "AK3-042",
        "successor_ids": ("AK3-107", "AK3-108"),
        "rebinding_entries": (("AK3-051", "AK3-042", ("AK3-107", "AK3-108")),),
        "existing_edges": (_edge("AK3-051", "AK3-042"),),
    }
    first = plan_rebinding(**args)  # type: ignore[arg-type]
    second = plan_rebinding(**args)  # type: ignore[arg-type]
    assert first == second
    assert {a.depends_on_story_id for a in first.additions} == {"AK3-107", "AK3-108"}


def test_no_unjustified_fanout_undeclared_target_fails() -> None:
    with pytest.raises(RebindingError, match="no_unjustified_fanout"):
        plan_rebinding(
            source_story_id="AK3-042",
            successor_ids=("AK3-107",),
            rebinding_entries=(("AK3-051", "AK3-042", ("AK3-999",)),),
            existing_edges=(_edge("AK3-051", "AK3-042"),),
        )


def test_graph_integrity_rejects_duplicate_active_edge() -> None:
    # AK3-051 already depends on AK3-107; rebinding its source edge onto AK3-107
    # would create a duplicate active edge.
    with pytest.raises(RebindingError, match="duplicate active edge"):
        plan_rebinding(
            source_story_id="AK3-042",
            successor_ids=("AK3-107",),
            rebinding_entries=(("AK3-051", "AK3-042", ("AK3-107",)),),
            existing_edges=(
                _edge("AK3-051", "AK3-042"),
                _edge("AK3-051", "AK3-107"),
            ),
        )


def test_graph_integrity_rejects_cycle() -> None:
    # AK3-107 already depends on AK3-051; rebinding AK3-051 -> AK3-107 closes a
    # cycle AK3-051 -> AK3-107 -> AK3-051.
    with pytest.raises(RebindingError, match="cycle"):
        plan_rebinding(
            source_story_id="AK3-042",
            successor_ids=("AK3-107",),
            rebinding_entries=(("AK3-051", "AK3-042", ("AK3-107",)),),
            existing_edges=(
                _edge("AK3-051", "AK3-042"),
                _edge("AK3-107", "AK3-051"),
            ),
        )
