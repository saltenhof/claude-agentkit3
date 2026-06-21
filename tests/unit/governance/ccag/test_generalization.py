"""Unit tests for LLM rule generalization as a proposal (AG3-086 AC8).

FK-42 §42.3 / F-42-039: the LLM yields ONLY a rule PROPOSAL; ``approved.yaml`` is
written ONLY after an explicit Promote/Confirm. A test fake at the LLM boundary is
the documented MOCKS exception (the only unit-isolatable seam).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
import yaml

from agentkit.backend.governance.ccag.generalization import (
    RuleGeneralizer,
    RuleProposal,
    RuleProposalError,
)
from agentkit.backend.governance.ccag.rules import RULE_FILE_APPROVED, load_rules

if TYPE_CHECKING:
    from pathlib import Path


class _FakeGeneralizationLlm:
    """First-class fake LLM transport at the documented LLM boundary (MOCKS exc.)."""

    def __init__(self, response: str) -> None:
        self._response = response
        self.calls: list[str] = []

    def generalize(self, *, intent_or_call: str) -> str:
        self.calls.append(intent_or_call)
        return self._response


def _llm(tool: str = "Bash", allow: str = "git push.*origin story/") -> _FakeGeneralizationLlm:
    return _FakeGeneralizationLlm(
        json.dumps(
            {
                "tool": tool,
                "allow_pattern": allow,
                "description": "Allow git push to all story branches",
            }
        )
    )


def test_propose_returns_draft_only(tmp_path: Path) -> None:
    # AC8: a proposal is generated from a single call; NO rule is persisted.
    fake = _llm()
    gen = RuleGeneralizer(fake)
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()

    proposal = gen.propose("git push -u origin story/ODIN-042")

    assert isinstance(proposal, RuleProposal)
    assert proposal.tool == "Bash"
    assert proposal.allow_pattern == "git push.*origin story/"
    assert proposal.learned_from == "git push -u origin story/ODIN-042"
    assert fake.calls == ["git push -u origin story/ODIN-042"]
    # NEGATIVE (the load-bearing AC8 check): proposing alone writes NO approved.yaml.
    assert not (rules_dir / RULE_FILE_APPROVED).exists()


def test_propose_from_nl_intent(tmp_path: Path) -> None:
    gen = RuleGeneralizer(_llm())
    proposal = gen.propose("Worker soll alle Story-Branches pushen duerfen")
    assert proposal.learned_from == "Worker soll alle Story-Branches pushen duerfen"
    assert proposal.tool == "Bash"


def test_no_persistence_without_confirm(tmp_path: Path) -> None:
    # AC8 NEGATIVE: even after MANY proposals, nothing is persisted without an
    # explicit promote/confirm. The first positive decision is NOT a permanent rule.
    gen = RuleGeneralizer(_llm())
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()

    gen.propose("git push -u origin story/A")
    gen.propose("git push -u origin story/B")

    assert load_rules(is_subagent=False, rules_dir=rules_dir).allows == ()
    assert not (rules_dir / RULE_FILE_APPROVED).exists()


def test_persistence_after_confirm_writes_learned_from(tmp_path: Path) -> None:
    # AC8 POSITIVE: an explicit promote writes approved.yaml WITH learned_from /
    # learned_at, and the rule then loads as an allow rule.
    gen = RuleGeneralizer(_llm())
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()

    proposal = gen.propose("git push -u origin story/ODIN-042")
    rule = RuleGeneralizer.promote(
        proposal, rules_dir=rules_dir, rule_id="auto-001"
    )

    assert rule.learned_from == "git push -u origin story/ODIN-042"
    assert rule.learned_at  # promotion timestamp set
    approved_path = rules_dir / RULE_FILE_APPROVED
    assert approved_path.exists()
    raw = yaml.safe_load(approved_path.read_text(encoding="utf-8"))
    assert raw[0]["learned_from"] == "git push -u origin story/ODIN-042"
    assert raw[0]["learned_at"]
    # The promoted rule loads as an allow rule from the canonical loader.
    loaded = load_rules(is_subagent=False, rules_dir=rules_dir)
    assert any(r.rule_id == "auto-001" for r in loaded.allows)


def test_malformed_llm_response_fails_closed(tmp_path: Path) -> None:
    # FAIL-CLOSED: a non-JSON / pattern-less response yields NO proposal (no rule).
    gen = RuleGeneralizer(_FakeGeneralizationLlm("not json at all"))
    with pytest.raises(RuleProposalError):
        gen.propose("git push origin story/X")


def test_missing_pattern_fails_closed() -> None:
    gen = RuleGeneralizer(
        _FakeGeneralizationLlm(json.dumps({"tool": "Bash", "description": "x"}))
    )
    with pytest.raises(RuleProposalError):
        gen.propose("git push origin story/X")


def test_missing_tool_fails_closed() -> None:
    gen = RuleGeneralizer(
        _FakeGeneralizationLlm(json.dumps({"allow_pattern": ".*", "description": "x"}))
    )
    with pytest.raises(RuleProposalError):
        gen.propose("git push origin story/X")
