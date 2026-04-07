"""Unit tests for agentkit.config.models."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from agentkit.config.models import (
    PipelineConfig,
    ProjectConfig,
    RepositoryConfig,
    _coerce_path,
)


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
            project_name="test",
            repositories=[RepositoryConfig(name="r", path=Path("/tmp"))],
        )
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
            project_name="full",
            repositories=[RepositoryConfig(name="r", path=Path("/tmp"))],
            pipeline=PipelineConfig(max_feedback_rounds=1),
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
                repositories=[RepositoryConfig(name="r", path=Path("/tmp"))]
            )  # type: ignore[call-arg]

    def test_missing_repositories_raises(self) -> None:
        with pytest.raises(ValidationError):
            ProjectConfig(project_name="test")  # type: ignore[call-arg]

    def test_empty_repositories_accepted(self) -> None:
        """Empty list is structurally valid (semantic validator warns)."""
        cfg = ProjectConfig(project_name="test", repositories=[])
        assert cfg.repositories == []

    def test_default_pipeline_is_independent_instance(self) -> None:
        """Each ProjectConfig gets its own PipelineConfig instance."""
        cfg1 = ProjectConfig(project_name="a", repositories=[])
        cfg2 = ProjectConfig(project_name="b", repositories=[])
        cfg1.pipeline.max_feedback_rounds = 99
        assert cfg2.pipeline.max_feedback_rounds == 3
