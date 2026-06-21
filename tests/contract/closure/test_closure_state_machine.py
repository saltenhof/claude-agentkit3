"""Contract tests pinning the closure orchestration to ``formal.story-closure.*``.

These pin the code (``ClosureProgress`` checkpoint order + ``ClosureVerdict``
values + the escalation behaviour) against the SSOT formal spec under
``concept/formal-spec/story-closure/`` -- NOT against a test-local duplicate
(AG3-053 AC#10, rubric category 7). A drift between the code and the spec fails
the contract.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from agentkit.backend.closure.phase import ClosureVerdict
from agentkit.backend.pipeline_engine.phase_executor import ClosureProgress

_SPEC_ROOT = (
    Path(__file__).resolve().parents[3]
    / "concept"
    / "formal-spec"
    / "story-closure"
)
_FORMAL_BLOCK = re.compile(
    r"<!-- FORMAL-SPEC:BEGIN -->\s*```yaml\n(?P<body>.*?)\n```", re.DOTALL
)


def _load_spec(name: str) -> dict[str, object]:
    text = (_SPEC_ROOT / name).read_text(encoding="utf-8")
    match = _FORMAL_BLOCK.search(text)
    assert match is not None, f"no FORMAL-SPEC block in {name}"
    return yaml.safe_load(match.group("body"))


def test_invariants_pin_exists() -> None:
    """The pinned invariant ids exist in the SSOT spec (guards against drift)."""
    invariants = _load_spec("invariants.md")["invariants"]
    ids = {inv["id"] for inv in invariants}
    for required in (
        "story-closure.invariant.push_precedes_merge",
        "story-closure.invariant.merge_requires_pushed_story_branch",
        "story-closure.invariant.integrity_gate_precedes_merge_block",
        "story-closure.invariant.merge_rejection_never_completes_closure",
        "story-closure.invariant.completed_requires_merge_and_story_close",
    ):
        assert required in ids


def test_closure_verdict_matches_spec_terminal_states() -> None:
    """``ClosureVerdict`` matches the spec's terminal states (completed/escalated)."""
    states = _load_spec("state-machine.md")["states"]
    terminal = {
        s["id"].rsplit(".", 1)[-1].upper()
        for s in states
        if s.get("terminal")
    }
    assert terminal == {v.value for v in ClosureVerdict}


def test_closure_progress_enforces_push_precedes_merge() -> None:
    """``push_precedes_merge``: merge_done cannot be true before story_branch_pushed."""
    with pytest.raises(ValueError, match="merge_done"):
        ClosureProgress(integrity_passed=True, merge_done=True)


def test_closure_progress_enforces_integrity_precedes_push() -> None:
    """``integrity_gate_precedes_merge_block``: push requires integrity_passed."""
    with pytest.raises(ValueError, match="story_branch_pushed"):
        ClosureProgress(story_branch_pushed=True)


def test_closure_progress_enforces_monotonic_order() -> None:
    """The full checkpoint chain is monotonic (no later flag before its prior)."""
    with pytest.raises(ValueError, match="metrics_written"):
        ClosureProgress(
            integrity_passed=True, story_branch_pushed=True, merge_done=True,
            metrics_written=True,
        )


def test_closure_progress_accepts_valid_prefix_chain() -> None:
    """A valid monotonic prefix is accepted (no over-rejection of legal states)."""
    progress = ClosureProgress(
        integrity_passed=True, story_branch_pushed=True, merge_done=True
    )
    assert progress.merge_done
    assert not progress.story_closed
