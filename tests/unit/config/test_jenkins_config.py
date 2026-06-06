"""Unit tests for the CI (Jenkins) config stanza (AG3-056 §2.1.6 / AC7).

Covers the cross-field validation rules:
* available+enabled require base_url+token_env+pipeline (fail-closed);
* code-producing + available + not enabled is illegal;
* code-producing project must DECLARE the ci stanza explicitly;
* available:false is permitted even for code-producing projects;
* poll bounds must be positive.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agentkit.config.models import (
    JenkinsConfig,
    ProjectConfig,
    RepositoryConfig,
    SonarQubeConfig,
)

#: Code-producing projects must declare sonarqube too (AG3-052 E6); opt out
#: so these tests isolate the ci rule.
_OPT_OUT_SONAR = SonarQubeConfig(available=False, enabled=False)


def _project(ci: object) -> ProjectConfig:
    return ProjectConfig(
        project_key="acme",
        project_name="Acme",
        repositories=[RepositoryConfig(name="app", path=".")],
        pipeline={"sonarqube": _OPT_OUT_SONAR, "ci": ci},  # type: ignore[arg-type]
    )


class TestJenkinsConfigStandalone:
    def test_active_requires_endpoint_pipeline(self) -> None:
        """available+enabled without endpoint/pipeline => fail-closed."""
        with pytest.raises(ValidationError, match="base_url and token_env and pipeline"):
            JenkinsConfig()

    def test_active_with_full_endpoint_ok(self) -> None:
        cfg = JenkinsConfig(
            available=True,
            enabled=True,
            base_url="http://jenkins:8080",
            token_env="JENKINS_TOKEN",
            pipeline="ak3-pre-merge",
        )
        assert cfg.available is True
        assert cfg.pipeline == "ak3-pre-merge"

    def test_explicit_opt_out_ok(self) -> None:
        cfg = JenkinsConfig(available=False, enabled=False)
        assert cfg.available is False

    def test_negative_poll_timeout_rejected(self) -> None:
        with pytest.raises(ValidationError, match="poll_timeout_seconds"):
            JenkinsConfig(available=False, enabled=False, poll_timeout_seconds=0)

    def test_negative_poll_interval_rejected(self) -> None:
        with pytest.raises(ValidationError, match="poll_interval_seconds"):
            JenkinsConfig(available=False, enabled=False, poll_interval_seconds=-1)


class TestCiCodeProducingRule:
    def test_codeproducing_omitted_ci_stanza_rejected(self) -> None:
        """A code-producing project must DECLARE the ci stanza (fail-closed)."""
        with pytest.raises(ValidationError, match="must DECLARE the 'ci'"):
            ProjectConfig(
                project_key="acme",
                project_name="Acme",
                repositories=[RepositoryConfig(name="app", path=".")],
                pipeline={"sonarqube": _OPT_OUT_SONAR},  # type: ignore[arg-type]
            )

    def test_codeproducing_available_enabled_with_endpoint_ok(self) -> None:
        cfg = _project(
            {
                "available": True,
                "enabled": True,
                "base_url": "http://jenkins:8080",
                "token_env": "JENKINS_TOKEN",
                "pipeline": "ak3-pre-merge",
            }
        )
        assert cfg.pipeline.ci is not None
        assert cfg.pipeline.ci.available is True

    def test_codeproducing_available_false_is_permitted(self) -> None:
        cfg = _project({"available": False, "enabled": False})
        assert cfg.pipeline.ci is not None
        assert cfg.pipeline.ci.available is False

    def test_codeproducing_available_true_enabled_false_rejected(self) -> None:
        with pytest.raises(ValidationError, match="must not set ci.enabled=false"):
            _project(
                {
                    "available": True,
                    "enabled": False,
                    "base_url": "http://jenkins:8080",
                    "token_env": "JENKINS_TOKEN",
                    "pipeline": "ak3-pre-merge",
                }
            )

    def test_non_codeproducing_may_omit_ci(self) -> None:
        cfg = ProjectConfig(
            project_key="acme",
            project_name="Acme",
            repositories=[],
            story_types=["concept", "research"],
        )
        assert cfg.pipeline.ci is None
