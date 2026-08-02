"""AC8 contract proof for nightly and pre-merge W2 wiring."""

from __future__ import annotations

import re
from pathlib import Path


def _prose(path: Path) -> str:
    """Read a markdown surface as flowing prose.

    Line wrapping and bold markers are layout, not content. Asserting on the
    raw bytes makes a reflow break the test and invites the next author to
    weaken the assertion instead of fixing the document.
    """
    raw = path.read_text(encoding="utf-8").replace("*", "")
    return re.sub(r"\s+", " ", raw)


def test_w2_is_only_in_explicit_non_blocking_nightly_stage() -> None:
    jenkins = Path("Jenkinsfile").read_text(encoding="utf-8")
    command = "python scripts/ci/check_concept_authority_prose.py --mode nightly"
    assert jenkins.count(command) == 1
    assert "stage('Concept Authority Prose Nightly (non-blocking)')" in jenkins
    assert "params.agentkit_mode == 'nightly'" in jenkins
    assert "LLM_HUB_URL=http://host.docker.internal:9600" in jenkins
    assert 'if [ "$W2_EXIT" -ne 0 ]' in jenkins
    assert "exit 0" in jenkins


def test_the_pre_merge_obligation_is_documented_as_suspended() -> None:
    """PO decision 2026-08-02: the W2/W3 pre-merge obligation is suspended.

    The tools keep working and the governance document keeps describing them —
    what ended is the DUTY to run them before landing. The rule that replaces
    it must be findable where an agent looks for its duties, otherwise the next
    agent either stalls on an unfulfillable rule or quietly claims it ran.
    """
    agents = _prose(Path("AGENTS.md"))
    assert "Die W2/W3-Pre-Merge-Pflicht ist seit 2026-08-02 ausgesetzt" in agents
    # What replaces it must be named, not merely the absence of the old duty.
    assert "unabhaengigen Agenten" in agents
    # The deterministic gates stay blocking — no gate-free path into the norm.
    assert "check_concept_decision_record.py" in agents
    assert "kein Abnahmekriterium mehr" in agents


def test_the_governance_document_still_describes_the_tools() -> None:
    """The suspension ended the obligation, not the tool description (W2/W3)."""
    governance = Path("concept/_meta/konzept-konsistenz-governance.md").read_text(encoding="utf-8")
    assert "python scripts/ci/check_concept_authority_prose.py --mode pre-merge" in governance
    assert "python scripts/ci/check_concept_scope_consistency.py --scope" in governance


def test_w3_is_only_in_explicit_non_blocking_nightly_stage() -> None:
    jenkins = Path("Jenkinsfile").read_text(encoding="utf-8")
    command = "python scripts/ci/check_concept_scope_consistency.py"
    start = jenkins.index("stage('Concept Scope Consistency Nightly (non-blocking)')")
    end = jenkins.index("stage('Concept Contract Checks')", start)
    stage = jenkins[start:end]
    assert jenkins.count(command) == 1
    assert "params.agentkit_mode == 'nightly'" in stage
    assert 'if [ "$W3_EXIT" -ne 0 ]' in stage
    assert "exit 0" in stage


def test_a_not_run_sweep_is_never_reported_as_green() -> None:
    """The suspension must not become a licence to overclaim (AG3-179 round 1).

    Suspending the duty is only safe while the difference between "did not run"
    and "green" stays written down. Without this sentence the suspension reads
    as permission to fold both into one report — which is exactly the
    overclaim it was meant to end.
    """
    agents = _prose(Path("AGENTS.md"))
    assert "niemals als \"gruen\"" in agents or 'niemals als "gruen"' in agents
