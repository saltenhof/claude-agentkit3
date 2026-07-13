"""Contract tests for the repository-wide Jenkins coverage gate."""

from __future__ import annotations

from pathlib import Path


def test_jenkins_coverage_gate_combines_all_ci_test_levels() -> None:
    """Defer the unchanged threshold until unit, contract, and integration ran."""
    jenkinsfile = (Path(__file__).parents[2] / "Jenkinsfile").read_text(
        encoding="utf-8"
    )
    unit_stage = jenkinsfile.index("stage('Unit Tests + Coverage')")
    integration_stage = jenkinsfile.index("stage('Postgres Contract + Integration')")
    concept_stage = jenkinsfile.index("stage('Concept Frontmatter Lint')")
    unit_commands = jenkinsfile[unit_stage:integration_stage]
    integration_commands = jenkinsfile[integration_stage:concept_stage]

    assert "--cov=src" in unit_commands
    assert "--cov-fail-under=0" in unit_commands
    assert "tests/contract tests/integration tests/e2e" in integration_commands
    assert "--cov=src" in integration_commands
    assert "--cov-append" in integration_commands
    assert "--cov-fail-under=0" not in integration_commands
