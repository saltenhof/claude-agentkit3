"""MCP tool contracts: names, required params, return fields, strict validators.

FK-13 §13.4.1 / §13.9.5 are bound here as the abnahmeverbindliche contract. The
strict argument validators implement the AC10 MCP-input axis: no bool-as-int
coercion, bounded positive ``limit``, strict enums, foreign ``project_id``
rejected (D2).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from agentkit.backend.vectordb.runtime_binding import RuntimeBinding, RuntimeBindingError
from agentkit.integration_clients.vectordb.weaviate_adapter import SEARCH_MODES

if TYPE_CHECKING:
    from collections.abc import Mapping

#: Max results a single search may return (bounded, AC10).
MAX_LIMIT: Final[int] = 100
DEFAULT_LIMIT: Final[int] = 10

#: Allowed concept_status filter values (FK-13 §13.9.5).
CONCEPT_STATUSES: Final[tuple[str, ...]] = ("active", "draft", "archived")


class ToolArgumentError(ValueError):
    """Raised when an MCP tool argument is invalid (fail-closed, AC10)."""


@dataclass(frozen=True)
class ToolContract:
    """One FK-13 MCP tool contract (name, required params, return fields)."""

    name: str
    description: str
    required_params: tuple[str, ...]
    optional_params: tuple[str, ...]
    return_fields: tuple[str, ...]


#: The five FK-13 tools (§13.4.1 / §13.9.5) -- the contract source of truth.
TOOL_CONTRACTS: Final[tuple[ToolContract, ...]] = (
    ToolContract(
        name="story_search",
        description="Semantic search over stories and research.",
        required_params=("query",),
        optional_params=("search_mode", "project_id", "status", "story_type", "limit"),
        return_fields=(
            "story_id", "title", "status", "story_type", "source_type", "module",
            "epic", "section_heading", "score", "snippet",
        ),
    ),
    ToolContract(
        name="story_list_sources",
        description="List indexed source types and producers for the bound project.",
        required_params=(),
        optional_params=("project_id",),
        return_fields=(
            "project_id", "source_type", "producer", "source_count",
            "chunk_count", "last_revision",
        ),
    ),
    ToolContract(
        name="story_sync",
        description="Incremental/full index of story and research sources.",
        required_params=(),
        optional_params=("project_id", "full_reindex"),
        return_fields=("project_id", "synced_sources", "written", "deleted", "corpus_revision"),
    ),
    ToolContract(
        name="concept_search",
        description="Semantic search over concept documents (default active, authority-ranked).",
        required_params=("query",),
        optional_params=(
            "search_mode", "project_id", "concept_id", "module",
            "is_appendix", "concept_status", "limit",
        ),
        return_fields=(
            "concept_id", "title", "module", "section_heading", "section_number",
            "is_appendix", "parent_concept_id", "defers_to", "authority_over",
            "normative_rules", "concept_status", "score", "snippet",
        ),
    ),
    ToolContract(
        name="concept_sync",
        description="Incremental/full index of concept sources (validate is a precondition).",
        required_params=(),
        optional_params=("project_id", "full_reindex", "concept_path"),
        return_fields=("project_id", "synced_sources", "written", "deleted", "corpus_revision"),
    ),
)

#: Tool names in canonical order.
TOOL_NAMES: Final[tuple[str, ...]] = tuple(t.name for t in TOOL_CONTRACTS)


def allowed_keys_for(name: str) -> frozenset[str]:
    """Return the exact allowed argument-key set for a tool (R13)."""
    contract = contract_for(name)
    return frozenset(contract.required_params + contract.optional_params)


def contract_for(name: str) -> ToolContract:
    """Return the tool contract by name (fail-closed on unknown)."""
    for contract in TOOL_CONTRACTS:
        if contract.name == name:
            return contract
    raise ToolArgumentError(f"unknown tool {name!r}")


# --------------------------------------------------------------------------- #
# Strict argument validation (AC10 MCP-input axis)
# --------------------------------------------------------------------------- #


def require_str(args: Mapping[str, Any], key: str) -> str:
    """Return a mandatory non-empty string argument (no coercion)."""
    value = args.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ToolArgumentError(f"argument {key!r} must be a non-empty string (AC10)")
    return value.strip()


def optional_str(args: Mapping[str, Any], key: str) -> str:
    """Return an optional string arg (``""`` when omitted).

    A PRESENT but wrong-typed value is a named error (R13): never coerced to a
    default and never silently ignored.
    """
    value = args.get(key)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ToolArgumentError(
            f"argument {key!r} must be a string, got {type(value).__name__} (AC10/R13)"
        )
    return value.strip()


def require_str_or_none(args: Mapping[str, Any], key: str) -> str | None:
    """Return a present-or-absent string arg as ``str | None`` (strict typing).

    A wrong-typed value is a named error (R13) -- NOT coerced to ``None``.
    """
    value = args.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ToolArgumentError(
            f"argument {key!r} must be a string, got {type(value).__name__} (AC10/R13)"
        )
    if not value.strip():
        return None
    return value.strip()


def reject_unknown_args(name: str, args: Mapping[str, Any]) -> None:
    """Reject any argument key outside the tool's allowed set (R13)."""
    allowed = allowed_keys_for(name)
    unknown = sorted(set(args.keys()) - allowed)
    if unknown:
        raise ToolArgumentError(
            f"tool {name!r} received unknown argument(s) {unknown}; "
            f"allowed: {sorted(allowed)} (AC10/R13)."
        )


def validate_search_mode(value: Any) -> str:
    if value is None:
        return "hybrid"
    if not isinstance(value, str) or value not in SEARCH_MODES:
        raise ToolArgumentError(
            f"search_mode {value!r} must be one of {SEARCH_MODES} (AC10)"
        )
    return value


def validate_limit(value: Any) -> int:
    if value is None:
        return DEFAULT_LIMIT
    # bool is a subclass of int -- reject bool-as-int explicitly (AC10).
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolArgumentError(f"limit must be an integer, got {type(value).__name__} (AC10)")
    if value <= 0 or value > MAX_LIMIT:
        raise ToolArgumentError(f"limit {value} must be in 1..{MAX_LIMIT} (AC10)")
    return int(value)


def validate_bool(value: Any, *, name: str) -> bool:
    if value is None:
        return False
    if not isinstance(value, bool):
        raise ToolArgumentError(f"{name} must be a boolean, got {type(value).__name__} (AC10)")
    return value


def validate_concept_status(value: Any) -> str:
    if value is None:
        return "active"
    if not isinstance(value, str) or value not in CONCEPT_STATUSES:
        raise ToolArgumentError(
            f"concept_status {value!r} must be one of {CONCEPT_STATUSES} (AC10)"
        )
    return value


def resolve_project_id(binding: RuntimeBinding, args: Mapping[str, Any]) -> str:
    """Resolve the tool ``project_id`` against the binding (D2/R13).

    Strict semantics (R13):
    - ABSENT (key not in args) -> the bound project id (omitted parameter).
    - PRESENT but ``None`` / empty / wrong-typed -> a NAMED validation error
      (NOT a silent fallback to the bound project).
    - PRESENT and equal to the bound id -> the bound id.
    - PRESENT and divergent -> REJECTED (never cross-project).
    """
    if "project_id" not in args:
        return binding.resolve_project_id(None)
    supplied = args["project_id"]
    if supplied is None:
        raise ToolArgumentError(
            "argument 'project_id' is explicitly null; omit it to use the bound "
            "project (R13, no silent fallback)."
        )
    if not isinstance(supplied, str):
        raise ToolArgumentError(
            f"argument 'project_id' must be a string, got {type(supplied).__name__} (AC10/R13)"
        )
    if not supplied.strip():
        raise ToolArgumentError(
            "argument 'project_id' is an empty string; omit it to use the bound "
            "project (R13, no silent fallback)."
        )
    try:
        return binding.resolve_project_id(supplied.strip())
    except RuntimeBindingError as exc:
        raise ToolArgumentError(str(exc)) from exc


def validate_search_args(
    binding: RuntimeBinding, args: Mapping[str, Any]
) -> dict[str, Any]:
    """Validate the common search arguments (query, search_mode, project_id, limit)."""
    return {
        "query": require_str(args, "query"),
        "search_mode": validate_search_mode(args.get("search_mode")),
        "project_id": resolve_project_id(binding, args),
        "limit": validate_limit(args.get("limit")),
    }


def validate_story_filters(args: Mapping[str, Any]) -> dict[str, object]:
    """Strictly validate the optional story filters (status, story_type) (R13)."""
    filters: dict[str, object] = {}
    status = require_str_or_none(args, "status")
    if status:
        filters["status"] = status
    story_type = require_str_or_none(args, "story_type")
    if story_type:
        filters["story_type"] = story_type
    return filters


def validate_concept_filters(args: Mapping[str, Any]) -> dict[str, object]:
    """Strictly validate the optional concept filters (R13)."""
    concept_status = validate_concept_status(args.get("concept_status"))
    filters: dict[str, object] = {"concept_status": concept_status}
    is_appendix = args.get("is_appendix")
    if is_appendix is not None:
        filters["is_appendix"] = validate_bool(is_appendix, name="is_appendix")
    concept_id = require_str_or_none(args, "concept_id")
    if concept_id:
        filters["concept_id"] = concept_id
    module = require_str_or_none(args, "module")
    if module:
        filters["module"] = module
    return filters


__all__ = [
    "CONCEPT_STATUSES",
    "DEFAULT_LIMIT",
    "MAX_LIMIT",
    "TOOL_CONTRACTS",
    "TOOL_NAMES",
    "ToolArgumentError",
    "ToolContract",
    "allowed_keys_for",
    "contract_for",
    "optional_str",
    "reject_unknown_args",
    "require_str",
    "require_str_or_none",
    "resolve_project_id",
    "validate_bool",
    "validate_concept_filters",
    "validate_concept_status",
    "validate_limit",
    "validate_search_args",
    "validate_search_mode",
    "validate_story_filters",
]
