"""Shared configuration helpers for composition-root builders."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def _project_config_present(project_root: Path) -> bool:
    """Whether the project declares an AK3 config file (vs deliberate absence)."""
    from agentkit.backend.config.defaults import DEFAULT_CONFIG_DIR, DEFAULT_CONFIG_FILE

    return (project_root / DEFAULT_CONFIG_DIR / DEFAULT_CONFIG_FILE).is_file()
