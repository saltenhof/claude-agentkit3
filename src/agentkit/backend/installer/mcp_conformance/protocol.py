"""JSON-RPC 2.0 envelope and MCP payload validation (AG3-164).

Blutgruppe A: pure classification / validation, no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from agentkit.backend.installer.mcp_conformance.types import (
    SUPPORTED_PROTOCOL_VERSIONS,
    McpConformanceReason,
    McpConformanceResult,
)
from agentkit.backend.installer.strict_json import (
    contains_lone_surrogate,
    contains_non_finite_float,
    exceeds_max_json_nesting,
    reject_duplicate_object_pairs,
    reject_non_json_constant,
)

_JsonRpcKind = Literal["notification", "response", "request"]


@dataclass(frozen=True, slots=True)
class ClassifiedMessage:
    """A well-formed JSON-RPC 2.0 message."""

    kind: _JsonRpcKind
    message: dict[str, Any]
    msg_id: object | None


def fail(reason: McpConformanceReason, detail: str) -> McpConformanceResult:
    """Build a failed conformance result."""
    return McpConformanceResult(ok=False, reason=reason, detail=detail)


def ok(detail: str, *, tool_names: tuple[str, ...] = ()) -> McpConformanceResult:
    """Build a successful intermediate or final result."""
    return McpConformanceResult(
        ok=True, reason=None, detail=detail, tool_names=tool_names
    )


def parse_json_object(line: str, *, cmd_label: str) -> dict[str, Any] | McpConformanceResult:
    """Parse one stdout line as a strict JSON object or return protocol_error.

    Fail-closed wire policy (library defaults are not trustable here):

    * ``parse_constant`` rejects non-JSON tokens (NaN/Infinity/-Infinity)
    * ``object_pairs_hook`` rejects duplicate object names at every level
    * decoder / validation nesting limits are protocol_error (not an internal fault)
    * non-finite floats (e.g. overflow from ``1e400``) are rejected
    * lone UTF-16 surrogate code points in any string are rejected

    Post-decode tree walks are iterative (shared ``strict_json`` helpers).
    """
    import json

    try:
        message = json.loads(
            line,
            parse_constant=reject_non_json_constant,
            object_pairs_hook=reject_duplicate_object_pairs,
        )
    except json.JSONDecodeError:
        return fail(
            McpConformanceReason.PROTOCOL_ERROR,
            f"MCP process produced non-JSON stdout for command: {cmd_label}.",
        )
    except RecursionError:
        return fail(
            McpConformanceReason.PROTOCOL_ERROR,
            f"MCP process produced JSON nesting that exceeds validation limits "
            f"for command: {cmd_label}.",
        )
    if not isinstance(message, dict):
        return fail(
            McpConformanceReason.PROTOCOL_ERROR,
            "MCP process produced a non-object JSON message.",
        )
    if exceeds_max_json_nesting(message):
        return fail(
            McpConformanceReason.PROTOCOL_ERROR,
            f"MCP process produced JSON nesting that exceeds validation limits "
            f"for command: {cmd_label}.",
        )
    if contains_non_finite_float(message):
        return fail(
            McpConformanceReason.PROTOCOL_ERROR,
            f"MCP process produced non-finite JSON number for command: {cmd_label}.",
        )
    if contains_lone_surrogate(message):
        return fail(
            McpConformanceReason.PROTOCOL_ERROR,
            f"MCP process produced lone UTF-16 surrogate in string for command: "
            f"{cmd_label}.",
        )
    return message


def classify_jsonrpc_message(
    message: dict[str, Any], *, cmd_label: str
) -> ClassifiedMessage | McpConformanceResult:
    """Classify a JSON object as a well-formed JSON-RPC 2.0 message.

    Disjoint envelope variants (JSON-RPC 2.0):

    * **notification** — ``method`` (string), no ``id``, no ``result``/``error``;
      optional ``params`` must be object or array.
    * **response** — ``id`` present, no ``method``, exactly one of ``result``/``error``.
    * **request** — ``method`` (string) + ``id``, no ``result``/``error``;
      optional ``params`` must be object or array.

    A present but wrongly typed ``method`` is a protocol error (not silently
    ignored). Boolean JSON-RPC ids are rejected.
    """
    if message.get("jsonrpc") != "2.0":
        return fail(
            McpConformanceReason.PROTOCOL_ERROR,
            f"MCP message missing jsonrpc '2.0' for command: {cmd_label}.",
        )

    if "method" in message:
        method = message["method"]
        if not isinstance(method, str) or not method:
            return fail(
                McpConformanceReason.PROTOCOL_ERROR,
                f"MCP message method must be a non-empty string for command: {cmd_label}.",
            )

    has_method = "method" in message
    has_id = "id" in message
    has_result = "result" in message
    has_error = "error" in message

    if has_method and not has_id:
        # Notification
        if has_result or has_error:
            return fail(
                McpConformanceReason.PROTOCOL_ERROR,
                f"MCP notification must not carry result/error for command: {cmd_label}.",
            )
        params_err = _validate_params_if_present(message, cmd_label=cmd_label)
        if params_err is not None:
            return params_err
        return ClassifiedMessage(kind="notification", message=message, msg_id=None)

    if has_id and not has_method:
        # Response: exactly one of result / error
        if has_result and has_error:
            return fail(
                McpConformanceReason.PROTOCOL_ERROR,
                f"MCP response must not carry both result and error "
                f"for command: {cmd_label}.",
            )
        if not has_result and not has_error:
            return fail(
                McpConformanceReason.PROTOCOL_ERROR,
                f"MCP response missing result/error for command: {cmd_label}.",
            )
        mid = message.get("id")
        if not _is_valid_jsonrpc_id(mid):
            return fail(
                McpConformanceReason.PROTOCOL_ERROR,
                f"MCP response id is not a valid JSON-RPC id for command: {cmd_label}.",
            )
        return ClassifiedMessage(kind="response", message=message, msg_id=mid)

    if has_method and has_id:
        # Request
        if has_result or has_error:
            return fail(
                McpConformanceReason.PROTOCOL_ERROR,
                f"MCP request must not carry result/error for command: {cmd_label}.",
            )
        mid = message.get("id")
        if not _is_valid_jsonrpc_id(mid):
            return fail(
                McpConformanceReason.PROTOCOL_ERROR,
                f"MCP request id is not a valid JSON-RPC id for command: {cmd_label}.",
            )
        params_err = _validate_params_if_present(message, cmd_label=cmd_label)
        if params_err is not None:
            return params_err
        return ClassifiedMessage(kind="request", message=message, msg_id=mid)

    return fail(
        McpConformanceReason.PROTOCOL_ERROR,
        f"MCP message is not a valid JSON-RPC request/response/notification "
        f"for command: {cmd_label}.",
    )


def _validate_params_if_present(
    message: dict[str, Any], *, cmd_label: str
) -> McpConformanceResult | None:
    if "params" not in message:
        return None
    params = message["params"]
    if isinstance(params, (dict, list)):
        return None
    return fail(
        McpConformanceReason.PROTOCOL_ERROR,
        f"MCP params must be object or array when present for command: {cmd_label}.",
    )


def _is_valid_jsonrpc_id(value: object) -> bool:
    """JSON-RPC id: string, number, or null — not boolean."""
    if value is None:
        return True
    if type(value) is bool:
        return False
    if type(value) is int:
        return True
    if type(value) is float:
        return True
    return type(value) is str


def ids_match_strict(*, expected: int, actual: object) -> bool:
    """Strict ID match for integer client request IDs.

    Python's ``True == 1`` must not accept boolean IDs for integer requests.
    """
    if type(actual) is bool:
        return False
    if type(actual) is int:
        return actual == expected
    return False


def handle_response_for_request(
    message: dict[str, Any],
    *,
    request_id: int,
    cmd_label: str,
) -> McpConformanceResult:
    """Validate a JSON-RPC response body for initialize (id=1) or tools/list (id=2)."""
    if "error" in message:
        return fail(
            McpConformanceReason.PROTOCOL_ERROR,
            f"MCP JSON-RPC error for id={request_id}: {message.get('error')!r}.",
        )

    result = message.get("result")
    if not isinstance(result, dict):
        return fail(
            McpConformanceReason.PROTOCOL_ERROR,
            f"MCP response id={request_id} missing object result for command: {cmd_label}.",
        )

    if request_id == 1:
        return validate_initialize_result(result, cmd_label=cmd_label)
    return validate_tools_list_result(result, cmd_label=cmd_label)


def _format_validation_error(exc: Exception) -> str:
    """Compact first pydantic/mcp validation error for diagnostics."""
    errors = getattr(exc, "errors", None)
    if callable(errors):
        try:
            items = errors()
        except Exception:  # noqa: BLE001 — diagnostic only
            return str(exc)
        if items:
            first = items[0]
            loc = ".".join(str(p) for p in first.get("loc", ()))
            msg = first.get("msg", str(exc))
            return f"{loc}: {msg}" if loc else msg
    return str(exc)


def validate_initialize_result(
    result: dict[str, Any], *, cmd_label: str
) -> McpConformanceResult:
    """Validate MCP initialize result against the official SDK type contract.

    Path: hard runtime dependency on ``mcp.types.InitializeResult`` (no optional
    import). Unknown extension keys are preserved by the SDK model. AK3 then
    applies stricter product rules (supported protocol versions, tools
    capability present as an object for tools/list).
    """
    from mcp.types import InitializeResult
    from pydantic import ValidationError

    try:
        # strict=True: refuse Pydantic coercion of wire values (e.g. "yes"/1 → bool).
        parsed = InitializeResult.model_validate(result, strict=True)
    except ValidationError as exc:
        return fail(
            McpConformanceReason.PROTOCOL_ERROR,
            f"MCP initialize result failed official schema validation "
            f"for command: {cmd_label}: {_format_validation_error(exc)}.",
        )

    protocol_version = parsed.protocolVersion
    if not isinstance(protocol_version, str) or not protocol_version.strip():
        return fail(
            McpConformanceReason.PROTOCOL_ERROR,
            "MCP initialize response lacks non-empty string protocolVersion "
            f"for command: {cmd_label}.",
        )
    if protocol_version not in SUPPORTED_PROTOCOL_VERSIONS:
        return fail(
            McpConformanceReason.PROTOCOL_ERROR,
            f"Unsupported MCP protocolVersion {protocol_version!r} "
            f"for command: {cmd_label}.",
        )

    # AK3 requires tools capability object so tools/list is meaningful.
    if parsed.capabilities.tools is None:
        return fail(
            McpConformanceReason.PROTOCOL_ERROR,
            "MCP initialize response missing capabilities.tools "
            f"(required for tools list) for command: {cmd_label}.",
        )

    name = parsed.serverInfo.name
    version = parsed.serverInfo.version
    if not isinstance(name, str) or not name.strip():
        return fail(
            McpConformanceReason.PROTOCOL_ERROR,
            "MCP initialize serverInfo.name must be a non-empty string "
            f"for command: {cmd_label}.",
        )
    if not isinstance(version, str) or not version.strip():
        return fail(
            McpConformanceReason.PROTOCOL_ERROR,
            "MCP initialize serverInfo.version must be a non-empty string "
            f"for command: {cmd_label}.",
        )

    return ok("initialize ok")


def validate_tools_list_result(
    result: dict[str, Any], *, cmd_label: str
) -> McpConformanceResult:
    """Validate tools/list against the official SDK type contract, then AK3 rules.

    Full ``ListToolsResult`` / ``Tool`` schema is enforced by ``mcp.types``
    (including optional fields like ``nextCursor``, ``description``,
    ``outputSchema``). AK3 additionally requires a non-empty tool list and
    non-empty tool names.
    """
    from mcp.types import ListToolsResult
    from pydantic import ValidationError

    try:
        # strict=True: refuse Pydantic coercion of wire values (e.g. "yes"/1 → bool).
        parsed = ListToolsResult.model_validate(result, strict=True)
    except ValidationError as exc:
        return fail(
            McpConformanceReason.PROTOCOL_ERROR,
            f"MCP tools list result failed official schema validation "
            f"for command: {cmd_label}: {_format_validation_error(exc)}.",
        )

    if not parsed.tools:
        return fail(
            McpConformanceReason.TOOLS_LIST_EMPTY,
            f"MCP tools list returned no tools for command: {cmd_label}.",
        )

    names: list[str] = []
    for index, tool in enumerate(parsed.tools):
        name = tool.name
        if not isinstance(name, str) or not name.strip():
            return fail(
                McpConformanceReason.PROTOCOL_ERROR,
                f"MCP tools list tools[{index}].name must be a non-empty string "
                f"for command: {cmd_label}.",
            )
        names.append(name)

    return ok("tools list ok", tool_names=tuple(names))


__all__ = [
    "ClassifiedMessage",
    "classify_jsonrpc_message",
    "fail",
    "handle_response_for_request",
    "ids_match_strict",
    "ok",
    "parse_json_object",
    "validate_initialize_result",
    "validate_tools_list_result",
]
