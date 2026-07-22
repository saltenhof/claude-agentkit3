"""Configuration loading and project root discovery.

Provides functions to locate a project's ``.agentkit/`` directory and
load the ``project.yaml`` into validated Pydantic models.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agentkit.backend.config.defaults import DEFAULT_CONFIG_DIR, DEFAULT_CONFIG_FILE
from agentkit.backend.config.models import ProjectConfig
from agentkit.backend.config.strict_yaml import StrictYamlError, strict_load_yaml
from agentkit.backend.exceptions import ConfigError


def find_project_root(start_path: Path | None = None) -> Path:
    """Walk up from *start_path* looking for an ``.agentkit/`` directory.

    If *start_path* is ``None`` the current working directory is used.

    Args:
        start_path: Directory to start the upward search from.

    Returns:
        The first ancestor directory (inclusive) that contains an
        ``.agentkit/`` subdirectory.

    Raises:
        ConfigError: If no ``.agentkit/`` directory is found in any
            ancestor up to the filesystem root.
    """
    current = (start_path or Path.cwd()).resolve()

    while True:
        candidate = current / ".agentkit"
        if candidate.is_dir():
            return current
        parent = current.parent
        if parent == current:
            # Reached filesystem root without finding .agentkit/
            raise ConfigError(
                f"No .agentkit/ directory found in {start_path or Path.cwd()} "
                f"or any parent directory",
                detail={"start_path": str(start_path or Path.cwd())},
            )
        current = parent


def load_project_config(project_root: Path) -> ProjectConfig:
    """Load and validate ``ProjectConfig`` from a project directory.

    Reads ``project_root/.agentkit/config/project.yaml``, parses the
    YAML content, and validates it against the :class:`ProjectConfig`
    schema.

    Args:
        project_root: Root directory of the target project.  Must
            contain a ``.agentkit/config/project.yaml`` file.

    Returns:
        A validated :class:`ProjectConfig` instance.

    Raises:
        ConfigError: If the configuration file is missing, contains
            invalid YAML, or fails Pydantic validation.
    """
    config_path = project_root / DEFAULT_CONFIG_DIR / DEFAULT_CONFIG_FILE

    if not config_path.is_file():
        raise ConfigError(
            f"Configuration file not found: {config_path}",
            detail={"config_path": str(config_path)},
        )

    try:
        raw_text = config_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ConfigError(
            f"Configuration file is not valid UTF-8: {config_path}: {exc}",
            detail={
                "config_path": str(config_path),
                "error": str(exc),
                "error_code": "configuration_invalid",
                "reason": "configuration_invalid",
            },
        ) from exc
    except OSError as exc:
        raise ConfigError(
            f"Failed to read configuration file: {config_path}",
            detail={
                "config_path": str(config_path),
                "error": str(exc),
                "error_code": "configuration_invalid",
            },
        ) from exc

    try:
        raw_data: Any = strict_load_yaml(raw_text)
    except StrictYamlError as exc:
        raise ConfigError(
            f"Invalid YAML in configuration file: {config_path}: {exc}",
            detail={
                "config_path": str(config_path),
                "error": str(exc),
                "reason": exc.reason,
                "error_code": "configuration_invalid",
            },
        ) from exc
    except RecursionError as exc:
        raise ConfigError(
            f"YAML nesting exceeds decoder limits in {config_path}",
            detail={
                "config_path": str(config_path),
                "error": str(exc),
                "reason": "configuration_invalid",
                "error_code": "configuration_invalid",
            },
        ) from exc

    if not isinstance(raw_data, dict):
        raise ConfigError(
            f"Configuration file must contain a YAML mapping, "
            f"got {type(raw_data).__name__}: {config_path}",
            detail={
                "config_path": str(config_path),
                "type": type(raw_data).__name__,
                "error_code": "configuration_invalid",
            },
        )

    try:
        return ProjectConfig.model_validate(raw_data)
    except Exception as exc:
        raise ConfigError(
            f"Configuration validation failed for {config_path}: {exc}",
            detail={
                "config_path": str(config_path),
                "error": str(exc),
                "error_code": "configuration_invalid",
            },
        ) from exc
