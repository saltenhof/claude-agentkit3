"""Unit tests for agentkit.config.validators."""

from __future__ import annotations

from pathlib import Path

from agentkit.config.models import PipelineConfig, ProjectConfig, RepositoryConfig
from agentkit.config.validators import validate_project_config


def _minimal_config(**overrides: object) -> ProjectConfig:
    """Create a minimal ProjectConfig with optional overrides."""
    defaults: dict[str, object] = {
        "project_key": "test-project",
        "project_name": "test",
        "repositories": [RepositoryConfig(name="r", path=Path("/tmp"))],
    }
    defaults.update(overrides)
    return ProjectConfig(**defaults)  # type: ignore[arg-type]


class TestValidateProjectConfig:
    """Tests for validate_project_config."""

    def test_no_warnings_when_fully_configured(self) -> None:
        cfg = ProjectConfig(
            project_key="test-project",
            project_name="test",
            repositories=[
                RepositoryConfig(
                    name="repo",
                    path=Path("/tmp/repo"),
                    language="python",
                    test_command="pytest",
                ),
            ],
            github_owner="owner",
            github_repo="repo",
        )
        warnings = validate_project_config(cfg)
        assert warnings == []

    def test_warns_no_repositories(self) -> None:
        cfg = _minimal_config(repositories=[])
        warnings = validate_project_config(cfg)
        assert any("No repositories defined" in w for w in warnings)

    def test_warns_missing_test_command(self) -> None:
        cfg = _minimal_config()
        warnings = validate_project_config(cfg)
        assert any("no test_command" in w for w in warnings)

    def test_warns_missing_language(self) -> None:
        cfg = _minimal_config()
        warnings = validate_project_config(cfg)
        assert any("no language" in w for w in warnings)

    def test_warns_missing_github(self) -> None:
        cfg = _minimal_config()
        warnings = validate_project_config(cfg)
        assert any("GitHub integration" in w for w in warnings)

    def test_warns_zero_feedback_rounds(self) -> None:
        cfg = _minimal_config(
            pipeline=PipelineConfig(max_feedback_rounds=0),
        )
        warnings = validate_project_config(cfg)
        assert any("max_feedback_rounds" in w for w in warnings)

    def test_warns_empty_verify_layers(self) -> None:
        cfg = _minimal_config(
            pipeline=PipelineConfig(verify_layers=[]),
        )
        warnings = validate_project_config(cfg)
        assert any("No verify_layers" in w for w in warnings)

    def test_warns_unknown_verify_layers(self) -> None:
        cfg = _minimal_config(
            pipeline=PipelineConfig(verify_layers=["structural", "unknown_layer"]),
        )
        warnings = validate_project_config(cfg)
        assert any("Unknown verify layers" in w for w in warnings)

    def test_warns_empty_story_types(self) -> None:
        cfg = _minimal_config(story_types=[])
        warnings = validate_project_config(cfg)
        assert any("No story_types" in w for w in warnings)

    def test_returns_list(self) -> None:
        cfg = _minimal_config()
        warnings = validate_project_config(cfg)
        assert isinstance(warnings, list)
        assert all(isinstance(w, str) for w in warnings)
