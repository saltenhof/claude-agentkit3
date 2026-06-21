"""Fail-closed split-plan loader (§54.6/§54.7).

Reads and validates the human-approved ``--plan`` artifact BEFORE any mutation.
Returns the raw text (for the deterministic ``plan_ref`` content hash) together
with the typed :class:`SplitPlan`. Any structural defect (not a file, invalid
JSON, missing required fields, inconsistent references) is a fail-closed reject.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from pydantic import ValidationError

from agentkit.backend.story_split.models import SplitPlan

if TYPE_CHECKING:
    from pathlib import Path


class SplitPlanError(ValueError):
    """Fail-closed split-plan validation error (no partial mutation)."""


def load_split_plan(plan_path: Path) -> tuple[SplitPlan, str]:
    """Read + validate the split plan at ``plan_path`` (fail-closed).

    Args:
        plan_path: Filesystem path to the human-approved plan JSON document.

    Returns:
        A ``(plan, plan_text)`` tuple: the typed plan plus the EXACT raw document
        text used to derive the deterministic ``plan_ref`` content hash.

    Raises:
        SplitPlanError: When the file is missing, not JSON, not an object, or
            does not satisfy the typed :class:`SplitPlan` contract.
    """
    if not plan_path.is_file():
        raise SplitPlanError(f"split plan not found: {plan_path}")
    plan_text = plan_path.read_text(encoding="utf-8")
    try:
        data = json.loads(plan_text)
    except json.JSONDecodeError as exc:
        raise SplitPlanError(f"split plan is not valid JSON ({plan_path}): {exc}") from exc
    if not isinstance(data, dict):
        raise SplitPlanError(f"split plan must be a JSON object: {plan_path}")
    try:
        plan = SplitPlan.model_validate(data)
    except ValidationError as exc:
        raise SplitPlanError(
            f"split plan failed validation ({plan_path}): {exc}",
        ) from exc
    return plan, plan_text


__all__ = ["SplitPlanError", "load_split_plan"]
