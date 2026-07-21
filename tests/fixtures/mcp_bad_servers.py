"""Helper scripts used as negative / delayed MCP conformance fixtures (AG3-164).

Invoked as ``python path/to/this/file.py <mode> [run_token]``.

The optional ``run_token`` is embedded in grandchild command lines so
parallel xdist workers can attribute leftovers to a specific test run.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from typing import Any


def _write(obj: object) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def _read() -> dict[str, Any] | None:
    line = sys.stdin.readline()
    if not line:
        return None
    loaded = json.loads(line)
    if not isinstance(loaded, dict):
        msg = "expected object"
        raise TypeError(msg)
    return loaded


def _mcp_loop(
    *,
    delay_s: float = 0.0,
    init_result: dict[str, Any] | None = None,
    tools: list[dict[str, Any]] | None = None,
    omit_jsonrpc: bool = False,
    prepend_garbage: bool = False,
    bool_id: bool = False,
) -> int:
    """Minimal loop with injectable payloads for adversarial tests."""
    default_init = {
        "protocolVersion": "2024-11-05",
        "capabilities": {"tools": {}},
        "serverInfo": {"name": "bad", "version": "0"},
    }
    default_tools: list[dict[str, Any]] = [
        {"name": "ping", "description": "p", "inputSchema": {"type": "object"}}
    ]
    garbage_sent = False
    while True:
        msg = _read()
        if msg is None:
            return 0
        method = msg.get("method")
        mid = msg.get("id")
        if method == "initialize":
            if prepend_garbage and not garbage_sent:
                _write({"garbage": True})
                garbage_sent = True
            if delay_s > 0:
                time.sleep(delay_s)
            resp_id: object = True if bool_id else mid
            body: dict[str, Any] = {
                "id": resp_id,
                "result": init_result or default_init,
            }
            if not omit_jsonrpc:
                body["jsonrpc"] = "2.0"
            _write(body)
        elif method == "notifications/initialized":
            continue
        elif method == "tools/list":
            if delay_s > 0:
                time.sleep(delay_s)
            body = {
                "id": mid,
                "result": {"tools": tools if tools is not None else default_tools},
            }
            if not omit_jsonrpc:
                body["jsonrpc"] = "2.0"
            _write(body)
        elif mid is not None:
            body = {"id": mid, "error": {"code": -32601, "message": "unknown"}}
            if not omit_jsonrpc:
                body["jsonrpc"] = "2.0"
            _write(body)


def _spawn_grandchild(*, token: str, immediate: bool) -> int:
    marker = f"AK3_MCP_RUN_TOKEN={token}"
    subprocess.Popen(  # noqa: S603
        [
            sys.executable,
            "-c",
            f"import time; time.sleep(3600)  # {marker}",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
    )
    if not immediate:
        time.sleep(0.4)
    return 1


def main(argv: list[str]) -> int:
    """Dispatch a negative-path or delayed server mode."""
    mode = argv[1] if len(argv) > 1 else "die"
    token = argv[2] if len(argv) > 2 else "no-token"

    modes: dict[str, Any] = {
        "die": lambda: 1,
        "hang": lambda: _hang(),
        "noise": lambda: _noise(),
        "empty_tools": lambda: _mcp_loop(tools=[]),
        "delay_300": lambda: _mcp_loop(delay_s=0.3),
        "delay_700": lambda: _mcp_loop(delay_s=0.7),
        "delay_notify_then_ok": lambda: _delay_notify(),
        "pseudo_mcp": lambda: _mcp_loop(
            omit_jsonrpc=True,
            init_result={"serverInfo": {"name": "x"}},
            tools=[{"name": "x"}],
        ),
        "no_jsonrpc": lambda: _mcp_loop(omit_jsonrpc=True),
        "unknown_protocol": lambda: _mcp_loop(
            init_result={
                "protocolVersion": "1999-01-01",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "old", "version": "0"},
            }
        ),
        "no_tools_capability": lambda: _mcp_loop(
            init_result={
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "serverInfo": {"name": "n", "version": "0"},
            }
        ),
        "tools_capability_null": lambda: _mcp_loop(
            init_result={
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": None},
                "serverInfo": {"name": "n", "version": "0"},
            }
        ),
        "empty_tool_name": lambda: _mcp_loop(
            tools=[{"name": "", "inputSchema": {"type": "object"}}]
        ),
        "missing_input_schema": lambda: _mcp_loop(tools=[{"name": "x"}]),
        "garbage_then_ok": lambda: _mcp_loop(prepend_garbage=True),
        "bool_id": lambda: _mcp_loop(bool_id=True),
        "bad_notification_params": lambda: _mode_bad_notification_params(),
        "method_wrong_type": lambda: _mode_method_wrong_type(),
        "invalid_utf8_name": lambda: _mode_invalid_utf8_name(),
        "notification_with_result": lambda: _mode_notification_with_result(),
        "oversized_frame": lambda: _mode_oversized_frame(),
        "nan_in_input_schema": lambda: _mode_non_json_constant(
            where="input_schema", constant=float("nan")
        ),
        "infinity_in_initialize": lambda: _mode_non_json_constant(
            where="initialize", constant=float("inf")
        ),
        "neg_infinity_in_initialize": lambda: _mode_non_json_constant(
            where="initialize", constant=float("-inf")
        ),
        "overflow_float_in_schema": lambda: _mode_overflow_float_schema(),
        "duplicate_id": lambda: _mode_duplicate_json_name(field="id"),
        "duplicate_result": lambda: _mode_duplicate_json_name(field="result"),
        "lone_surrogate_name": lambda: _mode_lone_surrogate_name(),
        "bad_instructions_type": lambda: _mode_schema_bad_field(
            where="initialize", field="instructions", value=7
        ),
        "bad_next_cursor_type": lambda: _mode_schema_bad_field(
            where="tools", field="nextCursor", value=7
        ),
        "bad_tool_description_type": lambda: _mode_schema_bad_field(
            where="tool", field="description", value=7
        ),
        "bad_tool_output_schema_type": lambda: _mode_schema_bad_field(
            where="tool", field="outputSchema", value=7
        ),
        "bad_tools_list_changed_type": lambda: _mode_schema_bad_field(
            where="initialize", field="listChanged", value=7
        ),
        # Coercible-under-strict=False: must still fail with strict=True (review-7).
        "coerce_prompts_list_changed_yes": lambda: _mode_schema_bad_field(
            where="initialize", field="prompts_listChanged", value="yes"
        ),
        "coerce_prompts_list_changed_1": lambda: _mode_schema_bad_field(
            where="initialize", field="prompts_listChanged", value=1
        ),
        "coerce_readonly_hint_yes": lambda: _mode_schema_bad_field(
            where="tool", field="annotations_readOnlyHint", value="yes"
        ),
        "coerce_readonly_hint_1": lambda: _mode_schema_bad_field(
            where="tool", field="annotations_readOnlyHint", value=1
        ),
        "spawn_grandchild": lambda: _spawn_grandchild(token=token, immediate=False),
        "spawn_grandchild_immediate": lambda: _spawn_grandchild(
            token=token, immediate=True
        ),
        "echo_env_sentinel": lambda: _mcp_loop(
            tools=[
                {
                    "name": (
                        "env_sentinel_"
                        + ("yes" if os.environ.get("AK3_TEST_SENTINEL_SECRET") else "no")
                        + "_explicit_"
                        + os.environ.get("MCP_EXPLICIT_VAR", "")
                    ),
                    "inputSchema": {"type": "object"},
                }
            ]
        ),
    }
    handler = modes.get(mode)
    if handler is None:
        print(f"unknown mode: {mode}", file=sys.stderr)
        return 2
    return int(handler())


def _hang() -> int:
    while True:
        time.sleep(60)


def _noise() -> int:
    sys.stdout.write("hello I am not MCP\n")
    sys.stdout.flush()
    while True:
        time.sleep(60)


def _mode_bad_notification_params() -> int:
    """Send a notification with non-structured params, then valid handshake."""
    while True:
        msg = _read()
        if msg is None:
            return 0
        method = msg.get("method")
        mid = msg.get("id")
        if method == "initialize":
            _write({"jsonrpc": "2.0", "method": "notice", "params": 7})
            _write(
                {
                    "jsonrpc": "2.0",
                    "id": mid,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "n", "version": "0"},
                    },
                }
            )
        elif method == "notifications/initialized":
            continue
        elif method == "tools/list":
            _write(
                {
                    "jsonrpc": "2.0",
                    "id": mid,
                    "result": {
                        "tools": [{"name": "ping", "inputSchema": {"type": "object"}}]
                    },
                }
            )
        elif mid is not None:
            _write(
                {
                    "jsonrpc": "2.0",
                    "id": mid,
                    "error": {"code": -32601, "message": "unknown"},
                }
            )


def _mode_method_wrong_type() -> int:
    """Initialize response carries method as non-string (must be protocol_error)."""
    while True:
        msg = _read()
        if msg is None:
            return 0
        method = msg.get("method")
        mid = msg.get("id")
        if method == "initialize":
            _write(
                {
                    "jsonrpc": "2.0",
                    "id": mid,
                    "method": 123,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "n", "version": "0"},
                    },
                }
            )
        elif method == "notifications/initialized":
            continue
        elif method == "tools/list":
            _write(
                {
                    "jsonrpc": "2.0",
                    "id": mid,
                    "result": {
                        "tools": [{"name": "ping", "inputSchema": {"type": "object"}}]
                    },
                }
            )


def _mode_invalid_utf8_name() -> int:
    """Write initialize result with invalid UTF-8 in serverInfo.name (raw bytes)."""
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return 0
        msg = json.loads(line.decode("utf-8"))
        method = msg.get("method")
        mid = msg.get("id")
        if method == "initialize":
            # Invalid UTF-8 byte 0xFF inside the JSON string value.
            raw = (
                b'{"jsonrpc":"2.0","id":'
                + str(mid).encode("ascii")
                + b',"result":{"protocolVersion":"2024-11-05",'
                b'"capabilities":{"tools":{}},'
                b'"serverInfo":{"name":"bad\xffname","version":"0"}}}\n'
            )
            sys.stdout.buffer.write(raw)
            sys.stdout.buffer.flush()
        elif method == "notifications/initialized":
            continue
        elif method == "tools/list":
            _write(
                {
                    "jsonrpc": "2.0",
                    "id": mid,
                    "result": {
                        "tools": [{"name": "ping", "inputSchema": {"type": "object"}}]
                    },
                }
            )


def _mode_notification_with_result() -> int:
    while True:
        msg = _read()
        if msg is None:
            return 0
        method = msg.get("method")
        mid = msg.get("id")
        if method == "initialize":
            _write(
                {
                    "jsonrpc": "2.0",
                    "method": "notice",
                    "result": {"x": 1},
                }
            )
            _write(
                {
                    "jsonrpc": "2.0",
                    "id": mid,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "n", "version": "0"},
                    },
                }
            )
        elif method == "tools/list":
            _write(
                {
                    "jsonrpc": "2.0",
                    "id": mid,
                    "result": {
                        "tools": [{"name": "ping", "inputSchema": {"type": "object"}}]
                    },
                }
            )


def _mode_oversized_frame() -> int:
    # One line larger than MAX_FRAME_BYTES (256 KiB).
    sys.stdout.buffer.write(b"x" * (256 * 1024 + 8) + b"\n")
    sys.stdout.buffer.flush()
    while True:
        if not sys.stdin.buffer.readline():
            return 0
        time.sleep(0.1)


def _write_raw_line(text: str) -> None:
    """Write a pre-formed NDJSON line (may contain non-JSON constants)."""
    payload = text if text.endswith("\n") else text + "\n"
    sys.stdout.buffer.write(payload.encode("utf-8"))
    sys.stdout.buffer.flush()


def _mode_non_json_constant(*, where: str, constant: float) -> int:
    """Handshake that embeds NaN/Infinity tokens via json.dumps default.

    CPython's ``json.dumps`` emits non-JSON ``NaN``/``Infinity`` tokens when
    ``allow_nan`` is true (the default). Review-4 requires these to fail closed
    at the conformance wire boundary.
    """
    while True:
        msg = _read()
        if msg is None:
            return 0
        method = msg.get("method")
        mid = msg.get("id")
        if method == "initialize":
            if where == "initialize":
                result = {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}, "x": constant},
                    "serverInfo": {"name": "n", "version": "0"},
                }
            else:
                result = {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "n", "version": "0"},
                }
            # Default dumps: allow_nan=True → literal NaN/Infinity tokens.
            line = json.dumps(
                {"jsonrpc": "2.0", "id": mid, "result": result},
                allow_nan=True,
                separators=(",", ":"),
            )
            _write_raw_line(line)
        elif method == "notifications/initialized":
            continue
        elif method == "tools/list":
            tools = [
                {
                    "name": "ping",
                    "inputSchema": (
                        {"type": "object", "const": constant}
                        if where == "input_schema"
                        else {"type": "object"}
                    ),
                }
            ]
            line = json.dumps(
                {"jsonrpc": "2.0", "id": mid, "result": {"tools": tools}},
                allow_nan=True,
                separators=(",", ":"),
            )
            _write_raw_line(line)


def _mode_overflow_float_schema() -> int:
    """Valid JSON number that overflows to inf in CPython (1e400)."""
    while True:
        msg = _read()
        if msg is None:
            return 0
        method = msg.get("method")
        mid = msg.get("id")
        if method == "initialize":
            _write(
                {
                    "jsonrpc": "2.0",
                    "id": mid,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "n", "version": "0"},
                    },
                }
            )
        elif method == "notifications/initialized":
            continue
        elif method == "tools/list":
            # Raw wire: legal JSON number grammar, illegal as a finite value.
            _write_raw_line(
                f'{{"jsonrpc":"2.0","id":{json.dumps(mid)},"result":{{'
                f'"tools":[{{"name":"ping","inputSchema":{{"type":"object",'
                f'"maximum":1e400}}}}]}}}}'
            )


def _mode_duplicate_json_name(*, field: str) -> int:
    """Emit initialize response with a duplicated JSON object name.

    Default Python decoders last-win; conformance must reject as protocol_error.
    """
    while True:
        msg = _read()
        if msg is None:
            return 0
        method = msg.get("method")
        mid = msg.get("id")
        if method == "initialize":
            result_ok = (
                '{"protocolVersion":"2024-11-05","capabilities":{"tools":{}},'
                '"serverInfo":{"name":"n","version":"0"}}'
            )
            if field == "id":
                # Conflicting ids: second would win under last-wins.
                line = (
                    f'{{"jsonrpc":"2.0","id":{json.dumps(mid)},"id":999,'
                    f'"result":{result_ok}}}'
                )
            else:
                # Duplicate "result" key; second value is incomplete but last-wins.
                line = (
                    f'{{"jsonrpc":"2.0","id":{json.dumps(mid)},'
                    f'"result":{result_ok},"result":{{"protocolVersion":"2024-11-05",'
                    f'"capabilities":{{"tools":{{}}}},'
                    f'"serverInfo":{{"name":"dup","version":"1"}}}}}}'
                )
            _write_raw_line(line)
        elif method == "notifications/initialized":
            continue
        elif method == "tools/list":
            _write(
                {
                    "jsonrpc": "2.0",
                    "id": mid,
                    "result": {
                        "tools": [{"name": "ping", "inputSchema": {"type": "object"}}]
                    },
                }
            )


def _mode_lone_surrogate_name() -> int:
    """serverInfo.name contains an isolated UTF-16 surrogate escape."""
    while True:
        msg = _read()
        if msg is None:
            return 0
        method = msg.get("method")
        mid = msg.get("id")
        if method == "initialize":
            # Lone high surrogate — not a Unicode scalar value.
            _write_raw_line(
                f'{{"jsonrpc":"2.0","id":{json.dumps(mid)},"result":{{'
                f'"protocolVersion":"2024-11-05","capabilities":{{"tools":{{}}}},'
                f'"serverInfo":{{"name":"\\ud800","version":"0"}}}}}}'
            )
        elif method == "notifications/initialized":
            continue
        elif method == "tools/list":
            _write(
                {
                    "jsonrpc": "2.0",
                    "id": mid,
                    "result": {
                        "tools": [{"name": "ping", "inputSchema": {"type": "object"}}]
                    },
                }
            )


def _mode_schema_bad_field(*, where: str, field: str, value: object) -> int:
    """Handshake with known MCP schema fields of the wrong type (review-6 P0-1)."""
    while True:
        msg = _read()
        if msg is None:
            return 0
        method = msg.get("method")
        mid = msg.get("id")
        if method == "initialize":
            init: dict[str, Any] = {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "n", "version": "0"},
            }
            if where == "initialize":
                if field == "instructions":
                    init["instructions"] = value
                elif field == "listChanged":
                    init["capabilities"] = {"tools": {"listChanged": value}}
                elif field == "prompts_listChanged":
                    init["capabilities"] = {
                        "tools": {},
                        "prompts": {"listChanged": value},
                    }
            _write({"jsonrpc": "2.0", "id": mid, "result": init})
        elif method == "notifications/initialized":
            continue
        elif method == "tools/list":
            tool: dict[str, Any] = {
                "name": "ping",
                "inputSchema": {"type": "object"},
            }
            body: dict[str, Any] = {"tools": [tool]}
            if where == "tools" and field == "nextCursor":
                body["nextCursor"] = value
            if where == "tool":
                if field == "annotations_readOnlyHint":
                    tool["annotations"] = {"readOnlyHint": value}
                else:
                    tool[field] = value
            _write({"jsonrpc": "2.0", "id": mid, "result": body})


def _delay_notify() -> int:
    while True:
        msg = _read()
        if msg is None:
            return 0
        method = msg.get("method")
        mid = msg.get("id")
        if method == "initialize":
            time.sleep(0.2)
            _write({"jsonrpc": "2.0", "method": "notifications/message", "params": {}})
            time.sleep(0.2)
            _write(
                {
                    "jsonrpc": "2.0",
                    "id": mid,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "notify-ok", "version": "1"},
                    },
                }
            )
        elif method == "notifications/initialized":
            continue
        elif method == "tools/list":
            _write(
                {
                    "jsonrpc": "2.0",
                    "id": mid,
                    "result": {
                        "tools": [{"name": "ping", "inputSchema": {"type": "object"}}]
                    },
                }
            )
        elif mid is not None:
            _write(
                {
                    "jsonrpc": "2.0",
                    "id": mid,
                    "error": {"code": -32601, "message": "unknown"},
                }
            )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
