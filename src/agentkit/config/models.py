"""Pydantic v2 models for AgentKit project configuration.

These models represent the structure of a target project's
``project.yaml`` (located at ``.agentkit/config/project.yaml``).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    field_validator,
    model_validator,
)

from agentkit.config.defaults import (
    DEFAULT_MAX_FEEDBACK_ROUNDS,
    DEFAULT_MAX_REMEDIATION_ROUNDS,
    DEFAULT_STORY_TYPES,
    DEFAULT_VERIFY_LAYERS,
)


class Features(BaseModel):
    """Optional feature flags for a target project.

    Attributes:
        are: Whether the Agent Requirements Engine (ARE) integration
            is enabled. When ``False`` (default), all
            ``RequirementsCoverage`` top-surface methods are no-ops
            that return ``SKIPPED`` results (FK-40 §40.2).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    are: bool = False


class AreConfig(BaseModel):
    """Configuration section for the Agent Requirements Engine (ARE).

    Required when ``pipeline.features.are`` is ``True`` (FK-03 §3.2.1).

    Attributes:
        mcp_server: MCP server endpoint for the ARE integration.
        rest_base_url: Optional REST base URL for ``AreClient`` (FK-40 §40.4).
        auth_token: Optional bearer token for ARE API authentication.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    mcp_server: str
    rest_base_url: str | None = None
    auth_token: str | None = None


_SEMVER_RE = re.compile(r"^\d+(\.\d+)*$")


def _validate_semver(value: str, *, field: str) -> str:
    """FK-03 §3: ``min_version`` strings must be parsable dotted SemVer."""
    if not _SEMVER_RE.fullmatch(value):
        msg = f"sonarqube.{field} must be a parsable SemVer string (FK-03 §3); got {value!r}"
        raise ValueError(msg)
    return value


class SonarQubeBranchPluginConfig(BaseModel):
    """Community Branch Plugin requirement (FK-03 §3, FK-33 §33.6.3).

    Attributes:
        min_version: Minimum Community Branch Plugin version (SemVer).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    min_version: str = "1.23.0"

    @field_validator("min_version")
    @classmethod
    def _check_min_version(cls, value: str) -> str:
        """FK-03 §3: plugin ``min_version`` must be parsable SemVer."""
        return _validate_semver(value, field="plugins.community_branch.min_version")


class SonarQubePluginsConfig(BaseModel):
    """SonarQube plugin requirements (FK-03 §3).

    Attributes:
        community_branch: Community Branch Plugin requirement.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    community_branch: SonarQubeBranchPluginConfig = SonarQubeBranchPluginConfig()


class SonarQubeQualityGateConfig(BaseModel):
    """Quality-gate / default-profile reference (FK-03 §3, FK-33 §33.6.3).

    Attributes:
        default_profile: Repo-relative path to the shipped default
            quality-gate profile artefact (SSOT under
            ``resources/target_project/``). Carries BOTH New-Code AND
            Overall-Code conditions (FK-33 §33.6.3 Overall-Code invariant).
        overrides_allowed: Whether the project owner may replace the
            default profile with its own rule set.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    default_profile: str = "resources/target_project/sonar/ak3-default-gate.json"
    overrides_allowed: bool = True


class SonarQubeConfig(BaseModel):
    """SonarQube-Green-Gate environment/profile requirement (FK-03 §3).

    Config-owner slice of the SonarQube-Green-Gate requirement; the gate
    semantics live in FK-33 §33.6.3 (capability ``sonarqube_gate``).
    Checked as an installer precondition (FK-50 CP 10d) and carried as a
    mandatory runtime dependency (FK-10 §10.2.2).

    The ``available``/``enabled`` split (FK-33 §33.6.5) is normative:

    * ``available`` -- whether SonarQube is declared present for this
      project/host. The CORE DEFAULT is ``true`` (FK-03 §3: the green-gate
      is the default for code-producing projects; ``available == false`` is
      only ever a CONSCIOUS, EXPLICIT opt-out). This makes a present-but-
      empty ``sonarqube: {}`` stanza fail closed (it defaults
      ``available/enabled == true`` and the missing endpoint then raises)
      rather than becoming a SILENT opt-out. ``available == false`` makes
      the gate not applicable (a deliberate absence, not a failure) and is
      permitted even for code-producing projects.
    * ``enabled`` -- whether the gate is switched on. Default ``true`` (a
      declared-present gate is on by default). For a code-producing project
      ``available == true AND enabled == false`` is illegal (cross-field
      rule below); pure concept/research projects may set both ``false``.

    Attributes:
        available: SonarQube declared present (FK-33 §33.6.5 applicability).
            Core default ``true`` (FK-03 §3): the gate is on by default for
            code-producing projects; ``false`` is an explicit opt-out only.
        enabled: Gate switched on (FK-03 §3 cross-field rule). Core default
            ``true``.
        base_url: SonarQube server endpoint (default port 9901, FK-10
            §10.7.2). Required when ``available and enabled``.
        token_env: Name of the ENV/secret-store key holding the Sonar
            token (never an inline token, FK-33 §33.3.2). Required when
            ``available and enabled``.
        min_version: Minimum SonarQube Community Build version (SemVer).
        plugins: Plugin requirements (Community Branch Plugin).
        quality_gate: Quality-gate / default-profile reference.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    available: bool = True
    enabled: bool = True
    base_url: str | None = None
    token_env: str | None = None
    min_version: str = "26.4"
    plugins: SonarQubePluginsConfig = SonarQubePluginsConfig()
    quality_gate: SonarQubeQualityGateConfig = SonarQubeQualityGateConfig()

    @field_validator("min_version")
    @classmethod
    def _check_min_version(cls, value: str) -> str:
        """FK-03 §3: ``min_version`` must be parsable SemVer."""
        return _validate_semver(value, field="min_version")

    @model_validator(mode="after")
    def _validate_active_requires_endpoint(self) -> SonarQubeConfig:
        """FK-03 §3: ``available and enabled`` requires base_url + token_env.

        No silent default to localhost without auth (fail-closed).
        """
        if self.available and self.enabled:
            missing = [
                name
                for name, value in (("base_url", self.base_url), ("token_env", self.token_env))
                if not value
            ]
            if missing:
                msg = (
                    "sonarqube.available=true and sonarqube.enabled=true require "
                    f"{' and '.join(missing)} (FK-03 §3, fail-closed: no silent "
                    "localhost-without-auth default)"
                )
                raise ValueError(msg)
        return self


class PipelineConfig(BaseModel):
    """Configuration for the 4-phase pipeline.

    Attributes:
        max_feedback_rounds: Maximum QA feedback cycles before
            escalation.
        max_remediation_rounds: Maximum remediation attempts per
            feedback round.
        exploration_mode: Whether the optional Exploration phase
            (Phase 2) is enabled for implementation stories.
        verify_layers: Ordered list of QA layers to execute during
            the implementation QA-subflow.
        features: Optional feature flags (e.g. ARE integration).
        sonarqube: SonarQube-Green-Gate environment/profile requirement
            (FK-03 §3 / FK-33 §33.6). ``None`` only for non-code-producing
            projects; a code-producing project (``story_types`` include
            ``implementation``/``bugfix``) MUST declare the stanza explicitly
            — an omitted stanza is rejected at config-load (AG3-052 E6,
            FAIL-CLOSED, see ``ProjectConfig._validate_sonarqube_codeproducing``).
            The installer ALWAYS writes an EXPLICIT stanza for a code-producing
            project (FK-03 §3 example: ``available: true``). The explicit
            ``available: false`` opt-out stays legal. The existing cross-field
            rule (``available: true`` + ``enabled: false`` on a code-producing
            project) is unchanged.
    """

    model_config = ConfigDict(strict=True)

    max_feedback_rounds: int = DEFAULT_MAX_FEEDBACK_ROUNDS
    max_remediation_rounds: int = DEFAULT_MAX_REMEDIATION_ROUNDS
    exploration_mode: bool = True
    verify_layers: list[str] = list(DEFAULT_VERIFY_LAYERS)
    features: Features = Features()
    sonarqube: SonarQubeConfig | None = None


def _coerce_path(value: Any) -> Path:
    """Coerce string values to Path objects for YAML compatibility."""
    if isinstance(value, Path):
        return value
    if isinstance(value, str):
        return Path(value)
    msg = f"Expected str or Path, got {type(value).__name__}"
    raise TypeError(msg)


class RepositoryConfig(BaseModel):
    """A single repository in the target project.

    Attributes:
        name: Human-readable repository name.
        path: Filesystem path to the repository root.
        language: Primary programming language (e.g. ``"python"``).
        test_command: Shell command to run the test suite.
        build_command: Shell command to build the project.
    """

    model_config = ConfigDict(strict=True)

    name: str
    path: Annotated[Path, BeforeValidator(_coerce_path)]
    language: str | None = None
    test_command: str | None = None
    build_command: str | None = None


class ProjectConfig(BaseModel):
    """Root configuration for a target project using AgentKit.

    This is the top-level model parsed from
    ``.agentkit/config/project.yaml``.

    Attributes:
        project_key: Stable technical key of the target project.
        project_name: Display name of the target project.
        project_prefix: Story-ID prefix (FK-03 §3.2 / FK-43 §43.4.2 placeholder
            ``{{project_prefix}}``). Defaults to ``project_key.upper()`` when
            not provided.
        repositories: List of repositories managed by this project.
        pipeline: Pipeline behaviour configuration.
        story_types: Allowed story types for this project.
        github_owner: GitHub organisation or user owning the repo.
        github_repo: GitHub repository name.
    """

    model_config = ConfigDict(strict=True, extra="forbid")

    project_key: str
    project_name: str
    project_prefix: str | None = None
    repositories: list[RepositoryConfig]
    pipeline: PipelineConfig = PipelineConfig()
    story_types: list[str] = list(DEFAULT_STORY_TYPES)
    github_owner: str | None = None
    github_repo: str | None = None
    are: AreConfig | None = None

    @model_validator(mode="after")
    def _validate_are_section_when_enabled(self) -> ProjectConfig:
        """FK-03 §3.2.1: ``features.are=True`` requires an ``are`` section."""
        if self.pipeline.features.are and self.are is None:
            msg = (
                "pipeline.features.are=True requires an 'are' configuration "
                "section (FK-03 §3.2.1)"
            )
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _validate_sonarqube_codeproducing(self) -> ProjectConfig:
        """FK-03 §3: code-producing project must DECLARE the gate explicitly.

        A project whose ``story_types`` include ``implementation`` or
        ``bugfix`` is code-producing. Two fail-closed rules apply:

        1. **No silent disable by omission (AG3-052 E6, FAIL-CLOSED).** A
           code-producing project that omits the ``sonarqube`` stanza
           entirely (``self.pipeline.sonarqube is None``) is rejected. The
           green-gate is a mandatory runtime dependency (FK-10 §10.2.2) and
           the operator's intent must be EXPLICIT: either declare
           ``available: true`` (gate enforced) or ``available: false``
           (deliberate, declared opt-out — gate not applicable, FK-33
           §33.6.5). Disabling by leaving the stanza out is NOT the same as a
           conscious ``available: false`` decision and must not pass silently.

        2. **Cross-field rule (unchanged).** A declared-present but
           switched-off gate (``sonarqube.available == true`` and
           ``sonarqube.enabled == false``) is rejected: the Setup-Preflight
           (FK-22 §22.4c) and Closure gate (FK-29 §29.1a / FK-35 §35.2.4a)
           could not satisfy their precondition.

        Non-code-producing (concept/research-only) projects may omit the
        stanza or switch the gate off entirely.
        """
        codeproducing = bool(
            {"implementation", "bugfix"}.intersection(self.story_types)
        )
        sonar = self.pipeline.sonarqube
        if codeproducing and sonar is None:
            msg = (
                "A code-producing project (story_types include "
                "implementation/bugfix) must DECLARE the 'sonarqube' stanza "
                "explicitly in pipeline (FK-03 §3, FAIL-CLOSED, AG3-052 E6): "
                "the green-gate is a mandatory runtime dependency (FK-10 "
                "§10.2.2) and must not be disabled by omission. Declare "
                "sonarqube.available=true to enforce the gate, or "
                "sonarqube.available=false to opt out explicitly (gate not "
                "applicable, FK-33 §33.6.5)."
            )
            raise ValueError(msg)
        if codeproducing and sonar is not None and sonar.available and not sonar.enabled:
            msg = (
                "A code-producing project (story_types include "
                "implementation/bugfix) with sonarqube.available=true must not "
                "set sonarqube.enabled=false (FK-03 §3): the green-gate "
                "precondition cannot be satisfied. Set enabled=true, or declare "
                "sonarqube.available=false to opt out (gate not applicable)."
            )
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _default_project_prefix(self) -> ProjectConfig:
        """FK-03 §3.2 / FK-43 §43.4.2: derive ``project_prefix`` from ``project_key``
        when not explicitly set (story-id prefix convention)."""
        if self.project_prefix is None:
            # Pydantic v2 frozen models: rebuild via model_copy to set the default.
            object.__setattr__(self, "project_prefix", self.project_key.upper())
        return self
