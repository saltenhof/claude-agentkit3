"""Strict, fail-closed YAML load for project configuration (AG3-176 AC2).

Rejects the lenient defaults that otherwise hide configuration faults:

* duplicate mapping keys (no last-wins)
* lone UTF-16 surrogates in strings
* unauthorised YAML tags (only the SafeLoader core set)
* extreme nesting depth
* non-mapping document roots (caller checks mapping type)

Uses PyYAML ``SafeLoader`` as the base so custom constructors stay banned.
"""

from __future__ import annotations

from typing import Any, Final

import yaml
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

#: Maximum nesting depth for project.yaml (fail-closed; same class as JSON).
MAX_YAML_NESTING_DEPTH: Final[int] = 64

#: Named configuration-invalid reason (ARCH-55, installer / ConfigError detail).
REASON_CONFIGURATION_INVALID: Final = "configuration_invalid"


class StrictYamlError(ValueError):
    """Raised when YAML is present but not strictly loadable."""

    def __init__(self, message: str, *, reason: str = REASON_CONFIGURATION_INVALID) -> None:
        self.reason = reason
        super().__init__(message)


def _contains_lone_surrogate(text: str) -> bool:
    """Return True when *text* contains an unpaired UTF-16 surrogate."""
    for ch in text:
        code = ord(ch)
        if 0xD800 <= code <= 0xDFFF:
            return True
    return False


class _StrictSafeLoader(yaml.SafeLoader):
    """SafeLoader that rejects duplicate keys and lone surrogates."""

    def construct_mapping(
        self, node: MappingNode, deep: bool = False
    ) -> dict[Any, Any]:
        if not isinstance(node, MappingNode):
            raise yaml.constructor.ConstructorError(
                None,
                None,
                f"expected a mapping node, got {node.id}",
                node.start_mark,
            )
        self.flatten_mapping(node)
        mapping: dict[Any, Any] = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if isinstance(key, str) and _contains_lone_surrogate(key):
                raise StrictYamlError(
                    f"YAML mapping key contains a lone UTF-16 surrogate "
                    f"near line {key_node.start_mark.line + 1}"
                )
            if key in mapping:
                raise StrictYamlError(
                    f"duplicate YAML mapping key {key!r} near line "
                    f"{key_node.start_mark.line + 1} (last-wins forbidden, "
                    f"fail-closed, AG3-176 AC2)"
                )
            value = self.construct_object(value_node, deep=deep)
            if isinstance(value, str) and _contains_lone_surrogate(value):
                raise StrictYamlError(
                    f"YAML string contains a lone UTF-16 surrogate near line "
                    f"{value_node.start_mark.line + 1}"
                )
            mapping[key] = value
        return mapping

    def construct_scalar(self, node: ScalarNode) -> Any:  # type: ignore[override]
        value = super().construct_scalar(node)
        if isinstance(value, str) and _contains_lone_surrogate(value):
            raise StrictYamlError(
                f"YAML string contains a lone UTF-16 surrogate near line "
                f"{node.start_mark.line + 1}"
            )
        return value


def _node_depth(node: Node, *, limit: int = MAX_YAML_NESTING_DEPTH) -> int:
    """Compute nesting depth iteratively; raise when depth exceeds *limit*."""
    max_depth = 1
    stack: list[tuple[Node, int]] = [(node, 1)]
    while stack:
        current, depth = stack.pop()
        if depth > limit:
            raise StrictYamlError(
                f"YAML nesting depth exceeds limit of {limit} (fail-closed, AG3-176 AC2)"
            )
        if depth > max_depth:
            max_depth = depth
        if isinstance(current, MappingNode):
            for key_node, value_node in current.value:
                stack.append((key_node, depth + 1))
                stack.append((value_node, depth + 1))
        elif isinstance(current, SequenceNode):
            for child in current.value:
                stack.append((child, depth + 1))
    return max_depth


def strict_load_yaml(text: str) -> Any:
    """Parse *text* with fail-closed YAML rules.

    Returns:
        The loaded Python object (typically a ``dict``).

    Raises:
        StrictYamlError: On duplicate keys, surrogates, extreme depth, or
            unauthorised tags / syntax errors.
    """
    try:
        stream = yaml.compose(text, Loader=_StrictSafeLoader)
    except StrictYamlError:
        raise
    except RecursionError as exc:
        raise StrictYamlError(
            f"YAML nesting exceeds decoder limits (fail-closed, AG3-176 R13): {exc}"
        ) from exc
    except yaml.YAMLError as exc:
        raise StrictYamlError(f"invalid YAML: {exc}") from exc

    if stream is None:
        return None

    try:
        _node_depth(stream)
    except StrictYamlError:
        raise

    try:
        loaded = yaml.load(text, Loader=_StrictSafeLoader)  # noqa: S506 -- StrictSafeLoader
    except StrictYamlError:
        raise
    except RecursionError as exc:
        raise StrictYamlError(
            f"YAML nesting exceeds decoder limits (fail-closed, AG3-176 R13): {exc}"
        ) from exc
    except yaml.YAMLError as exc:
        raise StrictYamlError(f"invalid YAML: {exc}") from exc

    return loaded


__all__ = [
    "MAX_YAML_NESTING_DEPTH",
    "REASON_CONFIGURATION_INVALID",
    "StrictYamlError",
    "strict_load_yaml",
]
