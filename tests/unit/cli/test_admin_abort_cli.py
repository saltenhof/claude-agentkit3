"""Unit tests for the AG3-138 ``agentkit admin-abort`` CLI adapter (AC7).

FK-91 Regel 10: the ``admin-abort`` command is a THIN REST adapter onto
``POST /v1/project-edge/operations/{op_id}/admin-abort``. It opens NO DB
connection and builds NO second semantics -- the core owns the abort /
epoch-fence / Teil-Write->repair logic. These tests pin the delegation (the REST
``admin_abort_operation`` is called with the op_id + audited request) and the
fail-closed input handling, without a live backend.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

from agentkit.backend.cli.main import main
from agentkit.backend.control_plane.models import (
    AdminAbortRequest,
    ControlPlaneMutationResult,
)
from agentkit.backend.exceptions import ControlPlaneApiError

if TYPE_CHECKING:
    import pytest

_BASE_ARGS = [
    "admin-abort",
    "op-target-1",
    "--session",
    "admin-sess-1",
    "--principal",
    "operator",
    "--reason",
    "hung executor; operator decision",
]


def _abort_result(status: str = "aborted") -> ControlPlaneMutationResult:
    return ControlPlaneMutationResult(
        status=status,  # type: ignore[arg-type]
        op_id="op-target-1",
        operation_kind="phase_start",
        run_id="run-1",
        phase="implementation",
        edge_bundle=None,
        phase_dispatch=None,
        admin_note=f"admin_abort_inflight_operation: {status}",
    )


class _RecordingClient:
    """A ProjectEdgeClient stand-in recording the admin-abort delegation only."""

    def __init__(self, result: ControlPlaneMutationResult) -> None:
        self._result = result
        self.calls: list[dict[str, object]] = []

    def admin_abort_operation(
        self, *, op_id: str, request: AdminAbortRequest
    ) -> ControlPlaneMutationResult:
        self.calls.append({"op_id": op_id, "request": request})
        return self._result


def _invoke(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> tuple[int, str, str]:
    code = main(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_admin_abort_delegates_to_rest_endpoint_only(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC7: the CLI delegates to ``client.admin_abort_operation`` (no DB/runtime path)."""
    client = _RecordingClient(_abort_result("aborted"))
    args = [*_BASE_ARGS, "--base-url", "https://127.0.0.1:9702"]
    with patch(
        "agentkit.backend.cli.main._build_control_plane_client",
        return_value=client,
    ):
        code, out, _err = _invoke(args, capsys)

    assert code == 0
    assert len(client.calls) == 1, "exactly one REST delegation, no second path"
    call = client.calls[0]
    assert call["op_id"] == "op-target-1"
    request = call["request"]
    assert isinstance(request, AdminAbortRequest)
    assert request.session_id == "admin-sess-1"
    assert request.principal_type == "operator"
    assert request.reason == "hung executor; operator decision"
    assert "aborted" in out


def test_admin_abort_repair_result_is_a_success_exit(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A ``repair`` terminal outcome is a successful abort (exit 0)."""
    client = _RecordingClient(_abort_result("repair"))
    args = [*_BASE_ARGS, "--base-url", "https://127.0.0.1:9702"]
    with patch(
        "agentkit.backend.cli.main._build_control_plane_client",
        return_value=client,
    ):
        code, out, _err = _invoke(args, capsys)

    assert code == 0
    assert "repair" in out


def test_admin_abort_requires_base_url_and_never_touches_backend(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC7/fail-closed: without --base-url the CLI errors WITHOUT building a client.

    The operator CLI never runs the core in-process (no DB path); a missing
    base URL is a fail-closed input error, and the control-plane client is never
    constructed.
    """
    with patch(
        "agentkit.backend.cli.main._build_control_plane_client",
    ) as build_client:
        code, _out, err = _invoke(list(_BASE_ARGS), capsys)

    assert code == 1
    assert "MissingBaseUrl" in err
    build_client.assert_not_called()


def test_admin_abort_maps_stable_api_error_to_nonzero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A stable 404/409 API error surfaces its error_code and exits non-zero."""

    class _FailingClient:
        def admin_abort_operation(
            self, *, op_id: str, request: AdminAbortRequest
        ) -> ControlPlaneMutationResult:
            del op_id, request
            raise ControlPlaneApiError(
                "Operation 'op-target-1' not found",
                error_code="operation_not_found",
                correlation_id="req-1",
                http_status=404,
            )

    args = [*_BASE_ARGS, "--base-url", "https://127.0.0.1:9702"]
    with patch(
        "agentkit.backend.cli.main._build_control_plane_client",
        return_value=_FailingClient(),
    ):
        code, _out, err = _invoke(args, capsys)

    assert code == 1
    assert "operation_not_found" in err


def test_admin_abort_rejects_empty_reason_before_any_call(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An empty ``--reason`` fails validation locally (mandatory audited reason)."""
    args = [
        "admin-abort",
        "op-target-1",
        "--session",
        "admin-sess-1",
        "--principal",
        "operator",
        "--reason",
        "",
        "--base-url",
        "https://127.0.0.1:9702",
    ]
    with patch(
        "agentkit.backend.cli.main._build_control_plane_client",
    ) as build_client:
        code, _out, err = _invoke(args, capsys)

    assert code == 1
    assert "InvalidRequest" in err
    build_client.assert_not_called()
