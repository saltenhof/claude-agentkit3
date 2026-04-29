"""Translate a JSON filter DSL into Weaviate v4 Filter objects.

The DSL is recursive so callers can build arbitrary boolean expressions
without learning the Weaviate Python API:

    {"op": "equal", "property": "layer", "value": "technical"}

    {"op": "and", "operands": [
        {"op": "equal", "property": "layer", "value": "formal"},
        {"op": "contains_any", "property": "tags", "value": ["governance"]}
    ]}

    {"op": "or", "operands": [...]}

Supported leaf ops: equal, not_equal, contains_any, contains_all, like.
"""

from __future__ import annotations

from typing import Any

from weaviate.classes.query import Filter

_LEAF_OPS = {"equal", "not_equal", "contains_any", "contains_all", "like"}
_GROUP_OPS = {"and", "or"}


class FilterSyntaxError(ValueError):
    """Raised when the filter DSL is malformed."""


def build_filter(node: Any) -> Filter | None:
    if node is None:
        return None
    if not isinstance(node, dict):
        raise FilterSyntaxError(f"filter node must be an object, got {type(node).__name__}")
    op = node.get("op")
    if not isinstance(op, str):
        raise FilterSyntaxError("filter node is missing 'op'")
    if op in _GROUP_OPS:
        return _build_group(op, node)
    if op in _LEAF_OPS:
        return _build_leaf(op, node)
    raise FilterSyntaxError(f"unsupported filter op: {op}")


def _build_group(op: str, node: dict[str, Any]) -> Filter:
    operands = node.get("operands")
    if not isinstance(operands, list) or not operands:
        raise FilterSyntaxError(f"'{op}' requires a non-empty 'operands' list")
    children: list[Filter] = []
    for raw in operands:
        child = build_filter(raw)
        if child is None:
            raise FilterSyntaxError("nested filter operand cannot be null")
        children.append(child)
    if op == "and":
        return Filter.all_of(children)
    return Filter.any_of(children)


def _build_leaf(op: str, node: dict[str, Any]) -> Filter:
    prop = node.get("property")
    if not isinstance(prop, str) or not prop:
        raise FilterSyntaxError(f"'{op}' requires a 'property' string")
    if "value" not in node:
        raise FilterSyntaxError(f"'{op}' requires a 'value'")
    value = node["value"]
    target = Filter.by_property(prop)
    if op == "equal":
        return target.equal(value)
    if op == "not_equal":
        return target.not_equal(value)
    if op == "contains_any":
        return target.contains_any(_as_list(value, op))
    if op == "contains_all":
        return target.contains_all(_as_list(value, op))
    if op == "like":
        if not isinstance(value, str):
            raise FilterSyntaxError("'like' value must be a string")
        return target.like(value)
    raise FilterSyntaxError(f"unhandled leaf op: {op}")


def _as_list(value: Any, op: str) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, (str, int, float, bool)):
        return [value]
    raise FilterSyntaxError(f"'{op}' value must be a scalar or list")
