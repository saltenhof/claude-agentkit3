"""Pydantic v2 models for AgentKit project configuration.

These models represent the structure of a target project's
``project.yaml`` (located at ``.agentkit/config/project.yaml``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, model_validator

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
    """

    model_config = ConfigDict(strict=True)

    max_feedback_rounds: int = DEFAULT_MAX_FEEDBACK_ROUNDS
    max_remediation_rounds: int = DEFAULT_MAX_REMEDIATION_ROUNDS
    exploration_mode: bool = True
    verify_layers: list[str] = list(DEFAULT_VERIFY_LAYERS)
    features: Features = Features()


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
    def _default_project_prefix(self) -> ProjectConfig:
        """FK-03 §3.2 / FK-43 §43.4.2: derive ``project_prefix`` from ``project_key``
        when not explicitly set (story-id prefix convention)."""
        if self.project_prefix is None:
            # Pydantic v2 frozen models: rebuild via model_copy to set the default.
            object.__setattr__(self, "project_prefix", self.project_key.upper())
        return self
