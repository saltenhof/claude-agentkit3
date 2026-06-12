"""Tests for the fail-closed split-plan loader (AG3-072 AK2)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from agentkit.story_split.plan_loader import SplitPlanError, load_split_plan

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


def test_non_json_plan_fails_closed(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.json"
    plan_path.write_text("not json {", encoding="utf-8")
    with pytest.raises(SplitPlanError, match="not valid JSON"):
        load_split_plan(plan_path)


def test_non_object_plan_fails_closed(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.json"
    plan_path.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(SplitPlanError, match="must be a JSON object"):
        load_split_plan(plan_path)


def test_incomplete_plan_fails_closed(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        json.dumps({"project_key": "ak3", "source_story_id": "AK3-042"}),
        encoding="utf-8",
    )
    with pytest.raises(SplitPlanError, match="failed validation"):
        load_split_plan(plan_path)
