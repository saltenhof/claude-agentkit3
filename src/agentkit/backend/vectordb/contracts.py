"""MCP tool contracts: names, parameters, return fields, strict validators.

FK-13 §13.4.1 / §13.9.5 are bound here as the abnahmeverbindliche contract. This
module is the SINGLE source of truth for

- the five tool names and their parameter sets,
- the ADVERTISED JSON input schema (built from the same table the validators
  use, so the schema can never drift from the enforcement), and
- the strict argument validation (AC10 MCP-input axis): no bool-as-int coercion,
  bounded positive ``limit``, strict enums, foreign ``project_id`` rejected (D2).

Absence semantics (R13): every validator takes the ARGUMENT MAPPING, not a
pre-extracted value, so an ABSENT key is distinguishable from an explicitly
supplied ``null`` / empty value. Only an absent key falls back to the documented
default; an explicit ``null``, an empty string or a wrongly-typed value is a
NAMED error for EVERY optional parameter.
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
class ToolParam:
    """One FK-13 tool parameter (name, JSON type, requiredness, enum)."""

    name: str
    json_type: str
    required: bool
    description: str
    enum: tuple[str, ...] = ()
    minimum: int | None = None
    maximum: int | None = None
    item_type: str = ""
    item_enum: tuple[str, ...] = ()

    def json_schema(self) -> dict[str, object]:
        """Return the JSON-Schema fragment advertised for this parameter.

        The type NEVER includes ``null``: an explicit JSON ``null`` is invalid
        for every optional parameter (R13), and only an absent key falls back to
        the documented default.

        An ``array`` parameter advertises its element type/enum plus the two
        constraints the strict validator enforces: at least one entry and no
        duplicates (D8 -- an empty or duplicated set is a named error, never
        silently normalised).
        """
        schema: dict[str, object] = {"type": self.json_type, "description": self.description}
        if self.enum:
            schema["enum"] = list(self.enum)
        if self.minimum is not None:
            schema["minimum"] = self.minimum
        if self.maximum is not None:
            schema["maximum"] = self.maximum
        if self.json_type == "array":
            items: dict[str, object] = {"type": self.item_type}
            if self.item_enum:
                items["enum"] = list(self.item_enum)
            schema["items"] = items
            schema["minItems"] = 1
            schema["uniqueItems"] = True
        return schema


@dataclass(frozen=True)
class ToolContract:
    """One FK-13 MCP tool contract (name, parameters, return fields)."""

    name: str
    description: str
    params: tuple[ToolParam, ...]
    return_fields: tuple[str, ...]

    @property
    def required_params(self) -> tuple[str, ...]:
        return tuple(p.name for p in self.params if p.required)

    @property
    def optional_params(self) -> tuple[str, ...]:
        return tuple(p.name for p in self.params if not p.required)

    def input_schema(self) -> dict[str, object]:
        """Return the advertised MCP ``inputSchema`` for this tool.

        ``additionalProperties: false`` mirrors :func:`reject_unknown_args`, so
        the advertised contract and the enforced contract are the same set.
        """
        return {
            "type": "object",
            "properties": {p.name: p.json_schema() for p in self.params},
            "required": list(self.required_params),
            "additionalProperties": False,
        }


_QUERY = ToolParam("query", "string", True, "Natural-language search text.")
_SEARCH_MODE = ToolParam(
    "search_mode", "string", False, "hybrid (default), vector or keyword.", enum=SEARCH_MODES
)
_PROJECT_ID = ToolParam(
    "project_id", "string", False, "Bound project id; a divergent value is rejected (D2)."
)
_LIMIT = ToolParam(
    "limit", "integer", False, f"Max results (default {DEFAULT_LIMIT}).",
    minimum=1, maximum=MAX_LIMIT,
)
_FULL_REINDEX = ToolParam(
    "full_reindex", "boolean", False, "Complete rebuild of the owned source types."
)

#: The five FK-13 tools (§13.4.1 / §13.9.5) -- the contract source of truth.
TOOL_CONTRACTS: Final[tuple[ToolContract, ...]] = (
    ToolContract(
        name="story_search",
        description="Semantic search over stories and research.",
        params=(
            _QUERY,
            _SEARCH_MODE,
            _PROJECT_ID,
            ToolParam("status", "string", False, "Story status filter (e.g. Done)."),
            ToolParam("story_type", "string", False, "Story type filter (e.g. concept)."),
            _LIMIT,
        ),
        return_fields=(
            "story_id", "title", "status", "story_type", "source_type", "module",
            "epic", "section_heading", "score", "snippet",
        ),
    ),
    ToolContract(
        name="story_list_sources",
        description="List indexed source types and producers for the bound project.",
        params=(_PROJECT_ID,),
        return_fields=(
            "project_id", "source_type", "producer", "source_count",
            "chunk_count", "last_revision",
        ),
    ),
    ToolContract(
        name="story_sync",
        description="Incremental/full index of story and research sources.",
        params=(_PROJECT_ID, _FULL_REINDEX),
        return_fields=("project_id", "synced_sources", "written", "deleted", "corpus_revision"),
    ),
    ToolContract(
        name="concept_search",
        description="Semantic search over concept documents (default active, authority-ranked).",
        params=(
            _QUERY,
            _SEARCH_MODE,
            _PROJECT_ID,
            ToolParam("concept_id", "string", False, "Filter on a specific concept."),
            ToolParam("module", "string", False, "Module filter (where a document lives)."),
            ToolParam(
                "authority_scope", "string", False,
                "authority_over scope the ranking rules 1/2 evaluate against "
                "(§13.9.11); a RANKING input, not a filter, and never derived "
                "from module (D7).",
            ),
            ToolParam("is_appendix", "boolean", False, "Only appendices / only core."),
            ToolParam(
                "concept_status", "array", False,
                'Status SET of the result; default ["active"]. Several statuses may '
                "be requested together; ranking rule 4 then orders active before "
                "draft/archived (D8).",
                item_type="string",
                item_enum=CONCEPT_STATUSES,
            ),
            _LIMIT,
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
        params=(
            _PROJECT_ID,
            _FULL_REINDEX,
            ToolParam("concept_path", "string", False, "Path of a single concept document."),
        ),
        return_fields=("project_id", "synced_sources", "written", "deleted", "corpus_revision"),
    ),
)

#: Tool names in canonical order.
TOOL_NAMES: Final[tuple[str, ...]] = tuple(t.name for t in TOOL_CONTRACTS)


def allowed_keys_for(name: str) -> frozenset[str]:
    """Return the exact allowed argument-key set for a tool (R13)."""
    contract = contract_for(name)
    return frozenset(p.name for p in contract.params)


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


def optional_str(args: Mapping[str, Any], key: str) -> str | None:
    """Return an optional string argument with STRICT absence semantics (R13).

    - key ABSENT -> ``None`` (the documented "no filter" default);
    - key present with ``null`` / empty / whitespace -> NAMED error;
    - key present with a non-string -> NAMED error (no coercion).
    """
    if key not in args:
        return None
    value = args[key]
    if value is None:
        raise ToolArgumentError(
            f"argument {key!r} is explicitly null; omit the key to use the default "
            "(R13, no silent fallback)"
        )
    if not isinstance(value, str):
        raise ToolArgumentError(
            f"argument {key!r} must be a string, got {type(value).__name__} (AC10/R13)"
        )
    if not value.strip():
        raise ToolArgumentError(
            f"argument {key!r} is an empty string; omit the key to use the default "
            "(R13, no silent fallback)"
        )
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


def validate_search_mode(args: Mapping[str, Any]) -> str:
    """Validate ``search_mode``: absent -> ``hybrid``; null/empty/unknown -> error."""
    value = optional_str(args, "search_mode")
    if value is None:
        return "hybrid"
    if value not in SEARCH_MODES:
        raise ToolArgumentError(
            f"search_mode {value!r} must be one of {SEARCH_MODES} (AC10)"
        )
    return value


def validate_limit(args: Mapping[str, Any]) -> int:
    """Validate ``limit``: absent -> default; null/bool/non-int/out-of-range -> error."""
    if "limit" not in args:
        return DEFAULT_LIMIT
    value = args["limit"]
    if value is None:
        raise ToolArgumentError(
            "argument 'limit' is explicitly null; omit the key to use the default "
            f"({DEFAULT_LIMIT}) (R13, no silent fallback)"
        )
    # bool is a subclass of int -- reject bool-as-int explicitly (AC10).
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolArgumentError(f"limit must be an integer, got {type(value).__name__} (AC10)")
    if value <= 0 or value > MAX_LIMIT:
        raise ToolArgumentError(f"limit {value} must be in 1..{MAX_LIMIT} (AC10)")
    return int(value)


def validate_bool(args: Mapping[str, Any], *, name: str) -> bool:
    """Validate an optional boolean: absent -> ``False``; null/non-bool -> error."""
    if name not in args:
        return False
    value = args[name]
    if value is None:
        raise ToolArgumentError(
            f"argument {name!r} is explicitly null; omit the key to use the default "
            "(False) (R13, no silent fallback)"
        )
    if not isinstance(value, bool):
        raise ToolArgumentError(f"{name} must be a boolean, got {type(value).__name__} (AC10)")
    return value


def validate_concept_status(args: Mapping[str, Any]) -> tuple[str, ...]:
    """Validate the ``concept_status`` SET (FK-13 §13.9.5/§13.9.10, D8).

    The filter is a LIST so several statuses can be requested together; ranking
    rule 4 then orders active before draft/archived. Semantics, fail-closed and
    without any coercion (consistent with D2/D7):

    - key ABSENT -> ``("active",)``, the documented default;
    - a BARE STRING is a named error, not a one-element list;
    - explicit ``null``, an empty list, an unknown value, a duplicate and a
      non-string element are named errors.

    Args:
        args: The RAW tool arguments as they arrived.

    Returns:
        The requested statuses in the caller's order (no normalisation).

    Raises:
        ToolArgumentError: For any of the rejected shapes above.
    """
    if "concept_status" not in args:
        return ("active",)
    value = args["concept_status"]
    if value is None:
        raise ToolArgumentError(
            "argument 'concept_status' is explicitly null; omit the key to use the "
            'default ["active"] (R13, no silent fallback)'
        )
    if isinstance(value, str):
        raise ToolArgumentError(
            f"concept_status must be a LIST of status values, got the bare string "
            f"{value!r}; use [{value!r}] (D8, no coercion)"
        )
    if not isinstance(value, (list, tuple)):
        raise ToolArgumentError(
            f"concept_status must be a list of status values, got "
            f"{type(value).__name__} (D8/AC10)"
        )
    if not value:
        raise ToolArgumentError(
            "concept_status is an empty list; omit the key to use the default "
            '["active"] (D8, an empty status set selects nothing)'
        )
    seen: list[str] = []
    for entry in value:
        if not isinstance(entry, str):
            raise ToolArgumentError(
                f"concept_status entry {entry!r} must be a string, got "
                f"{type(entry).__name__} (D8/AC10)"
            )
        if entry not in CONCEPT_STATUSES:
            raise ToolArgumentError(
                f"concept_status {entry!r} must be one of {CONCEPT_STATUSES} (AC10)"
            )
        if entry in seen:
            raise ToolArgumentError(
                f"concept_status lists {entry!r} twice; a duplicate is rejected "
                "rather than de-duplicated (D8, no silent normalisation)"
            )
        seen.append(entry)
    return tuple(seen)


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
    supplied = optional_str(args, "project_id")
    try:
        return binding.resolve_project_id(supplied)
    except RuntimeBindingError as exc:
        raise ToolArgumentError(str(exc)) from exc


def validate_search_args(
    binding: RuntimeBinding, args: Mapping[str, Any]
) -> dict[str, Any]:
    """Validate the common search arguments (query, search_mode, project_id, limit)."""
    return {
        "query": require_str(args, "query"),
        "search_mode": validate_search_mode(args),
        "project_id": resolve_project_id(binding, args),
        "limit": validate_limit(args),
    }


def validate_story_filters(args: Mapping[str, Any]) -> dict[str, object]:
    """Strictly validate the optional story filters (status, story_type) (R13)."""
    filters: dict[str, object] = {}
    status = optional_str(args, "status")
    if status is not None:
        filters["status"] = status
    story_type = optional_str(args, "story_type")
    if story_type is not None:
        filters["story_type"] = story_type
    return filters


def validate_concept_filters(args: Mapping[str, Any]) -> dict[str, object]:
    """Strictly validate the optional concept filters (R13)."""
    filters: dict[str, object] = {"concept_status": validate_concept_status(args)}
    if "is_appendix" in args:
        filters["is_appendix"] = validate_bool(args, name="is_appendix")
    concept_id = optional_str(args, "concept_id")
    if concept_id is not None:
        filters["concept_id"] = concept_id
    module = optional_str(args, "module")
    if module is not None:
        filters["module"] = module
    return filters


def validate_authority_scope(args: Mapping[str, Any]) -> str:
    """Strictly validate the RANKING input ``authority_scope`` (FK-13 §13.9.5, D7).

    It is deliberately NOT part of :func:`validate_concept_filters`: the scope does
    not restrict the result set, it names the ``authority_over`` scope the ranking
    rules 1/2 evaluate against (§13.9.11). Absence is a valid state -- rules 1/2
    then do not apply and 3/4/5 stay unchanged -- so an absent key yields ``""``.
    Explicit ``null``, an empty/whitespace string and any non-string are NAMED
    errors, exactly like every other optional (R13/AC10).

    Args:
        args: The RAW tool arguments as they arrived.

    Returns:
        The requested authority scope, or ``""`` when the caller asked for none.

    Raises:
        ToolArgumentError: The key is present but not a usable scope string.
    """
    scope = optional_str(args, "authority_scope")
    return scope if scope is not None else ""


__all__ = [
    "CONCEPT_STATUSES",
    "DEFAULT_LIMIT",
    "MAX_LIMIT",
    "TOOL_CONTRACTS",
    "TOOL_NAMES",
    "ToolArgumentError",
    "ToolContract",
    "ToolParam",
    "allowed_keys_for",
    "contract_for",
    "optional_str",
    "validate_authority_scope",
    "reject_unknown_args",
    "require_str",
    "resolve_project_id",
    "validate_bool",
    "validate_concept_filters",
    "validate_concept_status",
    "validate_limit",
    "validate_search_args",
    "validate_search_mode",
    "validate_story_filters",
]
