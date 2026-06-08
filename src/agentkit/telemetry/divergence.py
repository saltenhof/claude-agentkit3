"""Pure review-divergence verdict normalization and quorum logic."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

VERDICT_NORMALIZATION: dict[str, str] = {
    "PASS": "PASS",
    "PASS_WITH_CONCERNS": "CONCERN",
    "REWORK": "FAIL",
    "FAIL": "FAIL",
}

_VERDICT_STRICTNESS: dict[str, int] = {
    "PASS": 0,
    "CONCERN": 1,
    "FAIL": 2,
}


@dataclass(frozen=True)
class ReviewPairDivergence:
    """Review-pair divergence fact with optional quorum result."""

    reviewer_a: str
    reviewer_b: str
    verdict_a: str
    verdict_b: str
    divergent: bool
    quorum_triggered: bool
    final_verdict: str | None


def normalize_verdict(raw_verdict: str) -> str:
    """Normalize a raw review verdict to the FK-34 three-value verdict set.

    Unknown values pass through unchanged, matching FK-34 section 34.8.2.
    """
    return VERDICT_NORMALIZATION.get(raw_verdict, raw_verdict)


def check_divergence(verdict_a: str, verdict_b: str) -> bool:
    """Return whether two normalized review verdicts differ."""
    return normalize_verdict(verdict_a) != normalize_verdict(verdict_b)


def apply_quorum(verdict_a: str, verdict_b: str, verdict_c: str) -> str:
    """Return the majority verdict for three reviews.

    If all three normalized FK-34 verdicts differ, the decision fails closed to
    the strictest verdict in the order ``PASS < CONCERN < FAIL``.
    """
    normalized = (
        normalize_verdict(verdict_a),
        normalize_verdict(verdict_b),
        normalize_verdict(verdict_c),
    )
    counts = Counter(normalized)
    for verdict, count in counts.items():
        if count >= 2:
            return verdict
    return max(
        normalized,
        key=lambda verdict: _VERDICT_STRICTNESS.get(
            verdict, max(_VERDICT_STRICTNESS.values()) + 1
        ),
    )


__all__ = [
    "ReviewPairDivergence",
    "VERDICT_NORMALIZATION",
    "apply_quorum",
    "check_divergence",
    "normalize_verdict",
]
