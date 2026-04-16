"""Standard paths for AgentKit's target project layout."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

AGENTKIT_DIR: str = ".agentkit"
CONFIG_DIR: str = f"{AGENTKIT_DIR}/config"
PROMPTS_DIR: str = f"{AGENTKIT_DIR}/prompts"
HOOKS_DIR: str = f"{AGENTKIT_DIR}/hooks"
STORIES_DIR: str = "stories"
PROJECT_CONFIG_FILE: str = "project.yaml"
PIPELINE_CONFIG_FILE: str = "story-pipeline.yaml"
PHASE_RUNS_DIR: str = "phase-runs"
CONTEXT_FILE: str = "context.json"
PHASE_STATE_FILE: str = "phase-state.json"


def agentkit_dir(project_root: Path) -> Path:
    return project_root / AGENTKIT_DIR


def config_dir(project_root: Path) -> Path:
    return project_root / CONFIG_DIR


def project_config_path(project_root: Path) -> Path:
    return project_root / CONFIG_DIR / PROJECT_CONFIG_FILE


def stories_dir(project_root: Path) -> Path:
    return project_root / STORIES_DIR


def story_dir(project_root: Path, story_id: str) -> Path:
    return project_root / STORIES_DIR / story_id

__all__ = [
    "AGENTKIT_DIR",
    "CONFIG_DIR",
    "CONTEXT_FILE",
    "HOOKS_DIR",
    "PHASE_RUNS_DIR",
    "PHASE_STATE_FILE",
    "PIPELINE_CONFIG_FILE",
    "PROJECT_CONFIG_FILE",
    "PROMPTS_DIR",
    "STORIES_DIR",
    "agentkit_dir",
    "config_dir",
    "project_config_path",
    "stories_dir",
    "story_dir",
]
