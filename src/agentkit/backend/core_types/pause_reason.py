"""PauseReason — reason for a PAUSED phase state.

Source of truth: FK-39 §39.2.2 — concept/technical-design/39_phase_state_persistenz.md
(glossary entry lines 62-69 and description in §39.2.2).

The normalized values are pinned in FK-39 §39.2.2; any other string is
invalid and is rejected fail-closed by the phase runner (see
`from_yield_status`).

Concept-drift note (AG3-021 Codex review): FK-39 §39.2.2 contains
lowercase wire strings in the code example, the FK-39 glossary (lines
62-69) uses UPPER_SNAKE_CASE. Story AG3-021 §2.1.1.1 carries the
UPPER_SNAKE_CASE variant normatively; consistent with
QaContext/AttemptOutcome/FailureCause/EnvelopeStatus (upper-case).
The concept inconsistency in the FK-39 code block is reported in the
story report.
"""

from __future__ import annotations

from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Mapping

# Synonym table from AG3-021 §2.1.4 — maps historically observed
# free-string values onto the normalized PauseReason members.
# Comparison is case-insensitive (on the input side); keys are already
# lowercase.
_YIELD_STATUS_SYNONYMS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "awaiting_design_review": "AWAITING_DESIGN_REVIEW",
        "design_review_pending": "AWAITING_DESIGN_REVIEW",
        "design_review": "AWAITING_DESIGN_REVIEW",
        "awaiting_design_challenge": "AWAITING_DESIGN_CHALLENGE",
        "design_challenge": "AWAITING_DESIGN_CHALLENGE",
        "design_challenge_pending": "AWAITING_DESIGN_CHALLENGE",
        "governance_incident": "GOVERNANCE_INCIDENT",
        "governance_pause": "GOVERNANCE_INCIDENT",
        "governance_intervention": "GOVERNANCE_INCIDENT",
        "awaiting_edge_provisioning": "AWAITING_EDGE_PROVISIONING",
        "edge_provisioning": "AWAITING_EDGE_PROVISIONING",
        "edge_provisioning_pending": "AWAITING_EDGE_PROVISIONING",
    },
)


class PauseReason(StrEnum):
    """Four normalized values for `phase_state.paused_reason`.

    Attributes:
        AWAITING_DESIGN_REVIEW: Draft artifact waits for the design review
            (exploration phase).
        AWAITING_DESIGN_CHALLENGE: Design review raised objections, the
            pipeline pauses until the challenge process is complete.
        GOVERNANCE_INCIDENT: Governance observer detected a critical
            incident; a human must intervene.
        AWAITING_EDGE_PROVISIONING: Setup commissioned the Project Edge to
            provision worktrees / run the preflight probe and pauses
            fail-closed until the edge reports (FK-10 §10.2.4a, FK-91
            §91.1b). No human needed; the agent drives its own edge tool
            and the orchestrator resumes after the report.
    """

    AWAITING_DESIGN_REVIEW = "AWAITING_DESIGN_REVIEW"
    AWAITING_DESIGN_CHALLENGE = "AWAITING_DESIGN_CHALLENGE"
    GOVERNANCE_INCIDENT = "GOVERNANCE_INCIDENT"
    AWAITING_EDGE_PROVISIONING = "AWAITING_EDGE_PROVISIONING"

    @classmethod
    def from_yield_status(cls, raw: str) -> PauseReason:
        """Map a free-form yield-status string to a normalized PauseReason.

        Intended for the v2 -> v3 migration path, in which
        `result.yield_status` is still passed around as a free string (see
        AG3-021 §2.1.4). Accepts both legacy synonyms (e.g.
        ``"design_review_pending"``) and the normalized wire value itself
        (``"AWAITING_DESIGN_REVIEW"``).

        Args:
            raw: Any yield-status string.

        Returns:
            The corresponding ``PauseReason`` value.

        Raises:
            ValueError: When ``raw`` is neither a synonym nor a normalized
                value (fail-closed; no default).
        """
        if not raw:
            raise ValueError(
                "PauseReason.from_yield_status received empty string",
            )

        normalized = raw.strip().lower()
        if not normalized:
            raise ValueError(
                "PauseReason.from_yield_status received whitespace-only string",
            )

        target_name = _YIELD_STATUS_SYNONYMS.get(normalized)
        if target_name is None:
            # The normalized form may itself be the canonical lowercase
            # wire-string variant — but our wire format is upper-case.
            # Accept the canonical upper-case wire-string regardless of case.
            try:
                return cls(raw.strip().upper())
            except ValueError as exc:
                raise ValueError(
                    f"PauseReason.from_yield_status: unknown yield_status "
                    f"{raw!r}; allowed synonyms: "
                    f"{sorted(_YIELD_STATUS_SYNONYMS)} or a canonical "
                    f"member name {sorted(m.value for m in cls)}",
                ) from exc

        return cls(target_name)
