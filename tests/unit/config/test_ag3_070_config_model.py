"""Unit tests for AG3-070: Config model full build + schema-catalog.

Covers all acceptance criteria from AG3-070:
- AC1: config_version Pflichtfeld + fail-closed Loader
- AC2: FeaturesConfig six flags + e2e_assertions requires db
- AC3: multi_llm + llm_roles + required roles
- AC4: five new stanzas with FK-03 defaults
- AC4a: sonarqube.accept_frequency_fc_threshold default + range
- AC5/6: config_version versioning cut + owner
- AC7: config_version as migration anchor (loader exposes version)
- AC8: ARCH-55 (all English — checked by naming conventions)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
import yaml
from pydantic import ValidationError

from agentkit.config import (
    REQUIRED_LLM_ROLES,
    SUPPORTED_CONFIG_VERSION,
    GovernanceConfig,
    LlmRolesConfig,
    OrchestratorGuardConfig,
    PipelineConfig,
    PipelinePolicyConfig,
    PolicyConfig,
    ProjectConfig,
    SonarQubeConfig,
    TelemetryConfig,
    VectorDbConfig,
)
from agentkit.config.loader import load_project_config
from agentkit.config.models import (
    Features,
    JenkinsConfig,
    StageOverride,
    StageOverrideConfig,
)
from agentkit.exceptions import ConfigError

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

_OPT_OUT_SONAR = SonarQubeConfig(available=False, enabled=False)
_OPT_OUT_CI = JenkinsConfig(available=False, enabled=False)


def _minimal_pipeline(**kwargs: Any) -> PipelineConfig:
    """Build a PipelineConfig with explicit config_version, sonarqube + ci opt-outs.

    ``features=Features(multi_llm=False)`` is the default for fixtures that do
    not test multi-LLM behaviour (single-LLM mode, no llm_roles required).
    Override by passing ``features=Features(multi_llm=True)`` + ``llm_roles=...``
    when the test genuinely exercises multi-LLM paths.
    """
    kwargs.setdefault("features", Features(multi_llm=False))
    return PipelineConfig(  # type: ignore[arg-type]
        config_version=SUPPORTED_CONFIG_VERSION,
        sonarqube=_OPT_OUT_SONAR,
        ci=_OPT_OUT_CI,
        **kwargs,
    )


def _concept_project(**kwargs: Any) -> ProjectConfig:
    """Build a non-code-producing ProjectConfig (no sonarqube/ci required).

    Provides a minimal FK-conformant pipeline with config_version (required
    since pipeline is a mandatory field — FK-03 §3.2.1 fail-closed).
    Override ``pipeline`` via kwargs to test specific pipeline configurations.
    """
    kwargs.setdefault("pipeline", _minimal_pipeline())
    return ProjectConfig(
        project_key="test",
        project_name="Test",
        repositories=[],
        story_types=["concept"],
        **kwargs,
    )


def _write_yaml_config(tmp_path: Path, data: dict[str, Any]) -> None:
    config_dir = tmp_path / ".agentkit" / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "project.yaml").write_text(yaml.dump(data), encoding="utf-8")


# ===========================================================================
# AC1 — config_version Pflichtfeld + fail-closed Loader
# ===========================================================================


class TestConfigVersionField:
    """AC1: config_version is a required field with fail-closed validation."""

    def test_missing_config_version_fails_closed(self) -> None:
        """PipelineConfig without config_version must fail closed (AC1, no silent default).

        FK-03 §3.2.1: config_version is a mandatory field; omitting it is a
        hard error, not a warning.
        """
        with pytest.raises(ValidationError) as exc_info:
            PipelineConfig(features=Features(multi_llm=False))  # type: ignore[call-arg]
        # Must be a validation error about the missing required field
        assert "config_version" in str(exc_info.value)

    def test_explicit_3_0_accepted(self) -> None:
        """Explicit 'config_version: 3.0' is accepted."""
        cfg = PipelineConfig(config_version="3.0", features=Features(multi_llm=False))
        assert cfg.config_version == "3.0"

    def test_unknown_version_raises_value_error(self) -> None:
        """Unknown config_version must raise ValueError at model level (AC1a)."""
        with pytest.raises(ValidationError) as exc_info:
            PipelineConfig(config_version="4.0")
        # The model validator raises ValueError; Pydantic wraps it
        assert "Unsupported config_version" in str(exc_info.value)

    def test_unknown_version_raises_value_error_3_1(self) -> None:
        """config_version '3.1' is not '3.0' — must fail closed."""
        with pytest.raises(ValidationError):
            PipelineConfig(config_version="3.1")

    def test_config_version_separated_from_db_schema_version(self) -> None:
        """config_version (project.yaml) must NOT be confused with DB SCHEMA_VERSION.

        Regression guard: the DB schema version lives in
        agentkit.state_backend.config and is a separate versioning area.
        """
        from agentkit.state_backend import config as state_cfg

        # DB schema version is a SemVer like "3.20.0"; config version is "3.0"
        assert state_cfg.SCHEMA_VERSION != SUPPORTED_CONFIG_VERSION, (
            "DB SCHEMA_VERSION and config SUPPORTED_CONFIG_VERSION must be "
            "independent values (FK-03 §3.3.4 — two separate versioning areas)"
        )
        # Verify config BC has its own constant
        assert SUPPORTED_CONFIG_VERSION == "3.0"

    def test_loader_returns_config_error_for_wrong_version(
        self, tmp_path: Path
    ) -> None:
        """AC1b: load_project_config surfaces wrong version as ConfigError (not bare ValueError)."""
        _write_yaml_config(
            tmp_path,
            {
                "project_key": "p",
                "project_name": "P",
                "repositories": [],
                "story_types": ["concept"],
                "pipeline": {"config_version": "99.0", "features": {"multi_llm": False}},
            },
        )
        with pytest.raises(ConfigError) as exc_info:
            load_project_config(tmp_path)
        # ConfigError wraps the ValueError cause
        assert "config_path" in exc_info.value.detail
        cause = exc_info.value.__cause__
        assert cause is not None

    def test_loader_exposes_config_version_to_caller(self, tmp_path: Path) -> None:
        """AC7: loader exposes pipeline.config_version (AG3-089 migration anchor)."""
        _write_yaml_config(
            tmp_path,
            {
                "project_key": "p",
                "project_name": "P",
                "repositories": [],
                "story_types": ["concept"],
                "pipeline": {"config_version": "3.0", "features": {"multi_llm": False}},
            },
        )
        cfg = load_project_config(tmp_path)
        assert cfg.pipeline.config_version == SUPPORTED_CONFIG_VERSION

    def test_loader_missing_config_version_in_pipeline_stanza_fails_closed(
        self, tmp_path: Path
    ) -> None:
        """Loader returns ConfigError when pipeline stanza is present but config_version absent.

        AC1b negative path: no silent default when config_version is omitted from
        an explicit pipeline stanza (FK-03 §3.2.1, fail-closed).
        """
        _write_yaml_config(
            tmp_path,
            {
                "project_key": "p",
                "project_name": "P",
                "repositories": [],
                "story_types": ["concept"],
                "pipeline": {},  # stanza present, config_version key absent
            },
        )
        with pytest.raises(ConfigError) as exc_info:
            load_project_config(tmp_path)
        assert "config_path" in exc_info.value.detail

    def test_project_config_has_no_own_config_version_field(self) -> None:
        """ProjectConfig must not carry a second config_version field (SSOT)."""
        assert "config_version" not in ProjectConfig.model_fields


# ===========================================================================
# AC2 — FeaturesConfig six flags + e2e_assertions requires db
# ===========================================================================


class TestFeaturesConfig:
    """AC2: Features carries six flags + cross-field e2e_assertions requires db."""

    def test_default_flags(self) -> None:
        """Features defaults: are/multi_repo/vectordb/db/e2e_assertions=False,
        multi_llm=True (FK-01 §1.3 P5 / FK-03 §3.1 mandate), telemetry=True."""
        f = Features()
        assert f.are is False
        assert f.multi_repo is False
        assert f.vectordb is False
        assert f.multi_llm is True  # FK-01 §1.3 P5 / FK-03 §3.1: default True
        assert f.telemetry is True
        assert f.db is False
        assert f.e2e_assertions is False

    def test_all_six_flags_settable(self) -> None:
        """All six AG3-070 flags can be set explicitly."""
        f = Features(
            multi_repo=True,
            vectordb=True,
            multi_llm=False,
            telemetry=False,
            db=True,
            e2e_assertions=True,
        )
        assert f.multi_repo is True
        assert f.vectordb is True
        assert f.multi_llm is False
        assert f.telemetry is False
        assert f.db is True
        assert f.e2e_assertions is True

    def test_e2e_assertions_without_db_raises(self) -> None:
        """AC2: e2e_assertions=True without db=True must fail closed (FK-03 §3.2.1)."""
        with pytest.raises(ValidationError, match="requires features.db=True"):
            Features(e2e_assertions=True, db=False)

    def test_e2e_assertions_with_db_ok(self) -> None:
        """e2e_assertions=True with db=True is valid."""
        f = Features(e2e_assertions=True, db=True)
        assert f.e2e_assertions is True
        assert f.db is True

    def test_e2e_assertions_false_db_false_ok(self) -> None:
        """Default combination (both False) is always valid."""
        f = Features(e2e_assertions=False, db=False)
        assert f.e2e_assertions is False

    def test_features_is_frozen(self) -> None:
        """Features is immutable (frozen=True)."""
        f = Features()
        with pytest.raises(ValidationError):
            f.multi_repo = True  # type: ignore[misc]


# ===========================================================================
# AC3 — multi_llm + llm_roles + required roles
# ===========================================================================


class TestMultiLlmAndLlmRoles:
    """AC3: multi_llm=True requires llm_roles with the mandatory role set."""

    def test_required_llm_roles_constant(self) -> None:
        """REQUIRED_LLM_ROLES contains exactly the five mandatory roles (FK-03 §3.2.1)."""
        expected = frozenset(
            {
                "qa_review",
                "semantic_review",
                "adversarial_sparring",
                "doc_fidelity",
                "governance_adjudication",
            }
        )
        assert expected == REQUIRED_LLM_ROLES

    def test_multi_llm_true_without_llm_roles_raises(self) -> None:
        """multi_llm=True without llm_roles must fail closed (AC3 negative path)."""
        with pytest.raises(ValidationError, match="multi_llm=True requires a 'llm_roles'"):
            PipelineConfig(
                config_version=SUPPORTED_CONFIG_VERSION,
                features=Features(multi_llm=True),
                llm_roles=None,
            )

    def test_multi_llm_false_without_llm_roles_ok(self) -> None:
        """multi_llm=False without llm_roles is valid (single-LLM path)."""
        cfg = PipelineConfig(
            config_version=SUPPORTED_CONFIG_VERSION, features=Features(multi_llm=False)
        )
        assert cfg.llm_roles is None

    def test_multi_llm_true_with_all_required_roles_ok(self) -> None:
        """multi_llm=True with all five required roles is valid."""
        roles = LlmRolesConfig(
            qa_review="chatgpt",
            semantic_review="gemini",
            adversarial_sparring="grok",
            doc_fidelity="gemini",
            governance_adjudication="gemini",
        )
        cfg = PipelineConfig(
            config_version=SUPPORTED_CONFIG_VERSION,
            features=Features(multi_llm=True),
            llm_roles=roles,
        )
        assert cfg.llm_roles is not None
        assert cfg.llm_roles.qa_review == "chatgpt"

    def test_llm_roles_config_fields(self) -> None:
        """LlmRolesConfig carries all required + optional fields."""
        roles = LlmRolesConfig(
            worker="claude",
            qa_review="chatgpt",
            semantic_review="gemini",
            adversarial_sparring="grok",
            doc_fidelity="gemini",
            governance_adjudication="gemini",
            story_creation_review="chatgpt",
        )
        assert roles.worker == "claude"
        assert roles.qa_review == "chatgpt"
        assert roles.story_creation_review == "chatgpt"

    def test_llm_roles_missing_required_role_raises(self) -> None:
        """LlmRolesConfig with missing required field raises ValidationError."""
        with pytest.raises(ValidationError):
            LlmRolesConfig(  # type: ignore[call-arg]
                qa_review="chatgpt",
                # semantic_review missing
                adversarial_sparring="grok",
                doc_fidelity="gemini",
                governance_adjudication="gemini",
            )

    def test_single_roles_model_no_parallel_structure(self) -> None:
        """There is exactly ONE LLM-role-to-provider model: LlmRolesConfig.

        ReviewConfig.required_roles serves a different purpose (reviewer
        coverage enforcement for the ReviewGuard) and is NOT a parallel
        duplicate of LlmRolesConfig (AC3 SSOT rule).
        """
        from agentkit.config.models import ReviewConfig

        # ReviewConfig is for reviewer COVERAGE (which reviewers must have
        # reviewed) — not for provider assignment
        rc = ReviewConfig(required_roles=["qa_review", "semantic_review"])
        assert rc.required_roles == ["qa_review", "semantic_review"]

        # LlmRolesConfig is for provider ASSIGNMENT
        roles = LlmRolesConfig(
            qa_review="chatgpt",
            semantic_review="gemini",
            adversarial_sparring="grok",
            doc_fidelity="gemini",
            governance_adjudication="gemini",
        )
        assert roles.qa_review == "chatgpt"

        # Confirm these are distinct models serving distinct purposes
        assert type(rc) is not type(roles)


# ===========================================================================
# AC4 — five stanzas with FK-03 defaults
# ===========================================================================


class TestOrchestratorGuardConfig:
    """AC4: orchestrator_guard stanza with FK-03 defaults."""

    def test_defaults(self) -> None:
        """OrchestratorGuardConfig defaults are empty lists (FK-03 §3.1)."""
        cfg = OrchestratorGuardConfig()
        assert cfg.blocked_paths == []
        assert cfg.blocked_extensions == []
        assert cfg.blocked_files == []

    def test_custom_values(self) -> None:
        """OrchestratorGuardConfig accepts custom blocked paths/extensions/files."""
        cfg = OrchestratorGuardConfig(
            blocked_paths=["/src/", "/lib/"],
            blocked_extensions=[".py", ".ts"],
            blocked_files=["pyproject.toml"],
        )
        assert cfg.blocked_paths == ["/src/", "/lib/"]
        assert cfg.blocked_extensions == [".py", ".ts"]
        assert cfg.blocked_files == ["pyproject.toml"]

    def test_is_frozen(self) -> None:
        """OrchestratorGuardConfig is frozen (immutable)."""
        cfg = OrchestratorGuardConfig()
        with pytest.raises(ValidationError):
            cfg.blocked_paths = ["/new/"]  # type: ignore[misc]

    def test_rejects_extra_fields(self) -> None:
        """OrchestratorGuardConfig rejects unknown fields (extra=forbid)."""
        with pytest.raises(ValidationError):
            OrchestratorGuardConfig(unknown="oops")  # type: ignore[call-arg]

    def test_pipeline_config_has_orchestrator_guard(self) -> None:
        """PipelineConfig carries orchestrator_guard stanza."""
        cfg = PipelineConfig(
            config_version=SUPPORTED_CONFIG_VERSION, features=Features(multi_llm=False)
        )
        assert isinstance(cfg.orchestrator_guard, OrchestratorGuardConfig)
        assert cfg.orchestrator_guard.blocked_paths == []


class TestPolicyConfig:
    """AC4: policy stanza with FK-03 defaults."""

    def test_defaults(self) -> None:
        """Top-level PolicyConfig defaults to no stage overrides."""
        cfg = PolicyConfig()
        assert cfg.stage_overrides == {}

    def test_stage_override_config(self) -> None:
        """StageOverrideConfig allows overriding blocking per stage."""
        override = StageOverrideConfig(blocking=False)
        assert override.blocking is False

    def test_stage_override_requires_blocking(self) -> None:
        """StageOverride requires an explicit blocking value."""
        with pytest.raises(ValidationError):
            StageOverride()

    def test_policy_with_stage_overrides(self) -> None:
        """PolicyConfig accepts stage_overrides dict."""
        cfg = PolicyConfig(
            stage_overrides={"adversarial": StageOverrideConfig(blocking=False)},
        )
        assert cfg.stage_overrides["adversarial"].blocking is False

    def test_pipeline_config_has_policy(self) -> None:
        """PipelineConfig carries threshold policy stanza with correct defaults."""
        cfg = PipelineConfig(
            config_version=SUPPORTED_CONFIG_VERSION, features=Features(multi_llm=False)
        )
        assert isinstance(cfg.policy, PipelinePolicyConfig)
        assert cfg.policy.major_threshold == 3


class TestVectorDbConfig:
    """AC4: vectordb stanza with FK-03 defaults."""

    def test_defaults(self) -> None:
        """VectorDbConfig defaults: similarity_threshold=0.7, max_llm_candidates=5."""
        cfg = VectorDbConfig()
        assert cfg.similarity_threshold == 0.7
        assert cfg.max_llm_candidates == 5
        assert cfg.host is None
        assert cfg.port is None

    def test_custom_values(self) -> None:
        """VectorDbConfig accepts custom similarity threshold and candidates."""
        cfg = VectorDbConfig(
            similarity_threshold=0.85,
            max_llm_candidates=10,
            host="localhost",
            port=8080,
        )
        assert cfg.similarity_threshold == 0.85
        assert cfg.max_llm_candidates == 10
        assert cfg.host == "localhost"
        assert cfg.port == 8080

    def test_is_frozen(self) -> None:
        """VectorDbConfig is frozen."""
        cfg = VectorDbConfig()
        with pytest.raises(ValidationError):
            cfg.similarity_threshold = 0.5  # type: ignore[misc]

    def test_pipeline_config_vectordb_defaults_none(self) -> None:
        """PipelineConfig.vectordb defaults to None (not required unless vectordb feature on)."""
        cfg = PipelineConfig(
            config_version=SUPPORTED_CONFIG_VERSION, features=Features(multi_llm=False)
        )
        assert cfg.vectordb is None


class TestTelemetryConfig:
    """AC4: telemetry stanza with FK-03 defaults."""

    def test_defaults(self) -> None:
        """TelemetryConfig defaults: web_call_limit=200, web_call_warning=180 (FK-08-019)."""
        cfg = TelemetryConfig()
        assert cfg.web_call_limit == 200
        assert cfg.web_call_warning == 180

    def test_warning_below_limit_ok(self) -> None:
        """web_call_warning < web_call_limit is valid."""
        cfg = TelemetryConfig(web_call_limit=300, web_call_warning=250)
        assert cfg.web_call_warning == 250

    def test_warning_equal_to_limit_raises(self) -> None:
        """web_call_warning >= web_call_limit must fail closed."""
        with pytest.raises(ValidationError, match="web_call_warning.*must be.*less than"):
            TelemetryConfig(web_call_limit=200, web_call_warning=200)

    def test_warning_above_limit_raises(self) -> None:
        """web_call_warning > web_call_limit must fail closed."""
        with pytest.raises(ValidationError, match="web_call_warning.*must be.*less than"):
            TelemetryConfig(web_call_limit=200, web_call_warning=201)

    def test_pipeline_config_has_telemetry(self) -> None:
        """PipelineConfig carries telemetry stanza with correct defaults."""
        cfg = PipelineConfig(
            config_version=SUPPORTED_CONFIG_VERSION, features=Features(multi_llm=False)
        )
        assert isinstance(cfg.telemetry, TelemetryConfig)
        assert cfg.telemetry.web_call_limit == 200
        assert cfg.telemetry.web_call_warning == 180


class TestGovernanceConfig:
    """AC4: governance stanza with FK-03 defaults."""

    def test_defaults(self) -> None:
        """GovernanceConfig defaults: risk_threshold=30, window_size=50, cooldown_s=300."""
        cfg = GovernanceConfig()
        assert cfg.risk_threshold == 30
        assert cfg.window_size == 50
        assert cfg.cooldown_s == 300

    def test_custom_values(self) -> None:
        """GovernanceConfig accepts custom values."""
        cfg = GovernanceConfig(risk_threshold=50, window_size=100, cooldown_s=600)
        assert cfg.risk_threshold == 50
        assert cfg.window_size == 100
        assert cfg.cooldown_s == 600

    def test_is_frozen(self) -> None:
        """GovernanceConfig is frozen."""
        cfg = GovernanceConfig()
        with pytest.raises(ValidationError):
            cfg.risk_threshold = 99  # type: ignore[misc]

    def test_rejects_extra_fields(self) -> None:
        """GovernanceConfig rejects unknown fields."""
        with pytest.raises(ValidationError):
            GovernanceConfig(unknown="oops")  # type: ignore[call-arg]

    def test_pipeline_config_has_governance(self) -> None:
        """PipelineConfig carries governance stanza with correct defaults."""
        cfg = PipelineConfig(
            config_version=SUPPORTED_CONFIG_VERSION, features=Features(multi_llm=False)
        )
        assert isinstance(cfg.governance, GovernanceConfig)
        assert cfg.governance.risk_threshold == 30
        assert cfg.governance.window_size == 50
        assert cfg.governance.cooldown_s == 300


# ===========================================================================
# AC4a — sonarqube.accept_frequency_fc_threshold
# ===========================================================================


class TestAcceptFrequencyFcThreshold:
    """AC4a: SonarQubeConfig.accept_frequency_fc_threshold field (CP1, FK-03 §3.1)."""

    def test_default_is_0_25(self) -> None:
        """Default accept_frequency_fc_threshold must be 0.25 (FK-03 §3.1)."""
        # Use available=False to avoid the endpoint requirement
        cfg = SonarQubeConfig(available=False, enabled=False)
        assert cfg.accept_frequency_fc_threshold == 0.25

    def test_accepts_0_0(self) -> None:
        """Boundary value 0.0 is valid."""
        cfg = SonarQubeConfig(
            available=False,
            enabled=False,
            accept_frequency_fc_threshold=0.0,
        )
        assert cfg.accept_frequency_fc_threshold == 0.0

    def test_accepts_1_0(self) -> None:
        """Boundary value 1.0 is valid."""
        cfg = SonarQubeConfig(
            available=False,
            enabled=False,
            accept_frequency_fc_threshold=1.0,
        )
        assert cfg.accept_frequency_fc_threshold == 1.0

    def test_accepts_midpoint(self) -> None:
        """Midpoint 0.5 is valid."""
        cfg = SonarQubeConfig(
            available=False,
            enabled=False,
            accept_frequency_fc_threshold=0.5,
        )
        assert cfg.accept_frequency_fc_threshold == 0.5

    def test_below_zero_raises(self) -> None:
        """accept_frequency_fc_threshold < 0 must fail closed (AC4a range negative test)."""
        with pytest.raises(ValidationError, match="must be in \\[0.0, 1.0\\]"):
            SonarQubeConfig(
                available=False,
                enabled=False,
                accept_frequency_fc_threshold=-0.01,
            )

    def test_above_one_raises(self) -> None:
        """accept_frequency_fc_threshold > 1 must fail closed (AC4a range negative test)."""
        with pytest.raises(ValidationError, match="must be in \\[0.0, 1.0\\]"):
            SonarQubeConfig(
                available=False,
                enabled=False,
                accept_frequency_fc_threshold=1.01,
            )

    def test_no_second_sonarqube_stanza(self) -> None:
        """There is exactly ONE sonarqube stanza owner: PipelineConfig.sonarqube (SSOT).

        AC4a / FIX-THE-MODEL: extending the existing SonarQubeConfig owner,
        not creating a parallel stanza.
        """
        assert "sonarqube" in PipelineConfig.model_fields
        field_info = PipelineConfig.model_fields["sonarqube"]
        # The field type annotation includes SonarQubeConfig
        annotation = str(field_info.annotation)
        assert "SonarQubeConfig" in annotation

    def test_threshold_field_exists_on_sonarqubeconfig(self) -> None:
        """SonarQubeConfig.accept_frequency_fc_threshold field is declared."""
        assert "accept_frequency_fc_threshold" in SonarQubeConfig.model_fields


# ===========================================================================
# AC5/6 — config_version versioning cut + SUPPORTED_CONFIG_VERSION constant
# ===========================================================================


class TestConfigVersionVersioningCut:
    """AC5/6: config_version is owned solely by PipelineConfig; ProjectConfig
    has no second version field."""

    def test_supported_config_version_constant(self) -> None:
        """SUPPORTED_CONFIG_VERSION is '3.0' and exported from the config package."""
        assert SUPPORTED_CONFIG_VERSION == "3.0"

    def test_pipeline_config_is_the_config_version_owner(self) -> None:
        """PipelineConfig carries config_version (FK-03 §3.2.1 Config-BC owner)."""
        assert "config_version" in PipelineConfig.model_fields

    def test_project_config_reaches_version_via_pipeline(self) -> None:
        """ProjectConfig.pipeline.config_version is the path to the version."""
        cfg = _concept_project()
        assert cfg.pipeline.config_version == SUPPORTED_CONFIG_VERSION

    def test_pipeline_config_config_version_not_in_project_config(self) -> None:
        """ProjectConfig has no direct config_version field (single owner, SSOT)."""
        assert "config_version" not in ProjectConfig.model_fields

    def test_artifact_schema_version_is_out_of_cut(self) -> None:
        """Artefact-schema_version owners are in their own BCs, not config (FK-03 §3.3.4)."""
        from agentkit.artifacts import ENVELOPE_SCHEMA_VERSION
        from agentkit.artifacts.envelope import ArtifactEnvelope

        # ArtifactEnvelope.schema_version is the artefact-BC owner
        assert "schema_version" in ArtifactEnvelope.model_fields
        assert ENVELOPE_SCHEMA_VERSION == "3.0"

        # The config BC has config_version; these are independent (FK-03 §3.3.4)
        assert "config_version" not in ArtifactEnvelope.model_fields


# ===========================================================================
# ERROR 4 — PipelineConfig must reject unknown keys (extra=forbid)
# ===========================================================================


class TestPipelineConfigRejectsUnknownFields:
    """AC: PipelineConfig fails closed on unknown keys (FK-03 §3, extra=forbid)."""

    def test_model_rejects_unknown_pipeline_key(self) -> None:
        """PipelineConfig with an unknown field raises ValidationError (model level)."""
        with pytest.raises(ValidationError):
            PipelineConfig(  # type: ignore[call-arg]
                config_version=SUPPORTED_CONFIG_VERSION,
                features=Features(multi_llm=False),
                unknown_pipeline_key="oops",
            )

    def test_loader_rejects_unknown_pipeline_key_as_config_error(
        self, tmp_path: Path
    ) -> None:
        """load_project_config wraps unknown pipeline key as ConfigError (FK-03 §3)."""
        _write_yaml_config(
            tmp_path,
            {
                "project_key": "p",
                "project_name": "P",
                "repositories": [],
                "story_types": ["concept"],
                "pipeline": {
                    "config_version": "3.0",
                    "features": {"multi_llm": False},
                    "unknown_stanza": "forbidden",
                },
            },
        )
        with pytest.raises(ConfigError) as exc_info:
            load_project_config(tmp_path)
        assert "config_path" in exc_info.value.detail


# ===========================================================================
# Loader integration — YAML round-trip with new stanzas
# ===========================================================================


class TestLoaderWithNewStanzas:
    """Integration: load_project_config handles the new AG3-070 stanzas."""

    def test_load_with_vectordb_stanza(self, tmp_path: Path) -> None:
        """Loader correctly parses vectordb stanza."""
        _write_yaml_config(
            tmp_path,
            {
                "project_key": "p",
                "project_name": "P",
                "repositories": [],
                "story_types": ["concept"],
                "pipeline": {
                    "config_version": "3.0",
                    "features": {"multi_llm": False},
                    "vectordb": {
                        "similarity_threshold": 0.8,
                        "max_llm_candidates": 3,
                    },
                },
            },
        )
        cfg = load_project_config(tmp_path)
        assert cfg.pipeline.vectordb is not None
        assert cfg.pipeline.vectordb.similarity_threshold == 0.8
        assert cfg.pipeline.vectordb.max_llm_candidates == 3

    def test_load_with_governance_stanza(self, tmp_path: Path) -> None:
        """Loader correctly parses governance stanza."""
        _write_yaml_config(
            tmp_path,
            {
                "project_key": "p",
                "project_name": "P",
                "repositories": [],
                "story_types": ["concept"],
                "pipeline": {
                    "config_version": "3.0",
                    "features": {"multi_llm": False},
                    "governance": {
                        "risk_threshold": 50,
                        "window_size": 100,
                        "cooldown_s": 600,
                    },
                },
            },
        )
        cfg = load_project_config(tmp_path)
        assert cfg.pipeline.governance.risk_threshold == 50
        assert cfg.pipeline.governance.window_size == 100
        assert cfg.pipeline.governance.cooldown_s == 600

    def test_load_with_telemetry_stanza(self, tmp_path: Path) -> None:
        """Loader correctly parses telemetry stanza."""
        _write_yaml_config(
            tmp_path,
            {
                "project_key": "p",
                "project_name": "P",
                "repositories": [],
                "story_types": ["concept"],
                "pipeline": {
                    "config_version": "3.0",
                    "features": {"multi_llm": False},
                    "telemetry": {"web_call_limit": 300, "web_call_warning": 250},
                },
            },
        )
        cfg = load_project_config(tmp_path)
        assert cfg.pipeline.telemetry.web_call_limit == 300
        assert cfg.pipeline.telemetry.web_call_warning == 250

    def test_load_with_policy_stanza(self, tmp_path: Path) -> None:
        """Loader correctly parses pipeline threshold and top-level stage policy."""
        _write_yaml_config(
            tmp_path,
            {
                "project_key": "p",
                "project_name": "P",
                "repositories": [],
                "story_types": ["concept"],
                "pipeline": {
                    "config_version": "3.0",
                    "features": {"multi_llm": False},
                    "policy": {
                        "major_threshold": 5,
                    },
                },
                "policy": {
                    "stage_overrides": {
                        "adversarial": {"blocking": False},
                    },
                },
            },
        )
        cfg = load_project_config(tmp_path)
        assert cfg.pipeline.policy.major_threshold == 5
        assert cfg.policy.stage_overrides["adversarial"].blocking is False

    def test_load_with_orchestrator_guard_stanza(self, tmp_path: Path) -> None:
        """Loader correctly parses orchestrator_guard stanza."""
        _write_yaml_config(
            tmp_path,
            {
                "project_key": "p",
                "project_name": "P",
                "repositories": [],
                "story_types": ["concept"],
                "pipeline": {
                    "config_version": "3.0",
                    "features": {"multi_llm": False},
                    "orchestrator_guard": {
                        "blocked_paths": ["/src/"],
                        "blocked_extensions": [".py"],
                        "blocked_files": ["pyproject.toml"],
                    },
                },
            },
        )
        cfg = load_project_config(tmp_path)
        assert cfg.pipeline.orchestrator_guard.blocked_paths == ["/src/"]
        assert cfg.pipeline.orchestrator_guard.blocked_extensions == [".py"]
        assert cfg.pipeline.orchestrator_guard.blocked_files == ["pyproject.toml"]

    def test_load_with_llm_roles_and_multi_llm(self, tmp_path: Path) -> None:
        """Loader correctly parses llm_roles stanza with multi_llm=True."""
        _write_yaml_config(
            tmp_path,
            {
                "project_key": "p",
                "project_name": "P",
                "repositories": [],
                "story_types": ["concept"],
                "pipeline": {
                    "config_version": "3.0",
                    "features": {"multi_llm": True},
                    "llm_roles": {
                        "worker": "claude",
                        "qa_review": "chatgpt",
                        "semantic_review": "gemini",
                        "adversarial_sparring": "grok",
                        "doc_fidelity": "gemini",
                        "governance_adjudication": "gemini",
                    },
                },
            },
        )
        cfg = load_project_config(tmp_path)
        assert cfg.pipeline.llm_roles is not None
        assert cfg.pipeline.llm_roles.qa_review == "chatgpt"
        assert cfg.pipeline.llm_roles.worker == "claude"

    def test_load_with_sonarqube_accept_frequency(self, tmp_path: Path) -> None:
        """Loader correctly parses sonarqube.accept_frequency_fc_threshold."""
        _write_yaml_config(
            tmp_path,
            {
                "project_key": "p",
                "project_name": "P",
                "repositories": [],
                "story_types": ["concept"],
                "pipeline": {
                    "config_version": "3.0",
                    "features": {"multi_llm": False},
                    "sonarqube": {
                        "available": False,
                        "enabled": False,
                        "accept_frequency_fc_threshold": 0.3,
                    },
                },
            },
        )
        cfg = load_project_config(tmp_path)
        assert cfg.pipeline.sonarqube is not None
        assert cfg.pipeline.sonarqube.accept_frequency_fc_threshold == 0.3

    def test_load_invalid_config_version_raises_config_error(
        self, tmp_path: Path
    ) -> None:
        """An invalid config_version in YAML raises ConfigError (not bare ValueError)."""
        _write_yaml_config(
            tmp_path,
            {
                "project_key": "p",
                "project_name": "P",
                "repositories": [],
                "story_types": ["concept"],
                "pipeline": {"config_version": "bad-version", "features": {"multi_llm": False}},
            },
        )
        with pytest.raises(ConfigError):
            load_project_config(tmp_path)

    def test_load_pipeline_stanza_without_config_version_fails_closed(
        self, tmp_path: Path
    ) -> None:
        """A ``pipeline:`` stanza present but missing ``config_version`` must fail closed.

        AC1 / FK-03 §3.2.1 fail-closed: an explicit pipeline stanza with no
        config_version is a hard error — no silent default (ERROR 2 fix).
        """
        _write_yaml_config(
            tmp_path,
            {
                "project_key": "p",
                "project_name": "P",
                "repositories": [],
                "story_types": ["concept"],
                # pipeline stanza present but config_version omitted:
                "pipeline": {
                    "policy": {"major_threshold": 3},
                },
            },
        )
        with pytest.raises(ConfigError):
            load_project_config(tmp_path)

    def test_load_pipeline_key_absent_fails_closed(
        self, tmp_path: Path
    ) -> None:
        """When the ``pipeline:`` key is absent entirely the loader must fail closed.

        AC1 / FK-03 §3.2.1 fail-closed: ``pipeline`` is a required field on
        ``ProjectConfig`` — omitting it entirely is a hard error. No silent
        default, no fabricated config_version (FIX-B, residual AG3-070 fix).
        """
        _write_yaml_config(
            tmp_path,
            {
                "project_key": "p",
                "project_name": "P",
                "repositories": [],
                "story_types": ["concept"],
                # pipeline key intentionally absent — must fail closed
            },
        )
        with pytest.raises(ConfigError) as exc_info:
            load_project_config(tmp_path)
        # ConfigError wraps the Pydantic ValidationError about missing pipeline
        assert "config_path" in exc_info.value.detail
