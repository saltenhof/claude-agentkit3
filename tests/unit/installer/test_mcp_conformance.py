"""Unit tests for the generic MCP conformance check (AG3-164 rework 2)."""

from __future__ import annotations

import contextlib
import os
import sys
import time
import uuid
from pathlib import Path

import psutil
import pytest

from agentkit.backend.installer.checkpoint_engine.reasons import (
    REASON_MCP_COMMAND_NOT_FOUND,
    REASON_MCP_PROCESS_CONTROL_ERROR,
    REASON_MCP_PROCESS_EXITED,
    REASON_MCP_PROTOCOL_ERROR,
    REASON_MCP_TIMEOUT,
    REASON_MCP_TOOLS_LIST_EMPTY,
)
from agentkit.backend.installer.mcp_conformance import (
    McpConformanceReason,
    McpServerCommand,
    check_mcp_conformance,
)
from agentkit.backend.installer.mcp_conformance.protocol import (
    classify_jsonrpc_message,
    ids_match_strict,
    validate_initialize_result,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_MINIMAL_SERVER = _REPO_ROOT / "tests" / "fixtures" / "minimal_mcp_server.py"
_BAD_SERVERS = _REPO_ROOT / "tests" / "fixtures" / "mcp_bad_servers.py"


def _token() -> str:
    return f"t{uuid.uuid4().hex}"


def _cmd(*args: str, env: dict[str, str] | None = None) -> McpServerCommand:
    return McpServerCommand(command=sys.executable, args=list(args), env=env)


def _assert_no_token_leftovers(token: str) -> None:
    """xdist-safe: only processes carrying this run token are leak candidates."""
    marker = f"AK3_MCP_RUN_TOKEN={token}"
    time.sleep(0.15)
    for proc in psutil.process_iter(["cmdline", "pid"]):
        try:
            cmd = proc.info.get("cmdline") or []
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        joined = " ".join(cmd)
        if marker not in joined:
            continue
        if proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE:
            pytest.fail(f"leftover process for token={token} pid={proc.pid}: {joined}")


def test_reason_ssot_matches_checkpoint_reasons() -> None:
    assert McpConformanceReason.COMMAND_NOT_FOUND == REASON_MCP_COMMAND_NOT_FOUND
    assert McpConformanceReason.PROCESS_EXITED == REASON_MCP_PROCESS_EXITED
    assert McpConformanceReason.TIMEOUT == REASON_MCP_TIMEOUT
    assert McpConformanceReason.PROTOCOL_ERROR == REASON_MCP_PROTOCOL_ERROR
    assert McpConformanceReason.TOOLS_LIST_EMPTY == REASON_MCP_TOOLS_LIST_EMPTY
    assert (
        McpConformanceReason.PROCESS_CONTROL_ERROR == REASON_MCP_PROCESS_CONTROL_ERROR
    )


def test_ids_match_strict_rejects_boolean() -> None:
    """P0-1: True == 1 must not accept boolean JSON-RPC ids."""
    assert ids_match_strict(expected=1, actual=1) is True
    assert ids_match_strict(expected=1, actual=True) is False
    assert ids_match_strict(expected=1, actual="1") is False


def test_classify_rejects_garbage_without_jsonrpc() -> None:
    from agentkit.backend.installer.mcp_conformance.types import McpConformanceResult

    result = classify_jsonrpc_message({"garbage": True}, cmd_label="t")
    assert isinstance(result, McpConformanceResult)
    assert result.ok is False
    assert result.reason is McpConformanceReason.PROTOCOL_ERROR


def test_tools_capability_null_rejected_in_validator() -> None:
    result = validate_initialize_result(
        {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": None},
            "serverInfo": {"name": "n", "version": "0"},
        },
        cmd_label="t",
    )
    assert result.ok is False
    assert result.reason is McpConformanceReason.PROTOCOL_ERROR


def test_conformance_command_not_found() -> None:
    result = check_mcp_conformance(
        McpServerCommand(command="agentkit-are-mcp-definitely-missing-xyz"),
        timeout_seconds=2.0,
    )
    assert result.ok is False
    assert result.reason is McpConformanceReason.COMMAND_NOT_FOUND


def test_conformance_process_exits_immediately() -> None:
    token = _token()
    result = check_mcp_conformance(
        _cmd(str(_BAD_SERVERS), "die", token),
        timeout_seconds=5.0,
    )
    assert result.ok is False
    assert result.reason is McpConformanceReason.PROCESS_EXITED
    _assert_no_token_leftovers(token)


def test_conformance_non_mcp_protocol() -> None:
    token = _token()
    result = check_mcp_conformance(
        _cmd(str(_BAD_SERVERS), "noise", token),
        timeout_seconds=3.0,
    )
    assert result.ok is False
    assert result.reason is McpConformanceReason.PROTOCOL_ERROR
    _assert_no_token_leftovers(token)


def test_conformance_timeout_hanging_process_is_cleaned_up() -> None:
    token = _token()
    result = check_mcp_conformance(
        _cmd(str(_BAD_SERVERS), "hang", token),
        timeout_seconds=1.0,
    )
    assert result.ok is False
    assert result.reason is McpConformanceReason.TIMEOUT
    _assert_no_token_leftovers(token)


def test_conformance_empty_tools_list() -> None:
    token = _token()
    result = check_mcp_conformance(
        _cmd(str(_BAD_SERVERS), "empty_tools", token),
        timeout_seconds=5.0,
    )
    assert result.ok is False
    assert result.reason is McpConformanceReason.TOOLS_LIST_EMPTY
    _assert_no_token_leftovers(token)


@pytest.mark.parametrize(
    "mode",
    [
        "pseudo_mcp",
        "no_jsonrpc",
        "unknown_protocol",
        "no_tools_capability",
        "tools_capability_null",
        "empty_tool_name",
        "missing_input_schema",
        "garbage_then_ok",
        "bool_id",
        "bad_notification_params",
        "method_wrong_type",
        "invalid_utf8_name",
        "notification_with_result",
        "oversized_frame",
        "nan_in_input_schema",
        "infinity_in_initialize",
        "neg_infinity_in_initialize",
        "overflow_float_in_schema",
        "duplicate_id",
        "duplicate_result",
        "lone_surrogate_name",
        "bad_instructions_type",
        "bad_next_cursor_type",
        "bad_tool_description_type",
        "bad_tool_output_schema_type",
        "bad_tools_list_changed_type",
        "coerce_prompts_list_changed_yes",
        "coerce_prompts_list_changed_1",
        "coerce_readonly_hint_yes",
        "coerce_readonly_hint_1",
    ],
)
def test_conformance_rejects_structurally_invalid_mcp(mode: str) -> None:
    """Adversarial pseudo-MCP wire/schema cases (reviews 3–7)."""
    token = _token()
    result = check_mcp_conformance(
        _cmd(str(_BAD_SERVERS), mode, token),
        timeout_seconds=5.0,
    )
    assert result.ok is False, (mode, result.detail)
    assert result.reason is McpConformanceReason.PROTOCOL_ERROR
    _assert_no_token_leftovers(token)


def test_parse_json_object_rejects_nan_infinity_tokens() -> None:
    """Unit: parse_constant rejects non-JSON NaN/Infinity tokens."""
    from agentkit.backend.installer.mcp_conformance.protocol import parse_json_object
    from agentkit.backend.installer.mcp_conformance.types import McpConformanceResult

    for payload in (
        '{"jsonrpc":"2.0","id":1,"result":{"x":NaN}}',
        '{"jsonrpc":"2.0","id":1,"result":{"x":Infinity}}',
        '{"jsonrpc":"2.0","id":1,"result":{"x":-Infinity}}',
        '{"jsonrpc":"2.0","id":1,"result":{"x":1e400}}',
    ):
        result = parse_json_object(payload, cmd_label="t")
        assert isinstance(result, McpConformanceResult)
        assert result.ok is False
        assert result.reason is McpConformanceReason.PROTOCOL_ERROR


def test_parse_json_object_rejects_mid_depth_nesting_as_protocol_error() -> None:
    """Review-10: mid-depth nesting is protocol_error, not an internal fault."""
    from agentkit.backend.installer.mcp_conformance.protocol import parse_json_object
    from agentkit.backend.installer.mcp_conformance.types import McpConformanceResult

    depth = 700
    nested = "[" * depth + "0" + "]" * depth
    payload = f'{{"jsonrpc":"2.0","id":1,"result":{{"x":{nested}}}}}'
    result = parse_json_object(payload, cmd_label="t")
    assert isinstance(result, McpConformanceResult)
    assert result.ok is False
    assert result.reason is McpConformanceReason.PROTOCOL_ERROR
    assert "nesting" in (result.detail or "").lower()


def test_sdk_schema_rejects_wrong_typed_known_fields() -> None:
    """P0-1 unit: mcp.types oracle rejects known fields with wrong types."""
    from agentkit.backend.installer.mcp_conformance.protocol import (
        validate_initialize_result,
        validate_tools_list_result,
    )

    base_init = {
        "protocolVersion": "2024-11-05",
        "capabilities": {"tools": {}},
        "serverInfo": {"name": "n", "version": "0"},
    }
    r = validate_initialize_result({**base_init, "instructions": 7}, cmd_label="t")
    assert r.ok is False
    assert r.reason is McpConformanceReason.PROTOCOL_ERROR

    r = validate_initialize_result(
        {
            **base_init,
            "capabilities": {"tools": {"listChanged": 7}},
        },
        cmd_label="t",
    )
    assert r.ok is False
    assert r.reason is McpConformanceReason.PROTOCOL_ERROR

    # Coercible under strict=False — must fail with strict=True (review-7).
    for coerced in ("yes", 1, "true", "on", 0, "false"):
        r = validate_initialize_result(
            {
                **base_init,
                "capabilities": {
                    "tools": {},
                    "prompts": {"listChanged": coerced},
                },
            },
            cmd_label="t",
        )
        assert r.ok is False, coerced
        assert r.reason is McpConformanceReason.PROTOCOL_ERROR

    r = validate_tools_list_result(
        {
            "tools": [{"name": "ping", "inputSchema": {"type": "object"}}],
            "nextCursor": 7,
        },
        cmd_label="t",
    )
    assert r.ok is False
    assert r.reason is McpConformanceReason.PROTOCOL_ERROR

    for tool_extra in (
        {"description": 7},
        {"outputSchema": 7},
        {"annotations": {"readOnlyHint": "yes"}},
        {"annotations": {"readOnlyHint": 1}},
    ):
        r = validate_tools_list_result(
            {
                "tools": [
                    {
                        "name": "ping",
                        "inputSchema": {"type": "object"},
                        **tool_extra,
                    }
                ]
            },
            cmd_label="t",
        )
        assert r.ok is False
        assert r.reason is McpConformanceReason.PROTOCOL_ERROR


def test_parse_json_object_rejects_duplicate_names_and_lone_surrogates() -> None:
    """P1-2: duplicate keys and lone surrogates are protocol_error."""
    from agentkit.backend.installer.mcp_conformance.protocol import parse_json_object
    from agentkit.backend.installer.mcp_conformance.types import McpConformanceResult

    for payload in (
        '{"jsonrpc":"2.0","id":1,"id":2,"result":{}}',
        '{"jsonrpc":"2.0","id":1,"result":{"a":1},"result":{"a":2}}',
        '{"jsonrpc":"2.0","id":1,"result":{"nested":{"k":1,"k":2}}}',
        r'{"jsonrpc":"2.0","id":1,"result":{"name":"\ud800"}}',
        r'{"jsonrpc":"2.0","id":1,"result":{"\ud800":"x"}}',
    ):
        result = parse_json_object(payload, cmd_label="t")
        assert isinstance(result, McpConformanceResult), payload
        assert result.ok is False, payload
        assert result.reason is McpConformanceReason.PROTOCOL_ERROR

    # Valid surrogate *pair* must still decode to one scalar and pass.
    ok_pair = parse_json_object(
        r'{"jsonrpc":"2.0","id":1,"result":{"name":"\ud83d\ude00"}}',
        cmd_label="t",
    )
    assert isinstance(ok_pair, dict)
    assert ok_pair["result"]["name"] == "\U0001f600"


@pytest.mark.parametrize("delay_mode", ["delay_300", "delay_700"])
def test_conformance_accepts_slow_but_valid_responses(delay_mode: str) -> None:
    token = _token()
    result = check_mcp_conformance(
        _cmd(str(_BAD_SERVERS), delay_mode, token),
        timeout_seconds=5.0,
    )
    assert result.ok is True, result.detail
    assert "ping" in result.tool_names
    _assert_no_token_leftovers(token)


def test_conformance_accepts_notifications_before_response() -> None:
    token = _token()
    result = check_mcp_conformance(
        _cmd(str(_BAD_SERVERS), "delay_notify_then_ok", token),
        timeout_seconds=5.0,
    )
    assert result.ok is True, result.detail
    _assert_no_token_leftovers(token)


def test_conformance_real_minimal_mcp_server() -> None:
    result = check_mcp_conformance(
        _cmd(str(_MINIMAL_SERVER)),
        timeout_seconds=10.0,
    )
    assert result.ok is True
    assert result.reason is None
    assert "ping" in result.tool_names


def test_conformance_kills_grandchild_slow_parent() -> None:
    token = _token()
    result = check_mcp_conformance(
        _cmd(str(_BAD_SERVERS), "spawn_grandchild", token),
        timeout_seconds=5.0,
    )
    assert result.ok is False
    assert result.reason is McpConformanceReason.PROCESS_EXITED
    _assert_no_token_leftovers(token)


def test_conformance_kills_grandchild_immediate_parent_exit() -> None:
    """P0-2: parent exits immediately after spawning grandchild."""
    token = _token()
    result = check_mcp_conformance(
        _cmd(str(_BAD_SERVERS), "spawn_grandchild_immediate", token),
        timeout_seconds=5.0,
    )
    assert result.ok is False
    assert result.reason is McpConformanceReason.PROCESS_EXITED
    _assert_no_token_leftovers(token)


def test_conformance_does_not_inherit_installer_secrets() -> None:
    sentinel_key = "AK3_TEST_SENTINEL_SECRET"
    os.environ[sentinel_key] = "super-secret-value-not-for-mcp"
    try:
        result = check_mcp_conformance(
            _cmd(
                str(_BAD_SERVERS),
                "echo_env_sentinel",
                _token(),
                env={"MCP_EXPLICIT_VAR": "visible"},
            ),
            timeout_seconds=5.0,
        )
        assert result.ok is True, result.detail
        assert result.tool_names == ("env_sentinel_no_explicit_visible",)
    finally:
        os.environ.pop(sentinel_key, None)


def test_protocol_rejects_notification_params_scalar() -> None:
    from agentkit.backend.installer.mcp_conformance.types import McpConformanceResult

    result = classify_jsonrpc_message(
        {"jsonrpc": "2.0", "method": "notice", "params": 7},
        cmd_label="t",
    )
    assert isinstance(result, McpConformanceResult)
    assert result.ok is False


def test_protocol_rejects_method_wrong_type_on_response() -> None:
    from agentkit.backend.installer.mcp_conformance.types import McpConformanceResult

    result = classify_jsonrpc_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": 123,
            "result": {"x": 1},
        },
        cmd_label="t",
    )
    assert isinstance(result, McpConformanceResult)
    assert result.ok is False


def test_stdout_oversize_frame_is_protocol_error() -> None:
    """P1-2: transport frame limit surfaces as protocol_error."""
    import io
    import time

    from agentkit.backend.installer.mcp_conformance.transport import StdoutLinePump
    from agentkit.backend.installer.mcp_conformance.types import (
        MAX_FRAME_BYTES,
        TransportError,
    )

    oversize = b"y" * (MAX_FRAME_BYTES + 16) + b"\n"
    pump = StdoutLinePump(io.BytesIO(oversize))
    pump.start()
    time.sleep(0.05)
    err: TransportError | None = None
    for _ in range(30):
        try:
            line = pump.readline(timeout=0.1)
            if line is None:
                break
        except TransportError as te:
            err = te
            break
    assert err is not None
    assert err.reason is McpConformanceReason.PROTOCOL_ERROR
    pump.join(timeout=0.5)


def test_stdout_invalid_utf8_is_protocol_error() -> None:
    """P0-1: strict UTF-8 decode — no U+FFFD repair."""
    import io
    import time

    from agentkit.backend.installer.mcp_conformance.transport import StdoutLinePump
    from agentkit.backend.installer.mcp_conformance.types import TransportError

    pump = StdoutLinePump(io.BytesIO(b'{"jsonrpc":"2.0","id":1,"result":{"x":"\xff"}}\n'))
    pump.start()
    time.sleep(0.05)
    err: TransportError | None = None
    for _ in range(30):
        try:
            line = pump.readline(timeout=0.1)
            if line is None:
                break
        except TransportError as te:
            err = te
            break
    assert err is not None
    assert err.reason is McpConformanceReason.PROTOCOL_ERROR
    pump.join(timeout=0.5)


def test_stderr_tail_keeps_last_bytes() -> None:
    """P2-1: large single stderr write retains trailing detail bytes."""
    import io
    import time

    from agentkit.backend.installer.mcp_conformance.transport import StderrDrainPump
    from agentkit.backend.installer.mcp_conformance.types import STDERR_DETAIL_CHARS

    payload = b"A" * 3000 + b"TAILMARKER"
    stream = io.BytesIO(payload)
    pump = StderrDrainPump(stream)
    pump.start()
    time.sleep(0.05)
    pump.join(timeout=1.0)
    text = pump.retained_text()
    assert "TAILMARKER" in text
    assert len(text) <= STDERR_DETAIL_CHARS + 20


def test_job_create_failure_is_fail_closed() -> None:
    """P0-2/P1-2: Win32 job create failure is named process_control_error.

    Boundary fake: inject a failing job factory. Real CreateJobObject cannot
    be forced reliably without OS-level fault injection.
    """
    from agentkit.backend.installer.mcp_conformance.process import (
        ProcessControlError,
        ProcessSupervisor,
    )

    if sys.platform != "win32":
        pytest.skip("Windows job-object path only")

    supervisor = ProcessSupervisor()

    def _boom() -> int:
        raise ProcessControlError("injected job create failure")

    supervisor._job_factory = _boom  # noqa: SLF001 — test boundary
    with pytest.raises(ProcessControlError, match="injected job create"):
        supervisor.start([sys.executable, "-c", "pass"], env={}, cwd=None)
    # No leaked job handle (state reset).
    assert supervisor._job is None  # noqa: SLF001


def test_job_assign_failure_is_fail_closed() -> None:
    """Boundary fake: inject AssignProcessToJobObject failure."""
    from agentkit.backend.installer.mcp_conformance.process import (
        ProcessControlError,
        ProcessSupervisor,
    )

    if sys.platform != "win32":
        pytest.skip("Windows job-object path only")

    supervisor = ProcessSupervisor()

    def _fail_assign(job: int, proc: object) -> None:
        raise ProcessControlError("injected assign failure")

    supervisor._assign_hook = _fail_assign  # noqa: SLF001
    with pytest.raises(ProcessControlError, match="injected assign"):
        supervisor.start(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            env={},
            cwd=None,
        )
    assert supervisor.proc is None
    assert supervisor._job is None  # noqa: SLF001


def test_launch_failure_does_not_leak_job_handles(tmp_path: Path) -> None:
    """P1-1: repeated start failures against a non-executable must not grow handles."""
    if sys.platform != "win32":
        pytest.skip("num_handles is Windows-specific")
    import psutil as ps

    # A real file that is not executable as a process image.
    junk = tmp_path / "not-an-exe.txt"
    junk.write_text("x", encoding="utf-8")
    me = ps.Process()
    before = me.num_handles()
    for _ in range(30):
        result = check_mcp_conformance(
            McpServerCommand(command=str(junk)),
            timeout_seconds=2.0,
        )
        assert result.ok is False
        assert result.reason in {
            McpConformanceReason.COMMAND_NOT_FOUND,
            McpConformanceReason.PROCESS_CONTROL_ERROR,
            McpConformanceReason.PROCESS_EXITED,
        }
    after = me.num_handles()
    # Allow small OS noise; must not grow ~1 handle per iteration.
    assert after - before < 15, (before, after)


def test_stdout_pending_queue_overflow_is_protocol_error() -> None:
    """P1-2: pending-message capacity overflow is a transport protocol_error."""
    import io
    import time

    from agentkit.backend.installer.mcp_conformance.transport import StdoutLinePump
    from agentkit.backend.installer.mcp_conformance.types import (
        MAX_PENDING_STDOUT_MESSAGES,
        TransportError,
    )

    # Flood the bounded queue with more lines than capacity allows.
    flood = b"".join(
        f'{{"jsonrpc":"2.0","method":"n{i}","params":{{}}}}\n'.encode()
        for i in range(MAX_PENDING_STDOUT_MESSAGES + 32)
    )
    pump = StdoutLinePump(io.BytesIO(flood))
    # Do not drain the queue while the pump fills it — force Full.
    pump.start()
    time.sleep(0.2)
    err: TransportError | None = None
    for _ in range(80):
        try:
            line = pump.readline(timeout=0.05)
            if line is None:
                break
        except TransportError as te:
            err = te
            break
    assert err is not None
    assert err.reason is McpConformanceReason.PROTOCOL_ERROR
    assert "capacity" in err.detail.lower() or "exceeded" in err.detail.lower()
    pump.join(timeout=0.5)


def test_identity_create_time_mismatch_skips_kill() -> None:
    """P0-2/P1-2: kill path must not act on PID-reused identities."""
    from agentkit.backend.installer.mcp_conformance.process import (
        _kill_tracked,
        _open_if_identity_matches,
    )
    from agentkit.backend.installer.mcp_conformance.types import ProcessIdentity

    # Live process with a deliberately wrong create_time must not match.
    me = psutil.Process()
    fake = ProcessIdentity(pid=me.pid, create_time=me.create_time() - 9999.0)
    assert _open_if_identity_matches(fake) is None

    # _kill_tracked must leave the live process alone.
    deadline = time.monotonic() + 1.0
    _kill_tracked({fake}, deadline=deadline)
    assert me.is_running()


def test_remaining_budget_and_exhausted_join_are_non_negative() -> None:
    """P0-2: waits use remaining budget only; exhausted deadline joins are no-ops."""
    import io

    from agentkit.backend.installer.mcp_conformance.process import remaining_budget
    from agentkit.backend.installer.mcp_conformance.transport import StdoutLinePump

    assert remaining_budget(time.monotonic() - 1.0) == 0.0
    pump = StdoutLinePump(io.BytesIO(b""))
    # join with non-positive timeout must not block (thread never started).
    pump.join(timeout=0.0)
    pump.join(timeout=-1.0)


def test_split_probe_deadlines_never_extends_handshake() -> None:
    """P1-2: handshake_deadline <= full_deadline for tiny/normal/default budgets."""
    from agentkit.backend.installer.mcp_conformance.check import split_probe_deadlines
    from agentkit.backend.installer.mcp_conformance.types import (
        DEFAULT_TIMEOUT_SECONDS,
        TEARDOWN_RESERVE_SECONDS,
    )

    now = 1000.0
    for timeout in (0.01, 0.5, 1.0, DEFAULT_TIMEOUT_SECONDS, 60.0):
        full, handshake = split_probe_deadlines(timeout, now=now)
        assert full == pytest.approx(now + timeout)
        assert handshake <= full + 1e-12
        reserve = full - handshake
        assert reserve == pytest.approx(min(TEARDOWN_RESERVE_SECONDS, timeout * 0.2))
        # Must not invent time beyond the caller budget.
        assert handshake <= now + timeout + 1e-12


def test_small_timeout_does_not_exceed_total_budget() -> None:
    """P1-2: controlled wall time after return stays near the declared budget.

    Synchronous OS Popen is outside the budget; hang mode starts quickly so
    residual overrun is teardown/join only.
    """
    token = _token()
    timeout = 0.5
    t0 = time.monotonic()
    result = check_mcp_conformance(
        _cmd(str(_BAD_SERVERS), "hang", token),
        timeout_seconds=timeout,
    )
    elapsed = time.monotonic() - t0
    assert result.ok is False
    assert result.reason is McpConformanceReason.TIMEOUT
    # Generous slack for scheduling; must not be multi-second overshoot from
    # inventing handshake time beyond full_deadline.
    assert elapsed < timeout + 2.5, elapsed
    _assert_no_token_leftovers(token)


def test_resume_failure_is_public_process_control_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """P1-1: Resume boundary failure maps to mcp_process_control_error."""
    if sys.platform != "win32":
        pytest.skip("Windows resume path only")

    from agentkit.backend.installer.mcp_conformance import process as process_mod
    from agentkit.backend.installer.mcp_conformance.process import ProcessControlError

    def _boom_resume(pid: int) -> None:
        raise ProcessControlError("injected resume failure")

    monkeypatch.setattr(process_mod, "_resume_suspended_process", _boom_resume)
    result = check_mcp_conformance(
        _cmd(str(_MINIMAL_SERVER)),
        timeout_seconds=5.0,
    )
    assert result.ok is False
    assert result.reason is McpConformanceReason.PROCESS_CONTROL_ERROR
    assert "resume" in result.detail.lower()


def test_terminate_failure_is_public_process_control_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P1-1: TerminateJobObject failure overrides even a prior green path."""
    if sys.platform != "win32":
        pytest.skip("Windows job terminate path only")

    from agentkit.backend.installer.mcp_conformance import process as process_mod
    from agentkit.backend.installer.mcp_conformance.process import ProcessControlError

    def _boom_term(job: int, *, deadline: float) -> None:
        raise ProcessControlError("injected terminate failure")

    monkeypatch.setattr(process_mod, "_terminate_windows_job", _boom_term)
    result = check_mcp_conformance(
        _cmd(str(_MINIMAL_SERVER)),
        timeout_seconds=10.0,
    )
    assert result.ok is False
    assert result.reason is McpConformanceReason.PROCESS_CONTROL_ERROR
    assert "terminate" in result.detail.lower()


def test_close_job_failure_is_public_process_control_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P1-1: CloseHandle(job) failure after a successful handshake is not green."""
    if sys.platform != "win32":
        pytest.skip("Windows job close path only")

    from agentkit.backend.installer.mcp_conformance import process as process_mod
    from agentkit.backend.installer.mcp_conformance.process import ProcessControlError

    def _boom_close(job: int) -> None:
        raise ProcessControlError("injected close failure")

    monkeypatch.setattr(process_mod, "_close_windows_job", _boom_close)
    result = check_mcp_conformance(
        _cmd(str(_MINIMAL_SERVER)),
        timeout_seconds=10.0,
    )
    assert result.ok is False
    assert result.reason is McpConformanceReason.PROCESS_CONTROL_ERROR
    assert "close" in result.detail.lower()


def test_teardown_control_error_overrides_prior_handshake_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Teardown control fault wins over a prior protocol/process error."""
    if sys.platform != "win32":
        pytest.skip("Windows job terminate path only")

    from agentkit.backend.installer.mcp_conformance import process as process_mod
    from agentkit.backend.installer.mcp_conformance.process import ProcessControlError

    def _boom_term(job: int, *, deadline: float) -> None:
        raise ProcessControlError("injected terminate after exit")

    monkeypatch.setattr(process_mod, "_terminate_windows_job", _boom_term)
    token = _token()
    result = check_mcp_conformance(
        _cmd(str(_BAD_SERVERS), "die", token),
        timeout_seconds=5.0,
    )
    assert result.ok is False
    assert result.reason is McpConformanceReason.PROCESS_CONTROL_ERROR
    _assert_no_token_leftovers(token)


def test_popen_failure_plus_close_failure_is_process_control_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Popen OSError + CloseHandle failure surfaces process_control_error."""
    if sys.platform != "win32":
        pytest.skip("Windows job path only")

    import subprocess as sp

    from agentkit.backend.installer.mcp_conformance import process as process_mod
    from agentkit.backend.installer.mcp_conformance.process import ProcessControlError

    def _boom_close(job: int) -> None:
        raise ProcessControlError("injected close after popen fail")

    def _boom_popen(*_a: object, **_k: object) -> object:
        raise OSError("injected popen failure")

    monkeypatch.setattr(process_mod, "_close_windows_job", _boom_close)
    monkeypatch.setattr(sp, "Popen", _boom_popen)
    result = check_mcp_conformance(
        _cmd(str(_MINIMAL_SERVER)),
        timeout_seconds=5.0,
    )
    assert result.ok is False
    assert result.reason is McpConformanceReason.PROCESS_CONTROL_ERROR
    assert "close" in result.detail.lower()


def test_assign_plus_close_both_in_public_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P1-1: assign failure AND close failure both appear in public detail."""
    if sys.platform != "win32":
        pytest.skip("Windows job path only")

    from agentkit.backend.installer.mcp_conformance import process as process_mod
    from agentkit.backend.installer.mcp_conformance.process import ProcessControlError

    def _fail_assign(job: int, proc: object) -> None:
        raise ProcessControlError("ATTACK_ASSIGN_FAILED")

    def _fail_close(job: int) -> None:
        raise ProcessControlError("ATTACK_CLOSE_FAILED")

    real_start = process_mod.ProcessSupervisor.start

    def start_with_hooks(
        self: object,
        *args: object,
        **kwargs: object,
    ) -> None:
        self._assign_hook = _fail_assign  # type: ignore[attr-defined]
        self._close_hook = _fail_close  # type: ignore[attr-defined]
        return real_start(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(process_mod.ProcessSupervisor, "start", start_with_hooks)
    result = check_mcp_conformance(
        _cmd(str(_MINIMAL_SERVER)),
        timeout_seconds=5.0,
    )
    assert result.ok is False
    assert result.reason is McpConformanceReason.PROCESS_CONTROL_ERROR
    assert "ATTACK_ASSIGN_FAILED" in result.detail
    assert "ATTACK_CLOSE_FAILED" in result.detail


def test_terminate_plus_close_both_in_public_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review-7 P1-1: teardown terminate AND job-close both in public detail."""
    if sys.platform != "win32":
        pytest.skip("Windows job path only")

    from agentkit.backend.installer.mcp_conformance import process as process_mod
    from agentkit.backend.installer.mcp_conformance.process import ProcessControlError

    def _fail_term(job: int, *, deadline: float) -> None:
        raise ProcessControlError("ATTACK_TERMINATE_FAILED")

    def _fail_close(job: int) -> None:
        raise ProcessControlError("ATTACK_CLOSE_FAILED")

    monkeypatch.setattr(process_mod, "_terminate_windows_job", _fail_term)
    monkeypatch.setattr(process_mod, "_close_windows_job", _fail_close)
    result = check_mcp_conformance(
        _cmd(str(_MINIMAL_SERVER)),
        timeout_seconds=10.0,
    )
    assert result.ok is False
    assert result.reason is McpConformanceReason.PROCESS_CONTROL_ERROR
    assert "ATTACK_TERMINATE_FAILED" in result.detail
    assert "ATTACK_CLOSE_FAILED" in result.detail


def test_slow_popen_then_assign_failure_rearms_cleanup_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P1-2: after slow Popen, assign-fail path still has positive wait budget."""
    if sys.platform != "win32":
        pytest.skip("Windows job path only")

    import subprocess as sp

    from agentkit.backend.installer.mcp_conformance.process import (
        ProcessControlError,
        ProcessSupervisor,
    )

    real_popen = sp.Popen
    wait_timeouts: list[float | None] = []
    popen_delay = 0.45
    cleanup_span = 0.35

    def slow_popen(*args: object, **kwargs: object) -> sp.Popen[bytes]:
        time.sleep(popen_delay)
        proc = real_popen(*args, **kwargs)

        real_wait = proc.wait

        def tracked_wait(timeout: float | None = None) -> int | None:
            wait_timeouts.append(timeout)
            return real_wait(timeout=timeout)

        proc.wait = tracked_wait  # type: ignore[method-assign]
        return proc

    monkeypatch.setattr(sp, "Popen", slow_popen)

    supervisor = ProcessSupervisor()

    def _fail_assign(job: int, proc: object) -> None:
        raise ProcessControlError("ATTACK_ASSIGN_AFTER_SLOW_POPEN")

    supervisor._assign_hook = _fail_assign  # noqa: SLF001
    deadline = time.monotonic() + cleanup_span
    with pytest.raises(ProcessControlError, match="ATTACK_ASSIGN_AFTER_SLOW_POPEN"):
        supervisor.start(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            env={},
            cwd=None,
            deadline=deadline,
        )
    # Without re-arm, remaining budget after popen_delay > cleanup_span would be 0
    # and wait would be skipped. With re-arm, cleanup still runs with positive timeout.
    positive_waits = [t for t in wait_timeouts if t is not None and t > 0.05]
    assert positive_waits, (wait_timeouts, popen_delay, cleanup_span)
    assert supervisor.proc is None
    assert supervisor._job is None  # noqa: SLF001


def test_setinfo_plus_close_failure_is_process_control_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P1-3: SetInformation fail + CloseHandle fail is named process_control_error.

    Boundary fake: force job factory to raise the combined error shape that the
    production SetInformation+Close path produces (OS-level dual fault is not
    reliably injectable).
    """
    if sys.platform != "win32":
        pytest.skip("Windows job path only")

    from agentkit.backend.installer.mcp_conformance import process as process_mod
    from agentkit.backend.installer.mcp_conformance.process import (
        ProcessControlError,
        ProcessSupervisor,
    )

    def _boom_create() -> int:
        raise ProcessControlError(
            "SetInformationJobObject failed (winerr=5); "
            "CloseHandle(job-after-setinfo-fail) failed (winerr=6)."
        )

    supervisor = ProcessSupervisor()
    supervisor._job_factory = _boom_create  # noqa: SLF001
    with pytest.raises(ProcessControlError, match="SetInformationJobObject"):
        supervisor.start([sys.executable, "-c", "pass"], env={}, cwd=None)

    # Public check surface maps the same fault class.
    monkeypatch.setattr(process_mod, "_create_windows_job", _boom_create)
    result = check_mcp_conformance(
        _cmd(str(_MINIMAL_SERVER)),
        timeout_seconds=5.0,
    )
    assert result.ok is False
    assert result.reason is McpConformanceReason.PROCESS_CONTROL_ERROR


def test_slow_popen_does_not_consume_controlled_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P1-4: after a slow launch, full controlled budget is re-armed."""
    from agentkit.backend.installer.mcp_conformance import check as check_mod
    from agentkit.backend.installer.mcp_conformance.process import ProcessSupervisor

    captured: list[tuple[float, float]] = []
    real_handshake = check_mod._handshake  # noqa: SLF001
    real_start = ProcessSupervisor.start
    launch_delay = 0.35

    def delayed_start(
        self: ProcessSupervisor,
        *args: object,
        **kwargs: object,
    ) -> None:
        time.sleep(launch_delay)
        return real_start(self, *args, **kwargs)

    def capturing_handshake(
        *args: object,
        deadline: float,
        **kwargs: object,
    ) -> object:
        now = time.monotonic()
        captured.append((now, deadline))
        return real_handshake(*args, deadline=deadline, **kwargs)

    monkeypatch.setattr(ProcessSupervisor, "start", delayed_start)
    monkeypatch.setattr(check_mod, "_handshake", capturing_handshake)

    timeout = 2.0
    result = check_mcp_conformance(
        _cmd(str(_MINIMAL_SERVER)),
        timeout_seconds=timeout,
    )
    assert result.ok is True, result.detail
    assert captured, "handshake was not entered"
    now, deadline = captured[0]
    remaining = deadline - now
    # Handshake share is 80% of timeout; after re-arm must still be ~that,
    # not timeout - launch_delay.
    assert remaining >= timeout * 0.7, (remaining, timeout, launch_delay)


def test_resolve_command_edge_cases(tmp_path: Path) -> None:
    from agentkit.backend.installer.mcp_conformance.process import resolve_command

    assert resolve_command("", cwd=tmp_path) is None
    assert resolve_command("   ", cwd=tmp_path) is None
    missing_abs = tmp_path / "no-such-bin"
    assert resolve_command(str(missing_abs), cwd=tmp_path) is None
    real = tmp_path / "tool.py"
    real.write_text("x", encoding="utf-8")
    assert resolve_command(str(real), cwd=tmp_path) == str(real)
    assert resolve_command("tool.py", cwd=tmp_path) == str(real.resolve())


def test_server_command_from_mcp_entry_validation() -> None:
    from agentkit.backend.installer.mcp_conformance.check import (
        server_command_from_mcp_entry,
    )

    cmd = server_command_from_mcp_entry(
        {"command": "python", "args": ["-m", "x"], "env": {"A": "1"}}
    )
    assert cmd.command == "python"
    assert list(cmd.args) == ["-m", "x"]
    assert cmd.env == {"A": "1"}
    assert server_command_from_mcp_entry({"command": "c", "args": None}).args == []
    with pytest.raises(ValueError, match="command"):
        server_command_from_mcp_entry({"command": ""})
    with pytest.raises(ValueError, match="args"):
        server_command_from_mcp_entry({"command": "c", "args": [1]})
    with pytest.raises(ValueError, match="env"):
        server_command_from_mcp_entry({"command": "c", "env": {"A": 1}})


def test_split_probe_deadlines_rejects_non_positive() -> None:
    from agentkit.backend.installer.mcp_conformance.check import split_probe_deadlines

    with pytest.raises(ValueError, match="positive"):
        split_probe_deadlines(0)
    with pytest.raises(ValueError, match="positive"):
        split_probe_deadlines(-1)


def test_check_rejects_non_positive_timeout() -> None:
    with pytest.raises(ValueError, match="positive"):
        check_mcp_conformance(
            McpServerCommand(command="python"),
            timeout_seconds=0,
        )


def test_posix_kill_group_is_exercised_via_mocks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Coverage for POSIX group kill (mocked on Windows CI hosts)."""
    from agentkit.backend.installer.mcp_conformance import process as process_mod

    calls: list[tuple[int, int]] = []

    def fake_killpg(pgid: int, sig: int) -> None:
        calls.append((pgid, sig))

    monkeypatch.setattr(process_mod.os, "killpg", fake_killpg, raising=False)
    monkeypatch.setattr(
        process_mod.os,
        "getpgid",
        lambda pid: 4242 if pid == 9 else -1,
        raising=False,
    )
    monkeypatch.setattr(process_mod.signal, "SIGTERM", 15, raising=False)
    monkeypatch.setattr(process_mod.signal, "SIGKILL", 9, raising=False)

    class _FakeProc:
        pid = 9

    monkeypatch.setattr(
        process_mod.psutil,
        "process_iter",
        lambda attrs=None: [_FakeProc()],
    )
    process_mod._kill_posix_group(4242, deadline=time.monotonic() + 1.0)
    assert len(calls) >= 1  # at least SIGTERM; SIGKILL if still live


def test_posix_start_path_direct() -> None:
    """Exercise POSIX start helper (platform-independent unit call)."""
    from agentkit.backend.installer.mcp_conformance.process import ProcessSupervisor

    supervisor = ProcessSupervisor()
    supervisor._start_posix(  # noqa: SLF001
        [sys.executable, "-c", "pass"],
        env={},
        cwd=None,
    )
    assert supervisor.proc is not None
    assert supervisor._pgid == supervisor.proc.pid  # noqa: SLF001
    with contextlib.suppress(Exception):
        supervisor.proc.wait(timeout=5.0)
    supervisor._close_pipes()  # noqa: SLF001


def test_identity_of_missing_process() -> None:
    from agentkit.backend.installer.mcp_conformance.process import identity_of

    assert identity_of(0) is None or identity_of(999_999_999) is None


def test_resolve_relative_command_against_cwd(tmp_path: Path) -> None:
    script = tmp_path / "bin" / "server.py"
    script.parent.mkdir(parents=True)
    script.write_text(
        Path(_MINIMAL_SERVER).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    if sys.platform == "win32":
        wrapper = tmp_path / "run_server.bat"
        wrapper.write_text(
            f'@echo off\r\n"{sys.executable}" "%~dp0bin\\server.py"\r\n',
            encoding="utf-8",
        )
        command = ".\\run_server.bat"
    else:
        wrapper = tmp_path / "wrapper"
        wrapper.write_text(
            f"#!/bin/sh\nexec {sys.executable} \"$(dirname \"$0\")/bin/server.py\"\n",
            encoding="utf-8",
        )
        wrapper.chmod(0o755)
        command = "./wrapper"
    result = check_mcp_conformance(
        McpServerCommand(command=command, cwd=tmp_path),
        timeout_seconds=10.0,
    )
    assert result.ok is True, result.detail
