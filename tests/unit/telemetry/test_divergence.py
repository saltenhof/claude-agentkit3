"""Unit tests for pure review divergence logic (AG3-066)."""

from __future__ import annotations

import dataclasses
from dataclasses import FrozenInstanceError, fields
from typing import get_type_hints

import pytest

from agentkit.telemetry.divergence import (
    VERDICT_NORMALIZATION,
    ReviewPairDivergence,
    apply_quorum,
    check_divergence,
    normalize_verdict,
)


def test_review_pair_divergence_dataclass_contract_is_exact_and_frozen() -> None:
    assert dataclasses.is_dataclass(ReviewPairDivergence)
    assert ReviewPairDivergence.__dataclass_params__.frozen is True
    assert [field.name for field in fields(ReviewPairDivergence)] == [
        "reviewer_a",
        "reviewer_b",
        "verdict_a",
        "verdict_b",
        "divergent",
        "quorum_triggered",
        "final_verdict",
    ]
    assert get_type_hints(ReviewPairDivergence) == {
        "reviewer_a": str,
        "reviewer_b": str,
        "verdict_a": str,
        "verdict_b": str,
        "divergent": bool,
        "quorum_triggered": bool,
        "final_verdict": str | None,
    }
    fact = ReviewPairDivergence(
        reviewer_a="qa",
        reviewer_b="security",
        verdict_a="PASS",
        verdict_b="FAIL",
        divergent=True,
        quorum_triggered=True,
        final_verdict="FAIL",
    )
    with pytest.raises(FrozenInstanceError):
        fact.final_verdict = "PASS"  # type: ignore[misc]


def test_verdict_normalization_contract_is_exact() -> None:
    assert VERDICT_NORMALIZATION == {
        "PASS": "PASS",
        "PASS_WITH_CONCERNS": "CONCERN",
        "REWORK": "FAIL",
        "FAIL": "FAIL",
    }


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("PASS", "PASS"),
        ("PASS_WITH_CONCERNS", "CONCERN"),
        ("REWORK", "FAIL"),
        ("FAIL", "FAIL"),
        ("CONCERN", "CONCERN"),
        ("UNKNOWN_VENDOR_VERDICT", "UNKNOWN_VENDOR_VERDICT"),
    ],
)
def test_normalize_verdict_maps_known_values_and_passes_unknown_through(
    raw: str, expected: str
) -> None:
    assert normalize_verdict(raw) == expected


@pytest.mark.parametrize(
    ("verdict_a", "verdict_b", "expected"),
    [
        ("PASS", "PASS", False),
        ("PASS_WITH_CONCERNS", "CONCERN", False),
        ("CONCERN", "FAIL", True),
        ("REWORK", "FAIL", False),
        ("PASS", "REWORK", True),
    ],
)
def test_check_divergence_compares_normalized_three_value_verdicts(
    verdict_a: str, verdict_b: str, expected: bool
) -> None:
    assert check_divergence(verdict_a, verdict_b) is expected


@pytest.mark.parametrize(
    ("verdicts", "expected"),
    [
        (("PASS", "PASS", "FAIL"), "PASS"),
        (("PASS", "FAIL", "PASS"), "PASS"),
        (("FAIL", "PASS", "PASS"), "PASS"),
        (("CONCERN", "CONCERN", "PASS"), "CONCERN"),
        (("CONCERN", "PASS", "CONCERN"), "CONCERN"),
        (("PASS", "CONCERN", "CONCERN"), "CONCERN"),
        (("FAIL", "FAIL", "PASS"), "FAIL"),
        (("FAIL", "PASS", "FAIL"), "FAIL"),
        (("PASS", "FAIL", "FAIL"), "FAIL"),
        (("REWORK", "FAIL", "PASS"), "FAIL"),
    ],
)
def test_apply_quorum_returns_normalized_majority(
    verdicts: tuple[str, str, str], expected: str
) -> None:
    assert apply_quorum(*verdicts) == expected


def test_apply_quorum_no_majority_fails_closed_to_strictest_verdict() -> None:
    assert apply_quorum("PASS", "PASS_WITH_CONCERNS", "FAIL") == "FAIL"
