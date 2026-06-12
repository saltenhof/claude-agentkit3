"""Tests for the typed split-plan/record/lineage models (AG3-072)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from agentkit.story_context_manager.terminal_state import (
    ExitClass,
    TerminalState,
)
from agentkit.story_split.models import (
    DependencyRebinding,
    SplitPlan,
    SplitStatus,
    StorySplitRecord,
    SuccessorStory,
    compute_plan_ref,
    derive_split_id,
)

NOW = datetime(2026, 6, 12, 12, 0, tzinfo=UTC)


def _plan() -> SplitPlan:
    return SplitPlan.model_validate(
        {
            "project_key": "ak3",
            "source_story_id": "AK3-042",
            "reason": "scope_explosion",
            "successors": [
                {"story_id": "AK3-107", "title": "Slice A", "scope_slice": "A"},
                {"story_id": "AK3-108", "title": "Slice B", "scope_slice": "B"},
            ],
            "dependency_rebinding": [
                {
                    "dependent_story_id": "AK3-051",
                    "old_dependency": "AK3-042",
                    "new_dependencies": ["AK3-107"],
                }
            ],
        }
    )


def test_plan_requires_successors() -> None:
    with pytest.raises(ValidationError):
        SplitPlan.model_validate(
            {
                "project_key": "ak3",
                "source_story_id": "AK3-042",
                "reason": "scope_explosion",
                "successors": [],
            }
        )


def test_plan_rejects_duplicate_successor_ids() -> None:
    with pytest.raises(ValidationError, match="unique"):
        SplitPlan.model_validate(
            {
                "project_key": "ak3",
                "source_story_id": "AK3-042",
                "reason": "scope_explosion",
                "successors": [
                    {"story_id": "AK3-107", "title": "A", "scope_slice": "A"},
                    {"story_id": "AK3-107", "title": "B", "scope_slice": "B"},
                ],
            }
        )


def test_plan_rejects_successor_equal_to_source() -> None:
    with pytest.raises(ValidationError, match="differ from the source"):
        SplitPlan.model_validate(
            {
                "project_key": "ak3",
                "source_story_id": "AK3-042",
                "reason": "scope_explosion",
                "successors": [
                    {"story_id": "AK3-042", "title": "A", "scope_slice": "A"},
                ],
            }
        )


def test_plan_rejects_rebinding_to_unknown_successor() -> None:
    with pytest.raises(ValidationError, match="declared successor"):
        SplitPlan.model_validate(
            {
                "project_key": "ak3",
                "source_story_id": "AK3-042",
                "reason": "scope_explosion",
                "successors": [
                    {"story_id": "AK3-107", "title": "A", "scope_slice": "A"},
                ],
                "dependency_rebinding": [
                    {
                        "dependent_story_id": "AK3-051",
                        "old_dependency": "AK3-042",
                        "new_dependencies": ["AK3-999"],
                    }
                ],
            }
        )


def test_plan_rejects_rebinding_old_dependency_not_source() -> None:
    with pytest.raises(ValidationError, match="old_dependency"):
        SplitPlan.model_validate(
            {
                "project_key": "ak3",
                "source_story_id": "AK3-042",
                "reason": "scope_explosion",
                "successors": [
                    {"story_id": "AK3-107", "title": "A", "scope_slice": "A"},
                ],
                "dependency_rebinding": [
                    {
                        "dependent_story_id": "AK3-051",
                        "old_dependency": "AK3-999",
                        "new_dependencies": ["AK3-107"],
                    }
                ],
            }
        )


def test_story_lineage_is_derived_deterministically() -> None:
    plan = _plan()
    lineage = plan.story_lineage
    assert lineage.split_from == "AK3-042"
    assert lineage.split_successors == ("AK3-107", "AK3-108")
    assert lineage.superseded_by == ("AK3-107", "AK3-108")
    # Deterministic: re-deriving yields the same lineage.
    assert _plan().story_lineage.split_successors == lineage.split_successors


def test_dependency_rebinding_rejects_self_edge() -> None:
    with pytest.raises(ValidationError, match="itself"):
        DependencyRebinding(
            dependent_story_id="AK3-051",
            old_dependency="AK3-042",
            new_dependencies=("AK3-051",),
        )


def test_successor_story_rejects_blank_fields() -> None:
    with pytest.raises(ValidationError):
        SuccessorStory(story_id="", title="t", scope_slice="s")


def test_derive_split_id_is_deterministic_and_key_sensitive() -> None:
    a = derive_split_id("ak3", "AK3-042", "ref1")
    b = derive_split_id("ak3", "AK3-042", "ref1")
    assert a == b
    assert a.startswith("split-")
    # Boundary-safe: different splits never collide.
    assert derive_split_id("ak3", "AK3-04", "2ref1") != a
    assert derive_split_id("ak3", "AK3-042", "ref2") != a


def test_compute_plan_ref_is_content_hash() -> None:
    assert compute_plan_ref("x") == compute_plan_ref("x")
    assert compute_plan_ref("x") != compute_plan_ref("y")


def test_split_record_consumes_ag3_074_axis() -> None:
    record = StorySplitRecord(
        split_id="split-1",
        project_key="ak3",
        source_story_id="AK3-042",
        requested_by="human_cli",
        reason="scope_explosion",
        plan_ref="ref",
        status=SplitStatus.COMMITTED,
        successor_ids=("AK3-107",),
        superseded_by=("AK3-107",),
        terminal_state=TerminalState.CANCELLED,
        exit_class=ExitClass.SCOPE_SPLIT,
        created_at=NOW,
    )
    assert record.exit_class is ExitClass.SCOPE_SPLIT
    assert record.terminal_state is TerminalState.CANCELLED


def test_split_record_rejects_committed_without_exit_class() -> None:
    with pytest.raises(ValidationError, match="exit_class=scope_split"):
        StorySplitRecord(
            split_id="split-1",
            project_key="ak3",
            source_story_id="AK3-042",
            requested_by="human_cli",
            reason="r",
            plan_ref="ref",
            status=SplitStatus.COMMITTED,
            created_at=NOW,
        )


def test_split_record_rejects_failed_with_exit_class() -> None:
    with pytest.raises(ValidationError, match="no mutation"):
        StorySplitRecord(
            split_id="split-1",
            project_key="ak3",
            source_story_id="AK3-042",
            requested_by="human_cli",
            reason="r",
            plan_ref="ref",
            status=SplitStatus.FAILED,
            terminal_state=TerminalState.CANCELLED,
            exit_class=ExitClass.SCOPE_SPLIT,
            created_at=NOW,
        )


def test_split_record_rejects_exit_class_without_cancelled() -> None:
    # Delegated to AG3-074 validate_exit_class_constraints (no second constraint).
    with pytest.raises(ValidationError):
        StorySplitRecord(
            split_id="split-1",
            project_key="ak3",
            source_story_id="AK3-042",
            requested_by="human_cli",
            reason="r",
            plan_ref="ref",
            status=SplitStatus.COMMITTED,
            terminal_state=TerminalState.OPEN,
            exit_class=ExitClass.SCOPE_SPLIT,
            created_at=NOW,
        )
