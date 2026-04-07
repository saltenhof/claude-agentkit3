"""Standard paths for AgentKit's target project layout.

Provides path constants and helper functions for resolving well-known
locations within a target project that has AgentKit installed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

# Root directories
AGENTKIT_DIR: str = ".agentkit"
"""Top-level AgentKit directory in the target project."""

CONFIG_DIR: str = f"{AGENTKIT_DIR}/config"
"""Configuration directory inside ``.agentkit/``."""

PROMPTS_DIR: str = f"{AGENTKIT_DIR}/prompts"
"""Prompts directory inside ``.agentkit/``."""

HOOKS_DIR: str = f"{AGENTKIT_DIR}/hooks"
"""Hooks directory inside ``.agentkit/``."""

STORIES_DIR: str = "stories"
"""Top-level stories directory in the target project."""

# Config files
PROJECT_CONFIG_FILE: str = "project.yaml"
"""Name of the main project configuration file."""

PIPELINE_CONFIG_FILE: str = "story-pipeline.yaml"
"""Name of the pipeline configuration file."""

# Story directories
PHASE_RUNS_DIR: str = "phase-runs"
"""Subdirectory within a story directory for phase run artifacts."""

CONTEXT_FILE: str = "context.json"
"""Name of the story context file."""

PHASE_STATE_FILE: str = "phase-state.json"
"""Name of the phase state file."""


def agentkit_dir(project_root: Path) -> Path:
    """Return the ``.agentkit/`` directory path for a project.

    Args:
        project_root: Root directory of the target project.

    Returns:
        Absolute path to the ``.agentkit/`` directory.
    """
    return project_root / AGENTKIT_DIR


def config_dir(project_root: Path) -> Path:
    """Return the ``.agentkit/config/`` directory path for a project.

    Args:
        project_root: Root directory of the target project.

    Returns:
        Absolute path to the configuration directory.
    """
    return project_root / CONFIG_DIR


def project_config_path(project_root: Path) -> Path:
    """Return the path to ``project.yaml`` for a project.

    Args:
        project_root: Root directory of the target project.

    Returns:
        Absolute path to the ``project.yaml`` file.
    """
    return project_root / CONFIG_DIR / PROJECT_CONFIG_FILE


def stories_dir(project_root: Path) -> Path:
    """Return the ``stories/`` directory path for a project.

    Args:
        project_root: Root directory of the target project.

    Returns:
        Absolute path to the stories directory.
    """
    return project_root / STORIES_DIR


def story_dir(project_root: Path, story_id: str) -> Path:
    """Return the directory path for a specific story.

    Args:
        project_root: Root directory of the target project.
        story_id: Identifier of the story.

    Returns:
        Absolute path to the story's directory.
    """
    return project_root / STORIES_DIR / story_id
