"""Filesystem path helpers for FK-36 compaction-resilience artifacts."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

AGENT_PROMPTS_DIR = "_temp/agent-prompts"
QA_DIR = "_temp/qa"
STORY_MARKER_FILENAME = ".agentkit-story.json"


def qa_story_dir(project_root: Path, story_id: str) -> Path:
    """Return the canonical story-scoped QA temp directory."""
    return project_root / QA_DIR / story_id


def spawn_spec_path(project_root: Path, story_id: str, spawn_key: str) -> Path:
    """Return the canonical spawn-spec path."""
    return qa_story_dir(project_root, story_id) / f"spawn-spec--{spawn_key}.json"


def resume_capsule_path(project_root: Path, story_id: str, spawn_key: str) -> Path:
    """Return the canonical resume-capsule path."""
    return qa_story_dir(project_root, story_id) / f"resume-capsule--{spawn_key}.md"


def agent_prompts_dir(project_root: Path) -> Path:
    """Return the canonical per-agent runtime prompt directory."""
    return project_root / AGENT_PROMPTS_DIR


def manifest_path(project_root: Path, agent_id: str) -> Path:
    """Return the manifest path for a validated agent id."""
    return agent_prompts_dir(project_root) / f"{agent_id}.manifest.json"


def first_tool_path(project_root: Path, agent_id: str) -> Path:
    """Return the first-tool marker path for a validated agent id."""
    return agent_prompts_dir(project_root) / f"{agent_id}.first-tool"


def recovered_path(project_root: Path, agent_id: str) -> Path:
    """Return the legacy recovered marker path cleaned up by FK-36."""
    return agent_prompts_dir(project_root) / f"{agent_id}.recovered"


def active_path(project_root: Path, agent_id: str) -> Path:
    """Return the legacy active marker path cleaned up by FK-36."""
    return agent_prompts_dir(project_root) / f"{agent_id}.active"


__all__ = [
    "AGENT_PROMPTS_DIR",
    "QA_DIR",
    "STORY_MARKER_FILENAME",
    "active_path",
    "agent_prompts_dir",
    "first_tool_path",
    "manifest_path",
    "qa_story_dir",
    "recovered_path",
    "resume_capsule_path",
    "spawn_spec_path",
]
