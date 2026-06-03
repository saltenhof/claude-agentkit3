"""Unit tests for PlaceholderSubstitutor (AG3-027, FK-43 §43.4.2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentkit.config.models import (
    PipelineConfig,
    ProjectConfig,
    RepositoryConfig,
    SonarQubeConfig,
)
from agentkit.skills.errors import UnknownPlaceholderError
from agentkit.skills.placeholder import PlaceholderSubstitutor

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

#: AG3-052 E6: code-producing default story_types must declare sonarqube.
_OPT_OUT_PIPELINE = PipelineConfig(
    sonarqube=SonarQubeConfig(available=False, enabled=False)
)


def _project_config(
    *,
    project_key: str = "my-proj",
    github_owner: str | None = "my-org",
    github_repo: str | None = "my-repo",
) -> ProjectConfig:
    return ProjectConfig(
        project_key=project_key,
        project_name="My Project",
        repositories=[RepositoryConfig(name="app", path=Path("."))],
        github_owner=github_owner,
        github_repo=github_repo,
        pipeline=_OPT_OUT_PIPELINE,
    )


# ---------------------------------------------------------------------------
# Happy paths — four mandatory placeholders
# ---------------------------------------------------------------------------

class TestMandatoryPlaceholders:
    def setup_method(self) -> None:
        self.sub = PlaceholderSubstitutor()
        self.cfg = _project_config()

    def test_gh_owner(self) -> None:
        result = self.sub.substitute("Owner: {{gh_owner}}", self.cfg)
        assert result == "Owner: my-org"

    def test_gh_repo(self) -> None:
        # FK-43 §43.4.2: gh_repo source is config.repositories[0].name
        result = self.sub.substitute("Repo: {{gh_repo}}", self.cfg)
        assert result == "Repo: app"

    def test_project_key(self) -> None:
        result = self.sub.substitute("Key: {{project_key}}", self.cfg)
        assert result == "Key: my-proj"

    def test_project_prefix(self) -> None:
        # FK-03 §3.2 / Pass-2: project_prefix defaults to project_key.upper()
        result = self.sub.substitute("Prefix: {{project_prefix}}", self.cfg)
        assert result == "Prefix: MY-PROJ"

    def test_all_four_together(self) -> None:
        template = (
            "owner={{gh_owner}} repo={{gh_repo}} "
            "key={{project_key}} prefix={{project_prefix}}"
        )
        result = self.sub.substitute(template, self.cfg)
        assert result == "owner=my-org repo=app key=my-proj prefix=MY-PROJ"

    def test_no_placeholders_passthrough(self) -> None:
        result = self.sub.substitute("no placeholders here", self.cfg)
        assert result == "no placeholders here"

    def test_repeated_placeholder(self) -> None:
        result = self.sub.substitute("{{project_key}}/{{project_key}}", self.cfg)
        assert result == "my-proj/my-proj"

    def test_none_github_owner_becomes_empty_string(self) -> None:
        cfg = _project_config(github_owner=None)
        result = self.sub.substitute("{{gh_owner}}", cfg)
        assert result == ""

    def test_explicit_project_prefix_overrides_default(self) -> None:
        # FK-03 §3.2 / FK-43 §43.4.2: explicit project_prefix wins.
        cfg = ProjectConfig(
            project_key="my-proj",
            project_name="My Project",
            project_prefix="ACME",
            repositories=[RepositoryConfig(name="app", path=Path("."))],
            pipeline=_OPT_OUT_PIPELINE,
        )
        result = self.sub.substitute("Prefix: {{project_prefix}}", cfg)
        assert result == "Prefix: ACME"

    def test_empty_repositories_raises_value_error(self) -> None:
        # FK-43 §43.4.2: gh_repo has no canonical source without a repository.
        cfg = ProjectConfig(
            project_key="my-proj",
            project_name="My Project",
            repositories=[],
            pipeline=_OPT_OUT_PIPELINE,
        )
        with pytest.raises(ValueError, match="gh_repo"):
            self.sub.substitute("{{gh_repo}}", cfg)


# ---------------------------------------------------------------------------
# Fail-closed: unknown placeholder
# ---------------------------------------------------------------------------

class TestUnknownPlaceholderError:
    def setup_method(self) -> None:
        self.sub = PlaceholderSubstitutor()
        self.cfg = _project_config()

    def test_unknown_placeholder_raises(self) -> None:
        with pytest.raises(UnknownPlaceholderError):
            self.sub.substitute("{{unknown_token}}", self.cfg)

    def test_error_detail_contains_placeholder(self) -> None:
        with pytest.raises(UnknownPlaceholderError) as exc_info:
            self.sub.substitute("{{bad_key}}", self.cfg)
        assert "bad_key" in exc_info.value.detail["placeholder"]

    def test_error_detail_contains_supported_list(self) -> None:
        with pytest.raises(UnknownPlaceholderError) as exc_info:
            self.sub.substitute("{{bad_key}}", self.cfg)
        supported = exc_info.value.detail["supported"]
        assert "gh_owner" in supported
        assert "gh_repo" in supported
        assert "project_key" in supported
        assert "project_prefix" in supported

    def test_first_occurrence_raises_immediately(self) -> None:
        # Substitution should raise on the first bad token it encounters.
        with pytest.raises(UnknownPlaceholderError):
            self.sub.substitute("{{gh_owner}} {{nope}} {{project_key}}", self.cfg)
