"""Unit tests for agentkit.config.models."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from agentkit.config.models import (
    AreConfig,
    Features,
    PipelineConfig,
    ProjectConfig,
    RepositoryConfig,
    SonarQubeConfig,
    _coerce_path,
)

#: AG3-052 E6: a code-producing project (default story_types) must DECLARE the
#: sonarqube stanza explicitly. Tests that are NOT about the gate declare an
#: explicit opt-out (``available: false`` => gate not-applicable, legal).
_OPT_OUT_SONAR = SonarQubeConfig(available=False, enabled=False)


def _opt_out_pipeline(**kwargs: object) -> PipelineConfig:
    """Build a PipelineConfig with an explicit sonarqube opt-out (E6)."""
    return PipelineConfig(sonarqube=_OPT_OUT_SONAR, **kwargs)  # type: ignore[arg-type]


class TestPipelineConfig:
    """Tests for PipelineConfig."""

    def test_defaults(self) -> None:
        cfg = PipelineConfig()
        assert cfg.max_feedback_rounds == 3
        assert cfg.max_remediation_rounds == 2
        assert cfg.exploration_mode is True
        assert cfg.verify_layers == [
            "structural",
            "semantic",
            "adversarial",
            "policy",
        ]

    def test_custom_values(self) -> None:
        cfg = PipelineConfig(
            max_feedback_rounds=5,
            max_remediation_rounds=1,
            exploration_mode=False,
            verify_layers=["structural", "policy"],
        )
        assert cfg.max_feedback_rounds == 5
        assert cfg.max_remediation_rounds == 1
        assert cfg.exploration_mode is False
        assert cfg.verify_layers == ["structural", "policy"]

    def test_strict_rejects_string_for_int(self) -> None:
        with pytest.raises(ValidationError):
            PipelineConfig(max_feedback_rounds="3")  # type: ignore[arg-type]

    def test_strict_rejects_string_for_bool(self) -> None:
        with pytest.raises(ValidationError):
            PipelineConfig(exploration_mode="yes")  # type: ignore[arg-type]


class TestRepositoryConfig:
    """Tests for RepositoryConfig."""

    def test_minimal(self) -> None:
        repo = RepositoryConfig(name="my-repo", path=Path("/tmp/repo"))
        assert repo.name == "my-repo"
        assert repo.path == Path("/tmp/repo")
        assert repo.language is None
        assert repo.test_command is None
        assert repo.build_command is None

    def test_all_fields(self) -> None:
        repo = RepositoryConfig(
            name="backend",
            path=Path("/opt/backend"),
            language="python",
            test_command="pytest",
            build_command="pip install -e .",
        )
        assert repo.language == "python"
        assert repo.test_command == "pytest"
        assert repo.build_command == "pip install -e ."

    def test_path_coercion_from_string(self) -> None:
        """Path field accepts strings and coerces to Path (for YAML compat)."""
        repo = RepositoryConfig(name="r", path="/some/path")  # type: ignore[arg-type]
        assert isinstance(repo.path, Path)
        assert repo.path == Path("/some/path")

    def test_path_coercion_rejects_invalid_type(self) -> None:
        """_coerce_path raises TypeError for non-str/non-Path values."""
        with pytest.raises(TypeError, match="Expected str or Path"):
            _coerce_path(42)

    def test_missing_name_raises(self) -> None:
        with pytest.raises(ValidationError):
            RepositoryConfig(path=Path("/tmp"))  # type: ignore[call-arg]

    def test_missing_path_raises(self) -> None:
        with pytest.raises(ValidationError):
            RepositoryConfig(name="x")  # type: ignore[call-arg]


class TestProjectConfig:
    """Tests for ProjectConfig."""

    def test_minimal(self) -> None:
        cfg = ProjectConfig(
            project_key="test-project",
            project_name="test",
            repositories=[RepositoryConfig(name="r", path=Path("/tmp"))],
            pipeline=_opt_out_pipeline(),
        )
        assert cfg.project_key == "test-project"
        assert cfg.project_name == "test"
        assert len(cfg.repositories) == 1
        assert cfg.pipeline.max_feedback_rounds == 3
        assert cfg.story_types == [
            "implementation",
            "bugfix",
            "concept",
            "research",
        ]
        assert cfg.github_owner is None
        assert cfg.github_repo is None

    def test_all_fields(self) -> None:
        cfg = ProjectConfig(
            project_key="full-project",
            project_name="full",
            repositories=[RepositoryConfig(name="r", path=Path("/tmp"))],
            pipeline=_opt_out_pipeline(max_feedback_rounds=1),
            story_types=["bugfix"],
            github_owner="owner",
            github_repo="repo",
        )
        assert cfg.github_owner == "owner"
        assert cfg.github_repo == "repo"
        assert cfg.pipeline.max_feedback_rounds == 1
        assert cfg.story_types == ["bugfix"]

    def test_missing_project_name_raises(self) -> None:
        with pytest.raises(ValidationError):
            ProjectConfig(
                project_key="test-project",
                repositories=[RepositoryConfig(name="r", path=Path("/tmp"))]
            )  # type: ignore[call-arg]

    def test_missing_repositories_raises(self) -> None:
        with pytest.raises(ValidationError):
            ProjectConfig(project_key="test-project", project_name="test")  # type: ignore[call-arg]

    def test_empty_repositories_accepted(self) -> None:
        """Empty list is structurally valid (semantic validator warns)."""
        cfg = ProjectConfig(
            project_key="test-project",
            project_name="test",
            repositories=[],
            pipeline=_opt_out_pipeline(),
        )
        assert cfg.repositories == []

    def test_default_pipeline_is_independent_instance(self) -> None:
        """Each ProjectConfig gets its own PipelineConfig instance."""
        cfg1 = ProjectConfig(
            project_key="a", project_name="a", repositories=[],
            pipeline=_opt_out_pipeline(),
        )
        cfg2 = ProjectConfig(
            project_key="b", project_name="b", repositories=[],
            pipeline=_opt_out_pipeline(),
        )
        cfg1.pipeline.max_feedback_rounds = 99
        assert cfg2.pipeline.max_feedback_rounds == 3


class TestAreSectionRequiredWhenEnabled:
    """FK-03 §3.2.1: pipeline.features.are=True requires an 'are' section."""

    def test_disabled_without_are_section_ok(self) -> None:
        cfg = ProjectConfig(
            project_key="p",
            project_name="P",
            repositories=[],
            pipeline=_opt_out_pipeline(features=Features(are=False)),
        )
        assert cfg.are is None

    def test_enabled_without_are_section_raises(self) -> None:
        with pytest.raises(ValidationError, match="FK-03 §3.2.1"):
            ProjectConfig(
                project_key="p",
                project_name="P",
                repositories=[],
                pipeline=PipelineConfig(features=Features(are=True)),
            )

    def test_enabled_with_are_section_ok(self) -> None:
        cfg = ProjectConfig(
            project_key="p",
            project_name="P",
            repositories=[],
            pipeline=_opt_out_pipeline(features=Features(are=True)),
            are=AreConfig(mcp_server="https://are.example.com/mcp"),
        )
        assert cfg.are is not None
        assert cfg.are.mcp_server == "https://are.example.com/mcp"

class TestSonarqubeDeclaredExplicitly:
    """AG3-052 E6 / FK-03 §3: code-producing project must declare sonarqube."""

    def test_codeproducing_without_sonarqube_stanza_raises(self) -> None:
        """Omitted stanza on a code-producing project => fail-closed ValueError."""
        with pytest.raises(ValidationError, match="must DECLARE the 'sonarqube'"):
            ProjectConfig(
                project_key="p",
                project_name="P",
                repositories=[RepositoryConfig(name="r", path=Path("/tmp"))],
                # default story_types are code-producing; pipeline.sonarqube omitted
            )

    def test_codeproducing_with_explicit_available_false_ok(self) -> None:
        """An explicit available:false opt-out stays legal (declared absence)."""
        cfg = ProjectConfig(
            project_key="p",
            project_name="P",
            repositories=[RepositoryConfig(name="r", path=Path("/tmp"))],
            pipeline=_opt_out_pipeline(),
        )
        assert cfg.pipeline.sonarqube is not None
        assert cfg.pipeline.sonarqube.available is False

    def test_codeproducing_with_available_true_ok(self) -> None:
        """An explicit available:true (+endpoint) declaration is legal."""
        cfg = ProjectConfig(
            project_key="p",
            project_name="P",
            repositories=[RepositoryConfig(name="r", path=Path("/tmp"))],
            pipeline=PipelineConfig(
                sonarqube=SonarQubeConfig(
                    available=True,
                    enabled=True,
                    base_url="http://sonar:9901",
                    token_env="SONARQUBE_TOKEN",
                )
            ),
        )
        assert cfg.pipeline.sonarqube is not None
        assert cfg.pipeline.sonarqube.available is True

    def test_non_codeproducing_may_omit_sonarqube(self) -> None:
        """Concept/research-only projects may omit the stanza entirely."""
        cfg = ProjectConfig(
            project_key="p",
            project_name="P",
            repositories=[],
            story_types=["concept", "research"],
        )
        assert cfg.pipeline.sonarqube is None


class TestExtraFields:
    def test_extra_top_level_field_rejected(self) -> None:
        """ProjectConfig must reject unknown top-level fields (extra=forbid)."""
        with pytest.raises(ValidationError):
            ProjectConfig(  # type: ignore[call-arg]
                project_key="p",
                project_name="P",
                repositories=[],
                unknown_field="oops",
            )
