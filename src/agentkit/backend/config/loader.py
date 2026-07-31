"""Configuration loading and project root discovery.

Provides functions to locate a project's ``.agentkit/`` directory and
load the ``project.yaml`` into validated Pydantic models.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from pydantic import ValidationError
from yaml.constructor import ConstructorError

from agentkit.backend.config.defaults import DEFAULT_CONFIG_DIR, DEFAULT_CONFIG_FILE
from agentkit.backend.config.models import ProjectConfig
from agentkit.backend.exceptions import ConfigError

if TYPE_CHECKING:
    from yaml.nodes import MappingNode

_MAX_YAML_DEPTH = 64


class _UniqueKeySafeLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate mapping keys."""


def _construct_unique_mapping(
    loader: _UniqueKeySafeLoader,
    node: MappingNode,
    deep: bool = False,
) -> dict[object, object]:
    loader.flatten_mapping(node)
    result: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in result
        except TypeError as exc:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found an unhashable mapping key",
                key_node.start_mark,
            ) from exc
        if duplicate:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueKeySafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _validate_yaml_value(value: object, *, depth: int = 0) -> None:
    """Reject hostile scalar values and pathologically deep YAML trees."""
    if depth > _MAX_YAML_DEPTH:
        raise ValueError(f"YAML nesting exceeds {_MAX_YAML_DEPTH} levels")
    if isinstance(value, str):
        if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
            raise ValueError("YAML contains a lone Unicode surrogate")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _validate_yaml_value(key, depth=depth + 1)
            _validate_yaml_value(item, depth=depth + 1)
        return
    if isinstance(value, list):
        for item in value:
            _validate_yaml_value(item, depth=depth + 1)


def parse_project_config(raw_text: str, *, source: str) -> ProjectConfig:
    """Parse and strictly validate one canonical project configuration."""
    try:
        raw_data: Any = yaml.load(raw_text, Loader=_UniqueKeySafeLoader)
        _validate_yaml_value(raw_data)
    except (yaml.YAMLError, RecursionError, ValueError) as exc:
        raise ConfigError(
            f"Invalid YAML in configuration: {source}: {exc}",
            detail={"config_path": source, "error": str(exc)},
        ) from exc

    if not isinstance(raw_data, dict):
        raise ConfigError(
            f"Configuration must contain a YAML mapping, got {type(raw_data).__name__}: {source}",
            detail={"config_path": source, "type": type(raw_data).__name__},
        )

    try:
        return ProjectConfig.model_validate(raw_data)
    except ValidationError as exc:
        raise ConfigError(
            f"Configuration validation failed for {source}: {exc}",
            detail={"config_path": source, "error": str(exc)},
        ) from exc


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
                f"No .agentkit/ directory found in {start_path or Path.cwd()} or any parent directory",
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
    except (OSError, UnicodeError) as exc:
        raise ConfigError(
            f"Failed to read configuration file: {config_path}",
            detail={"config_path": str(config_path), "error": str(exc)},
        ) from exc

    return parse_project_config(raw_text, source=str(config_path))
