"""Unit tests for shared installer strict_json helpers (AG3-164 review-10)."""

from __future__ import annotations

import json
import math

from agentkit.backend.installer.strict_json import (
    MAX_JSON_NESTING_DEPTH,
    contains_lone_surrogate,
    contains_non_finite_float,
    exceeds_max_json_nesting,
    reject_duplicate_object_pairs,
    reject_non_json_constant,
)


def test_iterative_predicates_handle_mid_depth_without_recursion_error() -> None:
    """Depth where recursive walks used to raise must be walkable iteratively."""
    depth = 700
    text = "[" * depth + "0" + "]" * depth
    value = json.loads(
        text,
        parse_constant=reject_non_json_constant,
        object_pairs_hook=reject_duplicate_object_pairs,
    )
    assert contains_non_finite_float(value) is False
    assert contains_lone_surrogate(value) is False
    assert exceeds_max_json_nesting(value) is True
    assert exceeds_max_json_nesting(value, max_depth=depth + 1) is False


def test_contains_non_finite_and_surrogate_still_detect() -> None:
    assert contains_non_finite_float({"a": math.nan}) is True
    assert contains_non_finite_float({"a": 1.0}) is False
    assert contains_lone_surrogate({"\ud800": 1}) is True
    assert contains_lone_surrogate({"a": "\ud800"}) is True
    assert contains_lone_surrogate({"a": "ok"}) is False


def test_max_nesting_constant_is_below_default_recursion_limit() -> None:
    import sys

    assert sys.getrecursionlimit() > MAX_JSON_NESTING_DEPTH
    assert MAX_JSON_NESTING_DEPTH >= 64
