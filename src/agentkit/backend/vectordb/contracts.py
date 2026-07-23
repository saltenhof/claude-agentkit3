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
    value = args.get(key)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ToolArgumentError(f"argument {key!r} must be a string (AC10)")
    return value.strip()


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
    """Resolve the tool ``project_id`` against the binding (D2).

    Omitted -> bound id; divergent -> REJECTED (never cross-project).
    """
    supplied = args.get("project_id")
    try:
        return binding.resolve_project_id(supplied if isinstance(supplied, str) else None)
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


__all__ = [
    "CONCEPT_STATUSES",
    "DEFAULT_LIMIT",
    "MAX_LIMIT",
    "TOOL_CONTRACTS",
    "TOOL_NAMES",
    "ToolArgumentError",
    "ToolContract",
    "contract_for",
    "optional_str",
    "require_str",
    "resolve_project_id",
    "validate_bool",
    "validate_concept_status",
    "validate_limit",
    "validate_search_args",
    "validate_search_mode",
]
