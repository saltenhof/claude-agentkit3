"""LLM-assisted CCAG rule generalization as a proposal (FK-42 §42.3 / F-42-039).

FK-42 §42.3 / §42.3.1 (F-42-039) / §42.3.3 / §42.4.2: from a single permitted
tool call OR a natural-language intent, an LLM produces a generalized rule
PROPOSAL (regex + filled ``tool`` / ``allow_pattern`` / ``description``). The
proposal is a DRAFT only — it is NEVER persisted by the LLM call alone. A
persistent rule in ``approved.yaml`` (with ``learned_from`` / ``learned_at``)
arises ONLY after an explicit human Promote/Confirm decision (§42.3.1 "without
explicit confirmation no rules are stored"; §42.4.2 "no permanent rule without a
separate Promote decision"). The first positive decision on an open
permission case is only a single-case / lease, never an automatic permanent rule.

Architecture note: the LLM transport is consumed through the minimal
:class:`RuleGeneralizationLlm` port so this governance sub does NOT import the
verify-system LLM client cross-BC. The existing evaluator / LLM transport is
adapted onto this port at the composition edge. A test fake at the LLM boundary
is the documented MOCKS exception (the only unit-isolatable seam).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol

from agentkit.governance.ccag.rules import CcagRule, append_approved_rule
from agentkit.utils.io import parse_json_object

if TYPE_CHECKING:
    from pathlib import Path

_logger = logging.getLogger(__name__)


class RuleProposalError(ValueError):
    """Raised when an LLM rule-generalization response cannot be parsed.

    FAIL-CLOSED: a malformed LLM response yields NO proposal (and therefore NO
    rule). It is never silently coerced into a permissive rule.
    """


@dataclass(frozen=True)
class RuleProposal:
    """A generalized CCAG rule DRAFT (NOT persisted — FK-42 §42.3.1).

    Attributes:
        tool: The tool the proposed rule applies to (e.g. ``"Bash"``).
        allow_pattern: The generalized allow regex (e.g. ``"git push.*origin
            story/"``). Empty when the proposal is a block rule.
        block_pattern: The generalized block regex. Empty for an allow proposal.
        description: A human-readable preview of the rule's effect.
        learned_from: The original single call / NL intent the proposal
            generalized (carried into ``approved.yaml`` ONLY on promotion).
    """

    tool: str
    allow_pattern: str
    description: str
    block_pattern: str = ""
    learned_from: str = ""

    def to_rule(self, *, rule_id: str, learned_at: str) -> CcagRule:
        """Materialise the proposal into a persistable :class:`CcagRule`.

        Args:
            rule_id: The id assigned to the promoted rule.
            learned_at: The ISO-8601 promotion timestamp (``learned_at``).

        Returns:
            A :class:`CcagRule` carrying ``learned_from`` / ``learned_at``.
        """
        return CcagRule(
            rule_id=rule_id,
            tool=self.tool,
            allow_pattern=self.allow_pattern,
            block_pattern=self.block_pattern,
            description=self.description,
            learned_from=self.learned_from,
            learned_at=learned_at,
        )


class RuleGeneralizationLlm(Protocol):
    """Minimal LLM transport port for rule generalization (FK-42 §42.3).

    Satisfied by an adapter over the existing evaluator / LLM transport. Returns
    the raw LLM response text for a generalization prompt; the parser turns it
    into a :class:`RuleProposal`.
    """

    def generalize(self, *, intent_or_call: str) -> str:
        """Return the raw LLM response generalizing ``intent_or_call``."""
        ...


def parse_rule_proposal(response: str, *, learned_from: str) -> RuleProposal:
    """Parse an LLM generalization response into a :class:`RuleProposal`.

    The LLM is instructed (FK-42 §42.3.2) to return a JSON object with the
    generalized ``tool`` and ``allow_pattern`` (or ``block_pattern``) plus a
    ``description``. FAIL-CLOSED: a malformed response or a missing ``tool`` /
    pattern raises :class:`RuleProposalError` — no proposal is fabricated.

    Args:
        response: The raw LLM response text.
        learned_from: The original single call / NL intent (recorded on the
            proposal for an eventual promotion).

    Returns:
        The parsed :class:`RuleProposal`.

    Raises:
        RuleProposalError: When the response is not parseable into a valid draft.
    """
    try:
        # Parse via the utils.io truth-boundary helper (governance modules must
        # not call json.load* directly — formal.truth-boundary-checker.invariants).
        data = parse_json_object(response)
    except ValueError as exc:
        raise RuleProposalError(
            f"LLM rule-generalization response is not a valid JSON object: {exc}"
        ) from exc
    tool = str(data.get("tool", "")).strip()
    allow_pattern = str(data.get("allow_pattern", "")).strip()
    block_pattern = str(data.get("block_pattern", "")).strip()
    description = str(data.get("description", "")).strip()
    if not tool:
        raise RuleProposalError("LLM proposal is missing a 'tool'")
    if not allow_pattern and not block_pattern:
        raise RuleProposalError(
            "LLM proposal must carry an 'allow_pattern' or a 'block_pattern'"
        )
    return RuleProposal(
        tool=tool,
        allow_pattern=allow_pattern,
        block_pattern=block_pattern,
        description=description,
        learned_from=learned_from,
    )


class RuleGeneralizer:
    """Generates CCAG rule PROPOSALS via an LLM (FK-42 §42.3) — never persists.

    The generalizer produces drafts ONLY. Persistence is a SEPARATE, explicit
    Promote/Confirm step (:meth:`promote`); generating a proposal NEVER touches
    ``approved.yaml`` (FK-42 §42.3.1 / §42.4.2).

    Args:
        llm: The LLM transport port (the existing evaluator / transport adapted
            onto :class:`RuleGeneralizationLlm`).
    """

    def __init__(self, llm: RuleGeneralizationLlm) -> None:
        self._llm = llm

    def propose(self, intent_or_call: str) -> RuleProposal:
        """Generate a rule PROPOSAL from a single call or NL intent (no persist).

        FK-42 §42.3.1 (F-42-039): the LLM call yields ONLY a draft. No rule is
        stored. The caller must run :meth:`promote` after an explicit human
        confirmation to persist.

        Args:
            intent_or_call: The original single permitted tool call (e.g.
                ``"git push -u origin story/ODIN-042"``) OR a natural-language
                intent (e.g. ``"Worker should push all story branches"``).

        Returns:
            A :class:`RuleProposal` draft (NOT persisted).

        Raises:
            RuleProposalError: When the LLM response is not a valid draft.
        """
        response = self._llm.generalize(intent_or_call=intent_or_call)
        return parse_rule_proposal(response, learned_from=intent_or_call)

    @staticmethod
    def promote(
        proposal: RuleProposal,
        *,
        rules_dir: Path | str,
        rule_id: str,
        now: datetime | None = None,
    ) -> CcagRule:
        """Persist a PROPOSAL to ``approved.yaml`` after explicit confirmation.

        FK-42 §42.3.3 / §42.4.2: this is the SEPARATE Promote/Confirm barrier. It
        is the ONLY path that writes a durable rule (with ``learned_from`` /
        ``learned_at``) into ``approved.yaml``. The caller invokes it ONLY after a
        human has confirmed the proposal — the first positive decision alone is a
        single-case / lease and must NOT auto-promote (§42.4.2).

        Args:
            proposal: The confirmed :class:`RuleProposal`.
            rules_dir: The CCAG rules directory holding ``approved.yaml``.
            rule_id: The id assigned to the promoted rule.
            now: The promotion timestamp (defaults to ``datetime.now(UTC)``).

        Returns:
            The persisted :class:`CcagRule` (also appended to ``approved.yaml``).
        """
        learned_at = (now or datetime.now(tz=UTC)).isoformat()
        rule = proposal.to_rule(rule_id=rule_id, learned_at=learned_at)
        append_approved_rule(rule, rules_dir)
        _logger.info(
            "CCAG rule %r promoted to approved.yaml after explicit confirmation "
            "(FK-42 §42.3.3 / §42.4.2)",
            rule_id,
        )
        return rule


__all__ = [
    "RuleGeneralizationLlm",
    "RuleGeneralizer",
    "RuleProposal",
    "RuleProposalError",
    "parse_rule_proposal",
]
