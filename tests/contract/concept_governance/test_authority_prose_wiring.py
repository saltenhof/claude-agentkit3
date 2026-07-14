"""AC8 contract proof for nightly and pre-merge W2 wiring."""

from __future__ import annotations

from pathlib import Path


def test_w2_is_only_in_explicit_non_blocking_nightly_stage() -> None:
    jenkins = Path("Jenkinsfile").read_text(encoding="utf-8")
    command = "python scripts/ci/check_concept_authority_prose.py --mode nightly"
    assert jenkins.count(command) == 1
    assert "stage('Concept Authority Prose Nightly (non-blocking)')" in jenkins
    assert "params.agentkit_mode == 'nightly'" in jenkins
    assert "LLM_HUB_URL=http://host.docker.internal:9600" in jenkins
    assert 'if [ "$W2_EXIT" -ne 0 ]' in jenkins
    assert "exit 0" in jenkins


def test_pre_merge_command_is_documented_in_both_governance_surfaces() -> None:
    command = "python scripts/ci/check_concept_authority_prose.py --mode pre-merge"
    agents = Path("AGENTS.md").read_text(encoding="utf-8")
    governance = Path("concept/_meta/konzept-konsistenz-governance.md").read_text(encoding="utf-8")
    assert command in agents
    assert command in governance
