"""Fail-closed split-plan loader and parser (§54.6/§54.7).

Validates the human-approved plan document BEFORE any mutation. Any structural
defect (missing file, invalid JSON, not an object, missing required fields,
inconsistent references) is a fail-closed reject.

There is ONE validation implementation, :func:`parse_split_plan`, and two ways
in. FK-91 §91.1 requires the operator CLI to send the *validated* plan text, so
the edge reads the file and validates it (:func:`load_split_plan`); the writer
that executes the saga validates the text it receives, because a request that
reached the core is never trusted for having passed through a client. Both go
through the same function, so "validated" means the same thing on both sides --
this is a single rule checked twice, not two rules.
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


def parse_split_plan(plan_text: str) -> SplitPlan:
    """Validate ``plan_text`` and return the typed plan (fail-closed).

    Args:
        plan_text: The EXACT raw plan document the operator approved.

    Returns:
        The typed :class:`SplitPlan`.

    Raises:
        SplitPlanError: When the text is not JSON, not an object, or does not
            satisfy the typed :class:`SplitPlan` contract.
    """
    try:
        data = json.loads(plan_text)
    except json.JSONDecodeError as exc:
        raise SplitPlanError(f"split plan is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise SplitPlanError("split plan must be a JSON object")
    try:
        return SplitPlan.model_validate(data)
    except ValidationError as exc:
        raise SplitPlanError(f"split plan failed validation: {exc}") from exc


def load_split_plan(plan_path: Path) -> tuple[SplitPlan, str]:
    """Read + validate the split plan at ``plan_path`` (fail-closed).

    Args:
        plan_path: Filesystem path to the human-approved plan JSON document.

    Returns:
        A ``(plan, plan_text)`` tuple: the typed plan plus the EXACT raw document
        text used to derive the deterministic ``plan_ref`` content hash. The text
        is returned unparsed and unformatted -- re-serialising it here would
        change the hash.

    Raises:
        SplitPlanError: When the file is missing or its content is not a valid
            plan.
    """
    if not plan_path.is_file():
        raise SplitPlanError(f"split plan not found: {plan_path}")
    plan_text = plan_path.read_text(encoding="utf-8")
    try:
        return parse_split_plan(plan_text), plan_text
    except SplitPlanError as exc:
        raise SplitPlanError(f"{exc} ({plan_path})") from exc


__all__ = ["SplitPlanError", "load_split_plan", "parse_split_plan"]
