"""Default values and constants for AgentKit configuration.

These constants define the canonical defaults used when configuration
values are not explicitly provided in a project's ``project.yaml``.
"""

from __future__ import annotations

DEFAULT_CONFIG_DIR: str = ".agentkit/config"
"""Relative path from project root to the AgentKit configuration directory."""

DEFAULT_CONFIG_FILE: str = "project.yaml"
"""Name of the main project configuration file."""

DEFAULT_STORY_TYPES: tuple[str, ...] = (
    "implementation",
    "bugfix",
    "concept",
    "research",
)
"""Supported story types in the 5-phase pipeline."""

DEFAULT_MAX_FEEDBACK_ROUNDS: int = 3
"""Maximum number of feedback rounds before escalation in the Verify phase."""

DEFAULT_MAX_REMEDIATION_ROUNDS: int = 2
"""Maximum number of remediation attempts per feedback round."""

DEFAULT_VERIFY_LAYERS: tuple[str, ...] = (
    "structural",
    "semantic",
    "adversarial",
    "policy",
)
"""The four QA layers executed during the Verify phase."""
