"""Unit tests for agentkit.backend.config.validators."""

from __future__ import annotations

from pathlib import Path

from agentkit.backend.config.models import (
    SUPPORTED_CONFIG_VERSION,
    Features,
    JenkinsConfig,
    PipelineConfig,
    ProjectConfig,
    RepositoryConfig,
    SonarQubeConfig,
)
from agentkit.backend.config.validators import validate_project_config

#: AG3-052 E6: code-producing projects must declare sonarqube explicitly.
_OPT_OUT_SONAR = SonarQubeConfig(available=False, enabled=False)
#: AG3-056: code-producing projects must declare the ci stanza explicitly.
_OPT_OUT_CI = JenkinsConfig(available=False, enabled=False)


def _pipeline(**kwargs: object) -> PipelineConfig:
    """PipelineConfig with explicit config_version, sonarqube + ci opt-outs (E6 / AG3-056).

    Uses ``features=Features(multi_llm=False)`` by default for single-LLM fixtures.
    VectorDB is mandatory (AG3-176): supplies a default endpoint stanza.
    """
    from agentkit.backend.config.models import VectorDbConfig

    kwargs.setdefault("features", Features(multi_llm=False))
    kwargs.setdefault(
        "vectordb",
        VectorDbConfig(host="weaviate.test.local", port=19903, grpc_port=50051),
    )
    return PipelineConfig(  # type: ignore[arg-type]
        config_version=SUPPORTED_CONFIG_VERSION,
        sonarqube=_OPT_OUT_SONAR,
        ci=_OPT_OUT_CI,
        **kwargs,
    )


def _minimal_config(**overrides: object) -> ProjectConfig:
    """Create a minimal ProjectConfig with optional overrides.

    Injects an explicit pipeline by default (FK-03 §3.2.1: pipeline is a
    required field, no silent default). The default pipeline uses sonarqube +
    ci opt-outs (AG3-052 E6 / AG3-056) so the fixture is valid for both
    code-producing and non-code-producing story types.
    """
    defaults: dict[str, object] = {
        "project_key": "test-project",
        "project_name": "test",
        "repositories": [RepositoryConfig(name="r", path=Path("/tmp"))],
    }
    defaults.update(overrides)
    if "pipeline" not in defaults:
        defaults["pipeline"] = _pipeline()
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
            pipeline=_pipeline(),
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
            pipeline=_pipeline(max_feedback_rounds=0),
        )
        warnings = validate_project_config(cfg)
        assert any("max_feedback_rounds" in w for w in warnings)

    def test_warns_empty_verify_layers(self) -> None:
        cfg = _minimal_config(
            pipeline=_pipeline(verify_layers=[]),
        )
        warnings = validate_project_config(cfg)
        assert any("No verify_layers" in w for w in warnings)

    def test_warns_unknown_verify_layers(self) -> None:
        cfg = _minimal_config(
            pipeline=_pipeline(verify_layers=["structural", "unknown_layer"]),
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
