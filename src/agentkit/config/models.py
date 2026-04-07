"""Pydantic v2 models for AgentKit project configuration.

These models represent the structure of a target project's
``project.yaml`` (located at ``.agentkit/config/project.yaml``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict

from agentkit.config.defaults import (
    DEFAULT_MAX_FEEDBACK_ROUNDS,
    DEFAULT_MAX_REMEDIATION_ROUNDS,
    DEFAULT_STORY_TYPES,
    DEFAULT_VERIFY_LAYERS,
)


class PipelineConfig(BaseModel):
    """Configuration for the 5-phase pipeline.

    Attributes:
        max_feedback_rounds: Maximum verify-feedback cycles before
            escalation.
        max_remediation_rounds: Maximum remediation attempts per
            feedback round.
        exploration_mode: Whether the optional Exploration phase
            (Phase 2) is enabled for implementation stories.
        verify_layers: Ordered list of QA layers to execute during
            the Verify phase.
    """

    model_config = ConfigDict(strict=True)

    max_feedback_rounds: int = DEFAULT_MAX_FEEDBACK_ROUNDS
    max_remediation_rounds: int = DEFAULT_MAX_REMEDIATION_ROUNDS
    exploration_mode: bool = True
    verify_layers: list[str] = list(DEFAULT_VERIFY_LAYERS)


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
        project_name: Display name of the target project.
        repositories: List of repositories managed by this project.
        pipeline: Pipeline behaviour configuration.
        story_types: Allowed story types for this project.
        github_owner: GitHub organisation or user owning the repo.
        github_repo: GitHub repository name.
    """

    model_config = ConfigDict(strict=True)

    project_name: str
    repositories: list[RepositoryConfig]
    pipeline: PipelineConfig = PipelineConfig()
    story_types: list[str] = list(DEFAULT_STORY_TYPES)
    github_owner: str | None = None
    github_repo: str | None = None
