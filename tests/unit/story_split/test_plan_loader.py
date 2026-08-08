"""Tests for the fail-closed split-plan loader/parser (AG3-072 AK2, AG3-240).

AG3-240 gave the module ONE validation implementation with two entries:
``load_split_plan`` for the edge (FK-91 §91.1 -- the CLI sends the *validated*
plan text) and ``parse_split_plan`` for the writer, which validates the text it
received rather than trusting the client it came from.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.story_split.plan_loader import (
    SplitPlanError,
    load_split_plan,
    parse_split_plan,
)

if TYPE_CHECKING:
    from pathlib import Path

_VALID = {
    "project_key": "ak3",
    "source_story_id": "AK3-042",
    "reason": "scope_explosion",
    "successors": [
        {"story_id": "AK3-107", "title": "Slice A", "scope_slice": "A"},
    ],
    "dependency_rebinding": [],
}


def test_valid_plan_text_returns_typed_plan() -> None:
    plan = parse_split_plan(json.dumps(_VALID))

    assert plan.source_story_id == "AK3-042"
    assert plan.project_key == "ak3"


def test_non_json_plan_fails_closed() -> None:
    with pytest.raises(SplitPlanError, match="not valid JSON"):
        parse_split_plan("not json {")


def test_non_object_plan_fails_closed() -> None:
    with pytest.raises(SplitPlanError, match="must be a JSON object"):
        parse_split_plan("[1, 2, 3]")


def test_incomplete_plan_fails_closed() -> None:
    with pytest.raises(SplitPlanError, match="failed validation"):
        parse_split_plan(json.dumps({"project_key": "ak3", "source_story_id": "AK3-042"}))


def test_empty_plan_text_fails_closed() -> None:
    """An unreadable/empty document never reaches the saga (§54.6)."""
    with pytest.raises(SplitPlanError, match="not valid JSON"):
        parse_split_plan("")


def test_load_valid_plan_returns_typed_plan_and_raw_text(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.json"
    text = json.dumps(_VALID)
    plan_path.write_text(text, encoding="utf-8")

    plan, plan_text = load_split_plan(plan_path)

    assert plan.source_story_id == "AK3-042"
    assert plan_text == text  # exact bytes for the deterministic plan_ref hash


def test_missing_plan_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(SplitPlanError, match="not found"):
        load_split_plan(tmp_path / "absent.json")


def test_load_reports_the_path_with_the_defect(tmp_path: Path) -> None:
    """The edge-side error names the file; the shared rule stays one function."""
    plan_path = tmp_path / "plan.json"
    plan_path.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(SplitPlanError, match="must be a JSON object"):
        load_split_plan(plan_path)


def test_both_entries_enforce_the_same_rule(tmp_path: Path) -> None:
    """A document either side rejects is rejected by the other one too."""
    defective = json.dumps({"project_key": "ak3", "source_story_id": "AK3-042"})
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(defective, encoding="utf-8")

    with pytest.raises(SplitPlanError):
        parse_split_plan(defective)
    with pytest.raises(SplitPlanError):
        load_split_plan(plan_path)
