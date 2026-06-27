"""CLI production wiring for installer live preflight dependencies."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.cli.main import (
    _split_jenkins_url,
    _wire_live_install_integrations,
)
from agentkit.backend.installer.integration_checkpoints.sonar_preflight import (
    ADMINISTER_ISSUES,
)
from agentkit.backend.installer.runner import InstallConfig
from agentkit.integration_clients.jenkins import JenkinsClient
from agentkit.integration_clients.sonar import SonarClient

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_split_jenkins_job_url_to_root_and_pipeline() -> None:
    base_url, pipeline = _split_jenkins_url(
        "http://localhost:9900/job/claude-agentkit3/"
    )
    assert base_url == "http://localhost:9900"
    assert pipeline == "claude-agentkit3"


def test_cli_wires_live_sonar_and_jenkins_from_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SONAR_URL", "http://sonar:9901")
    monkeypatch.setenv("SONAR_USER", "admin")
    monkeypatch.setenv("SONAR_PASSWORD", "sonar-secret")
    monkeypatch.setenv("JENKINS_URL", "http://jenkins:9900/job/ak3/")
    monkeypatch.setenv("JENKINS_USER", "admin")
    monkeypatch.setenv("JENKINS_API_TOKEN", "jenkins-secret")

    config = InstallConfig(
        project_key="ak3",
        project_name="AgentKit 3",
        project_root=tmp_path,
    )
    _wire_live_install_integrations(config)

    assert config.sonarqube_base_url == "http://sonar:9901"
    assert config.sonarqube_token_env == "SONAR_PASSWORD"
    assert isinstance(config.sonar_client, SonarClient)
    assert config.sonar_token_permissions == frozenset({ADMINISTER_ISSUES})
    assert config.sonar_branch_plugin_self_test is not None
    assert config.ci_base_url == "http://jenkins:9900"
    assert config.ci_pipeline == "ak3"
    assert config.ci_token_env == "JENKINS_API_TOKEN"
    assert isinstance(config.ci_client, JenkinsClient)
