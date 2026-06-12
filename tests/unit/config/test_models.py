"""Unit tests for agentkit.config.models."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from agentkit.config.models import (
    SUPPORTED_CONFIG_VERSION,
    AreConfig,
    Features,
    JenkinsConfig,
    PipelineConfig,
    ProjectConfig,
    RepositoryConfig,
    ReviewConfig,
    SonarQubeConfig,
    _coerce_path,
)

#: AG3-052 E6: a code-producing project (default story_types) must DECLARE the
#: sonarqube stanza explicitly. Tests that are NOT about the gate declare an
#: explicit opt-out (``available: false`` => gate not-applicable, legal).
_OPT_OUT_SONAR = SonarQubeConfig(available=False, enabled=False)
#: AG3-056: a code-producing project must likewise DECLARE the ci stanza
#: explicitly. Tests not about the runner declare an explicit opt-out.
_OPT_OUT_CI = JenkinsConfig(available=False, enabled=False)


def _opt_out_pipeline(**kwargs: object) -> PipelineConfig:
    """Build a PipelineConfig with explicit config_version, sonarqube + ci opt-outs.

    Uses ``features=Features(multi_llm=False)`` by default for fixtures that do
    not test multi-LLM behaviour (single-LLM mode, no llm_roles required).
    """
    from agentkit.config.models import SUPPORTED_CONFIG_VERSION, Features

    kwargs.setdefault("features", Features(multi_llm=False))
    return PipelineConfig(  # type: ignore[arg-type]
        config_version=SUPPORTED_CONFIG_VERSION,
        sonarqube=_OPT_OUT_SONAR,
        ci=_OPT_OUT_CI,
        **kwargs,
    )


class TestPipelineConfig:
    """Tests for PipelineConfig."""

    def test_defaults(self) -> None:
        cfg = PipelineConfig(  # type: ignore[call-arg]
            config_version="3.0", features=Features(multi_llm=False)
        )
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
        cfg = PipelineConfig(  # type: ignore[call-arg]
            config_version=SUPPORTED_CONFIG_VERSION,
            features=Features(multi_llm=False),
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

    def test_review_required_roles_default_empty(self) -> None:
        # AG3-036 §2.1.5 / FIX-2: review.required_roles is the authoritative
        # source for ReviewGuard; default is empty (no mandatory coverage).
        cfg = PipelineConfig(  # type: ignore[call-arg]
            config_version=SUPPORTED_CONFIG_VERSION, features=Features(multi_llm=False)
        )
        assert cfg.review.required_roles == []

    def test_review_required_roles_custom(self) -> None:
        cfg = PipelineConfig(  # type: ignore[call-arg]
            config_version=SUPPORTED_CONFIG_VERSION,
            features=Features(multi_llm=False),
            review=ReviewConfig(required_roles=["qa", "security"]),
        )
        assert cfg.review.required_roles == ["qa", "security"]


class TestReviewConfig:
    """Tests for ReviewConfig (AG3-036 §2.1.5)."""

    def test_default_is_empty(self) -> None:
        assert ReviewConfig().required_roles == []

    def test_rejects_extra_fields(self) -> None:
        with pytest.raises(ValidationError):
            ReviewConfig(unknown="x")  # type: ignore[call-arg]

    def test_is_frozen(self) -> None:
        cfg = ReviewConfig(required_roles=["qa"])
        with pytest.raises(ValidationError):
            cfg.required_roles = ["security"]  # type: ignore[misc]


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
        # AG3-113: wiki_stories_dir default (FK-03 §3.1 / FK-43 §43.4.2).
        assert cfg.wiki_stories_dir == "stories"

    def test_wiki_stories_dir_custom_relative(self) -> None:
        cfg = ProjectConfig(
            project_key="p",
            project_name="p",
            repositories=[RepositoryConfig(name="r", path=Path("/tmp"))],
            pipeline=_opt_out_pipeline(),
            wiki_stories_dir="docs/stories",
        )
        assert cfg.wiki_stories_dir == "docs/stories"

    def test_wiki_stories_dir_trimmed(self) -> None:
        cfg = ProjectConfig(
            project_key="p",
            project_name="p",
            repositories=[RepositoryConfig(name="r", path=Path("/tmp"))],
            pipeline=_opt_out_pipeline(),
            wiki_stories_dir="  stories  ",
        )
        assert cfg.wiki_stories_dir == "stories"

    @pytest.mark.parametrize(
        "bad",
        [
            "",
            "   ",
            "/abs/stories",
            "../stories",
            "a/../b",
            "C:\\stories",
            "C:stories",
        ],
    )
    def test_wiki_stories_dir_invalid_fails_closed(self, bad: str) -> None:
        # FK-03 §3.1 fail-closed: non-empty, project-relative, no '..', no absolute.
        with pytest.raises(ValidationError):
            ProjectConfig(
                project_key="p",
                project_name="p",
                repositories=[RepositoryConfig(name="r", path=Path("/tmp"))],
                pipeline=_opt_out_pipeline(),
                wiki_stories_dir=bad,
            )

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
            pipeline=_opt_out_pipeline(features=Features(are=False, multi_llm=False)),
        )
        assert cfg.are is None

    def test_enabled_without_are_section_raises(self) -> None:
        with pytest.raises(ValidationError, match="FK-03 §3.2.1"):
            ProjectConfig(
                project_key="p",
                project_name="P",
                repositories=[],
                pipeline=PipelineConfig(  # type: ignore[call-arg]
                    config_version=SUPPORTED_CONFIG_VERSION,
                    features=Features(are=True, multi_llm=False),
                ),
            )

    def test_enabled_with_are_section_ok(self) -> None:
        cfg = ProjectConfig(
            project_key="p",
            project_name="P",
            repositories=[],
            pipeline=_opt_out_pipeline(features=Features(are=True, multi_llm=False)),
            are=AreConfig(mcp_server="https://are.example.com/mcp"),
        )
        assert cfg.are is not None
        assert cfg.are.mcp_server == "https://are.example.com/mcp"

class TestSonarqubeDeclaredExplicitly:
    """AG3-052 E6 / FK-03 §3: code-producing project must declare sonarqube."""

    def test_codeproducing_without_sonarqube_stanza_raises(self) -> None:
        """Omitted sonarqube stanza on a code-producing project => fail-closed ValueError.

        pipeline is required (FK-03 §3.2.1); the stanza is provided but without
        a sonarqube key to isolate the sonarqube fail-closed rule.
        """
        with pytest.raises(ValidationError, match="must DECLARE the 'sonarqube'"):
            ProjectConfig(
                project_key="p",
                project_name="P",
                repositories=[RepositoryConfig(name="r", path=Path("/tmp"))],
                # pipeline provided but sonarqube stanza omitted — fail-closed
                pipeline=PipelineConfig(  # type: ignore[call-arg]
                    config_version=SUPPORTED_CONFIG_VERSION,
                    features=Features(multi_llm=False),
                    ci=_OPT_OUT_CI,
                    # sonarqube intentionally absent
                ),
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
            pipeline=PipelineConfig(  # type: ignore[call-arg]
                config_version=SUPPORTED_CONFIG_VERSION,
                features=Features(multi_llm=False),
                sonarqube=SonarQubeConfig(
                    available=True,
                    enabled=True,
                    base_url="http://sonar:9901",
                    token_env="SONARQUBE_TOKEN",
                    scanner_version="5.0.1",
                ),
                ci=_OPT_OUT_CI,
            ),
        )
        assert cfg.pipeline.sonarqube is not None
        assert cfg.pipeline.sonarqube.available is True

    def test_non_codeproducing_may_omit_sonarqube(self) -> None:
        """Concept/research-only projects may omit the sonarqube stanza.

        pipeline is required (FK-03 §3.2.1); a minimal pipeline with only
        config_version is sufficient for a non-code-producing project.
        """
        cfg = ProjectConfig(
            project_key="p",
            project_name="P",
            repositories=[],
            story_types=["concept", "research"],
            pipeline=PipelineConfig(  # type: ignore[call-arg]
                config_version=SUPPORTED_CONFIG_VERSION,
                features=Features(multi_llm=False),
            ),
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


class TestPermissionsConfig:
    """AG3-086 (FK-93 §93.5a): the typed permission-request TTL config key."""

    def test_default_is_fk93_1800(self) -> None:
        from agentkit.config.models import PermissionsConfig

        assert PermissionsConfig().request_ttl_s == 1800

    def test_positive_value_accepted(self) -> None:
        from agentkit.config.models import PermissionsConfig

        assert PermissionsConfig(request_ttl_s=600).request_ttl_s == 600

    def test_zero_rejected(self) -> None:
        from agentkit.config.models import PermissionsConfig

        with pytest.raises(ValidationError, match="positive integer"):
            PermissionsConfig(request_ttl_s=0)

    def test_negative_rejected(self) -> None:
        from agentkit.config.models import PermissionsConfig

        with pytest.raises(ValidationError, match="FK-93"):
            PermissionsConfig(request_ttl_s=-5)

    def test_extra_field_rejected(self) -> None:
        from agentkit.config.models import PermissionsConfig

        with pytest.raises(ValidationError):
            PermissionsConfig(unknown="x")  # type: ignore[call-arg]
