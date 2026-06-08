"""Unit tests for the SonarQube config stanza (FK-03 §3, AG3-052 AC7).

Covers the cross-field validation rules verbatim per FK-03/§2.1.6:
* available+enabled require base_url+token_env (fail-closed);
* code-producing + available + not enabled is illegal;
* available:false is permitted even for code-producing projects.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agentkit.config import ProjectConfig, SonarQubeConfig
from agentkit.config.models import RepositoryConfig


def _project(**pipeline_sonar: object) -> ProjectConfig:
    return ProjectConfig(
        project_key="acme",
        project_name="Acme",
        repositories=[RepositoryConfig(name="app", path=".")],
        # AG3-056: code-producing projects must also declare the ci stanza;
        # an explicit opt-out keeps these Sonar-focused tests isolated.
        # config_version is mandatory (FK-03 §3.2.1); features.multi_llm=False
        # for this single-LLM test fixture.
        pipeline={  # type: ignore[arg-type]
            "config_version": "3.0",
            "features": {"multi_llm": False},
            "sonarqube": pipeline_sonar,
            "ci": {"available": False, "enabled": False},
        },
    )


class TestSonarQubeConfigStandalone:
    def test_defaults_are_available_and_enabled(self) -> None:
        """FK-03 §3: the green-gate is the DEFAULT for code-producing projects.

        A bare/empty ``sonarqube: {}`` stanza must NOT be a silent opt-out.
        The core default is ``available/enabled == true``; the missing
        endpoint then fails closed (next test), forcing either an explicit
        endpoint or a conscious ``available: false`` opt-out.
        """
        with pytest.raises(ValidationError, match="base_url and token_env"):
            SonarQubeConfig()

    def test_explicit_opt_out_disables(self) -> None:
        """``available:false`` stays a legal, explicit, conscious opt-out."""
        cfg = SonarQubeConfig(available=False, enabled=False)
        assert cfg.available is False
        assert cfg.enabled is False

    def test_available_enabled_requires_endpoint(self) -> None:
        with pytest.raises(ValidationError, match="base_url and token_env"):
            SonarQubeConfig(available=True, enabled=True)

    def test_available_enabled_with_endpoint_ok(self) -> None:
        cfg = SonarQubeConfig(
            available=True,
            enabled=True,
            base_url="http://sonar:9901",
            token_env="SONARQUBE_TOKEN",
            scanner_version="5.0.1",
        )
        assert cfg.base_url == "http://sonar:9901"

    def test_available_enabled_requires_scanner_version(self) -> None:
        """ERROR-B: scanner_version is a mandatory attestation binding."""
        with pytest.raises(ValidationError, match="scanner_version"):
            SonarQubeConfig(
                available=True,
                enabled=True,
                base_url="http://sonar:9901",
                token_env="SONARQUBE_TOKEN",
            )

    def test_rejects_unparsable_scanner_version(self) -> None:
        with pytest.raises(ValidationError, match="SemVer"):
            SonarQubeConfig(
                available=True,
                enabled=True,
                base_url="http://sonar:9901",
                token_env="SONARQUBE_TOKEN",
                scanner_version="not-a-version",
            )

    def test_rejects_unparsable_min_version(self) -> None:
        with pytest.raises(ValidationError, match="SemVer"):
            SonarQubeConfig(min_version="not-a-version")

    def test_rejects_extra_field(self) -> None:
        with pytest.raises(ValidationError):
            SonarQubeConfig(unknown_field=True)  # type: ignore[call-arg]


class TestCrossFieldRule:
    def test_codeproducing_available_not_enabled_is_illegal(self) -> None:
        """impl/bugfix project + available:true + enabled:false -> ValueError."""
        with pytest.raises(ValidationError, match="must not\\s+set sonarqube.enabled=false"):
            _project(available=True, enabled=False)

    def test_codeproducing_available_false_is_permitted(self) -> None:
        """available:false stays legal for a code-producing project (NOT_APPLICABLE)."""
        project = _project(available=False, enabled=False)
        assert project.pipeline.sonarqube.available is False

    def test_codeproducing_available_enabled_with_endpoint_ok(self) -> None:
        project = _project(
            available=True,
            enabled=True,
            base_url="http://sonar:9901",
            token_env="SONARQUBE_TOKEN",
            scanner_version="5.0.1",
        )
        assert project.pipeline.sonarqube.enabled is True

    def test_codeproducing_empty_stanza_fails_closed(self) -> None:
        """FK-03 §3: a present-but-empty ``sonarqube: {}`` is NOT a silent opt-out.

        With the core default ``available/enabled == true`` the empty stanza
        resolves to a declared-present, switched-on gate WITHOUT an endpoint,
        which fails closed (ValueError) — forcing an explicit endpoint or a
        conscious ``available: false`` opt-out (no silent disable by omission).
        """
        with pytest.raises(ValidationError, match="base_url and token_env"):
            _project()

    def test_concept_research_only_may_disable(self) -> None:
        """A non-code-producing project may set available:true + enabled:false."""
        project = ProjectConfig(
            project_key="docs",
            project_name="Docs",
            repositories=[RepositoryConfig(name="app", path=".")],
            story_types=["concept", "research"],
            pipeline={  # type: ignore[arg-type]
                "config_version": "3.0",
                "features": {"multi_llm": False},
                "sonarqube": {"available": True, "enabled": False},
            },
        )
        assert project.pipeline.sonarqube.enabled is False
