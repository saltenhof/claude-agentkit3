"""Public MCP conformance check orchestration (AG3-164).

Wires transport pumps, JSON-RPC/MCP validation, and the process supervisor.
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any

from agentkit.backend.installer.mcp_conformance.process import (
    ProcessControlError,
    ProcessSupervisor,
    build_minimal_env,
    remaining_budget,
    resolve_command,
)
from agentkit.backend.installer.mcp_conformance.protocol import (
    classify_jsonrpc_message,
    fail,
    handle_response_for_request,
    ids_match_strict,
    ok,
    parse_json_object,
)
from agentkit.backend.installer.mcp_conformance.transport import (
    StderrDrainPump,
    StdoutLinePump,
)
from agentkit.backend.installer.mcp_conformance.types import (
    CLIENT_NAME,
    CLIENT_PROTOCOL_VERSION,
    CLIENT_VERSION,
    DEFAULT_TIMEOUT_SECONDS,
    TEARDOWN_RESERVE_SECONDS,
    McpConformanceReason,
    McpConformanceResult,
    McpServerCommand,
    TransportError,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from subprocess import Popen


def check_mcp_conformance(
    server: McpServerCommand,
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> McpConformanceResult:
    """Probe whether ``server`` is a live, MCP-speaking stdio server.

    Success requires process start, strict MCP initialize, and a non-empty
    well-formed tools list. The process tree is always torn down before return.

    Timeout contract: after a successful process launch returns, the full
    controlled budget (:data:`timeout_seconds`) is (re)armed from
    ``time.monotonic()``. A share (:data:`TEARDOWN_RESERVE_SECONDS`, at most
    20%) is reserved for teardown; the handshake uses the remainder.
    ``handshake_deadline`` never exceeds ``full_deadline``.

    The synchronous OS ``Popen`` call itself is not interruptible on all
    platforms. That launch window is **outside** the controlled budget: it
    does not consume handshake or teardown reserve. Launch-failure cleanup
    uses a separate launch-scoped deadline so partial process/job state can
    still be torn down if the OS launch was slow.
    """
    if timeout_seconds <= 0:
        msg = "timeout_seconds must be positive"
        raise ValueError(msg)

    # Launch-scoped deadline only: bounds start-failure waits. Does not define
    # the post-launch controlled handshake/teardown budget (rearmed below).
    launch_deadline = time.monotonic() + timeout_seconds

    resolved = resolve_command(server.command, cwd=server.cwd)
    if resolved is None:
        return fail(
            McpConformanceReason.COMMAND_NOT_FOUND,
            f"MCP command not found: {server.command!r} (cwd={server.cwd!r}).",
        )

    argv = [resolved, *list(server.args)]
    child_env = build_minimal_env(server.env)
    cwd = str(server.cwd) if server.cwd is not None else None
    cmd_label = " ".join(argv)

    supervisor = ProcessSupervisor()
    stdout_pump: StdoutLinePump | None = None
    stderr_pump: StderrDrainPump | None = None
    outcome: McpConformanceResult | None = None
    # Post-launch controlled deadlines; set only after successful start so a
    # slow Popen cannot burn handshake/teardown reserve.
    full_deadline: float | None = None
    try:
        try:
            supervisor.start(
                argv, env=child_env, cwd=cwd, deadline=launch_deadline
            )
        except ProcessControlError as exc:
            outcome = fail(
                McpConformanceReason.PROCESS_CONTROL_ERROR,
                f"MCP process control failed for {cmd_label}: {exc.detail}",
            )
        except OSError as exc:
            outcome = fail(
                McpConformanceReason.COMMAND_NOT_FOUND,
                f"Failed to start MCP command {argv[0]!r}: {exc}.",
            )
        else:
            # FK-50: re-arm controlled budget after Popen returns.
            full_deadline, handshake_deadline = split_probe_deadlines(
                timeout_seconds
            )
            proc = supervisor.proc
            assert proc is not None
            assert proc.stdout is not None
            assert proc.stderr is not None

            stdout_pump = StdoutLinePump(proc.stdout)
            stderr_pump = StderrDrainPump(proc.stderr)
            stdout_pump.start()
            stderr_pump.start()

            try:
                outcome = _handshake(
                    supervisor,
                    stdout_pump=stdout_pump,
                    stderr_pump=stderr_pump,
                    deadline=handshake_deadline,
                    cmd_label=cmd_label,
                )
            except TransportError as exc:
                outcome = fail(exc.reason, exc.detail)
            except ProcessControlError as exc:
                outcome = fail(
                    McpConformanceReason.PROCESS_CONTROL_ERROR,
                    f"MCP process control failed for {cmd_label}: {exc.detail}",
                )
            except Exception as exc:  # noqa: BLE001 — boundary
                outcome = fail(
                    McpConformanceReason.PROTOCOL_ERROR,
                    f"Internal MCP conformance fault for {cmd_label}: {exc}.",
                )
    finally:
        teardown_deadline = (
            full_deadline if full_deadline is not None else launch_deadline
        )
        try:
            supervisor.shutdown(
                deadline=teardown_deadline,
                graceful=bool(outcome is not None and outcome.ok),
            )
        except ProcessControlError as exc:
            # FK-50: non-terminable control plane is always the public reason,
            # even when a prior handshake error already exists.
            outcome = fail(
                McpConformanceReason.PROCESS_CONTROL_ERROR,
                f"MCP process control failed during teardown for {cmd_label}: "
                f"{exc.detail}",
            )
        join_left = remaining_budget(teardown_deadline)
        if stdout_pump is not None and join_left > 0:
            half = join_left / 2
            stdout_pump.join(timeout=half)
            join_left = remaining_budget(teardown_deadline)
        if stderr_pump is not None and join_left > 0:
            stderr_pump.join(timeout=join_left)

    if outcome is None:
        return fail(
            McpConformanceReason.PROTOCOL_ERROR,
            f"MCP conformance produced no outcome for {cmd_label}.",
        )
    return outcome


def split_probe_deadlines(
    timeout_seconds: float, *, now: float | None = None
) -> tuple[float, float]:
    """Split total probe budget into full and handshake deadlines.

    Invariant: ``handshake_deadline <= full_deadline``. Teardown reserve is
    ``min(TEARDOWN_RESERVE_SECONDS, 20% of timeout)`` — never more than the
    caller budget, never inventing extra wall time for the handshake.
    """
    if timeout_seconds <= 0:
        msg = "timeout_seconds must be positive"
        raise ValueError(msg)
    clock = time.monotonic() if now is None else now
    full_deadline = clock + timeout_seconds
    teardown_reserve = min(TEARDOWN_RESERVE_SECONDS, timeout_seconds * 0.2)
    handshake_deadline = full_deadline - teardown_reserve
    # Clamp only downward so handshake never exceeds the total budget.
    if handshake_deadline > full_deadline:
        handshake_deadline = full_deadline
    return full_deadline, handshake_deadline


def server_command_from_mcp_entry(entry: Mapping[str, Any]) -> McpServerCommand:
    """Build a :class:`McpServerCommand` from a ``.mcp.json`` server entry."""
    command = entry.get("command")
    if not isinstance(command, str) or not command.strip():
        msg = "mcp server entry requires a non-empty string 'command'"
        raise ValueError(msg)
    raw_args = entry.get("args", [])
    if raw_args is None:
        args: list[str] = []
    elif isinstance(raw_args, list) and all(isinstance(a, str) for a in raw_args):
        args = list(raw_args)
    else:
        msg = "mcp server entry 'args' must be a list of strings"
        raise ValueError(msg)
    raw_env = entry.get("env")
    env: dict[str, str] | None
    if raw_env is None:
        env = None
    elif isinstance(raw_env, dict) and all(
        isinstance(k, str) and isinstance(v, str) for k, v in raw_env.items()
    ):
        env = dict(raw_env)
    else:
        msg = "mcp server entry 'env' must be a string-to-string mapping"
        raise ValueError(msg)
    return McpServerCommand(command=command, args=args, env=env)


def _handshake(
    supervisor: ProcessSupervisor,
    *,
    stdout_pump: StdoutLinePump,
    stderr_pump: StderrDrainPump,
    deadline: float,
    cmd_label: str,
) -> McpConformanceResult:
    proc = supervisor.proc
    assert proc is not None

    if remaining_budget(deadline) <= 0:
        return fail(
            McpConformanceReason.TIMEOUT,
            f"MCP deadline exhausted before handshake for: {cmd_label}.",
        )

    settle = min(0.05, remaining_budget(deadline) / 4)
    if settle > 0:
        time.sleep(settle)
    supervisor.refresh_tree()
    if proc.poll() is not None:
        return _exited(proc, stderr_pump, cmd_label=cmd_label, when="immediately")

    _write_message(
        proc,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": CLIENT_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": CLIENT_NAME, "version": CLIENT_VERSION},
            },
        },
    )

    init_resp = _read_response(
        supervisor,
        stdout_pump=stdout_pump,
        stderr_pump=stderr_pump,
        request_id=1,
        deadline=deadline,
        cmd_label=cmd_label,
    )
    if not init_resp.ok:
        return init_resp

    _write_message(
        proc,
        {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
    )
    _write_message(
        proc,
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    )

    tools_resp = _read_response(
        supervisor,
        stdout_pump=stdout_pump,
        stderr_pump=stderr_pump,
        request_id=2,
        deadline=deadline,
        cmd_label=cmd_label,
    )
    if not tools_resp.ok:
        return tools_resp

    if not tools_resp.tool_names:
        return fail(
            McpConformanceReason.TOOLS_LIST_EMPTY,
            f"MCP tools list returned no tools for command: {cmd_label}.",
        )

    return ok(
        f"MCP conformance OK for command: {cmd_label}; "
        f"tools={list(tools_resp.tool_names)}.",
        tool_names=tools_resp.tool_names,
    )


def _write_message(proc: Popen[bytes], message: dict[str, Any]) -> None:
    if proc.stdin is None:
        raise TransportError(
            McpConformanceReason.PROTOCOL_ERROR,
            "MCP process stdin is not available.",
        )
    if proc.poll() is not None:
        raise TransportError(
            McpConformanceReason.PROCESS_EXITED,
            f"MCP process exited before write (exit={proc.returncode}).",
        )
    try:
        payload = (json.dumps(message, separators=(",", ":")) + "\n").encode("utf-8")
        proc.stdin.write(payload)
        proc.stdin.flush()
    except (BrokenPipeError, OSError, ValueError) as exc:
        raise TransportError(
            McpConformanceReason.PROCESS_EXITED,
            f"MCP process pipe broken during write: {exc}.",
        ) from exc


def _read_response(
    supervisor: ProcessSupervisor,
    *,
    stdout_pump: StdoutLinePump,
    stderr_pump: StderrDrainPump,
    request_id: int,
    deadline: float,
    cmd_label: str,
) -> McpConformanceResult:
    proc = supervisor.proc
    assert proc is not None

    while True:
        remaining = remaining_budget(deadline)
        if remaining <= 0:
            return fail(
                McpConformanceReason.TIMEOUT,
                f"MCP handshake timed out waiting for response id={request_id} "
                f"from command: {cmd_label}.",
            )

        supervisor.refresh_tree()

        if proc.poll() is not None:
            supervisor.refresh_tree()
            return _exited(
                proc, stderr_pump, cmd_label=cmd_label, when="during handshake"
            )

        try:
            line = stdout_pump.readline(timeout=min(remaining, 0.5))
        except TransportError as exc:
            return fail(exc.reason, exc.detail)

        if line == "":
            continue
        if line is None:
            supervisor.refresh_tree()
            return _exited(proc, stderr_pump, cmd_label=cmd_label, when="stdout EOF")
        if not line.strip():
            continue

        parsed = parse_json_object(line, cmd_label=cmd_label)
        if isinstance(parsed, McpConformanceResult):
            return parsed

        classified = classify_jsonrpc_message(parsed, cmd_label=cmd_label)
        if isinstance(classified, McpConformanceResult):
            return classified

        if classified.kind == "notification":
            continue

        if classified.kind == "request":
            return fail(
                McpConformanceReason.PROTOCOL_ERROR,
                f"MCP server sent unexpected JSON-RPC request during handshake "
                f"for command: {cmd_label}.",
            )

        if not ids_match_strict(expected=request_id, actual=classified.msg_id):
            return fail(
                McpConformanceReason.PROTOCOL_ERROR,
                f"MCP response id {classified.msg_id!r} does not strictly match "
                f"expected integer id={request_id} for command: {cmd_label}.",
            )

        return handle_response_for_request(
            classified.message, request_id=request_id, cmd_label=cmd_label
        )


def _exited(
    proc: Popen[bytes],
    stderr_pump: StderrDrainPump,
    *,
    cmd_label: str,
    when: str,
) -> McpConformanceResult:
    tail = stderr_pump.retained_text()
    return fail(
        McpConformanceReason.PROCESS_EXITED,
        f"MCP process exited {when} (exit={proc.returncode}) for command: {cmd_label}."
        + (f" stderr: {tail}" if tail else ""),
    )


__all__ = ["check_mcp_conformance", "server_command_from_mcp_entry"]
