from __future__ import annotations

from argparse import Namespace
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.cli._operator_ownership_commands import (
    _cmd_recover_story,
    _cmd_takeover_confirm,
    _cmd_takeover_request,
)
from agentkit.backend.cli.main import main
from agentkit.backend.control_plane.models import (
    ControlPlaneMutationResult,
    RecoveryRequest,
    TakeoverChallenge,
    TakeoverConfirmRequest,
    TakeoverRequest,
)
from agentkit.backend.control_plane.ownership_transfer import LOSS_CORRIDOR_TEXT
from agentkit.backend.exceptions import ControlPlaneApiError

if TYPE_CHECKING:
    from pathlib import Path


class _RecordingClient:
    def __init__(self, result: ControlPlaneMutationResult) -> None:
        self.result = result
        self.request: TakeoverRequest | TakeoverConfirmRequest | RecoveryRequest | None = None

    def takeover_request(self, *, run_id: str, request: TakeoverRequest) -> ControlPlaneMutationResult:
        assert run_id == "run-old"
        self.request = request
        return self.result

    def takeover_confirm(self, *, run_id: str, request: TakeoverConfirmRequest) -> ControlPlaneMutationResult:
        assert run_id == "run-old"
        self.request = request
        return self.result

    def recover(self, *, run_id: str, request: RecoveryRequest) -> ControlPlaneMutationResult:
        assert run_id == "run-old"
        self.request = request
        return self.result


def _args(tmp_path: Path, **updates: object) -> Namespace:
    values: dict[str, object] = {
        "base_url": "http://127.0.0.1:9701",
        "project_root": str(tmp_path),
        "project": "tenant-a",
        "username": "strategist",
        "story": "AG3-154",
        "run": "run-old",
        "session": "sess-new",
        "reason": "operator decision",
        "worktree": [str(tmp_path)],
        "challenge_id": "challenge-1",
        "discard": False,
        "op_id": "op-cli-1",
        "config": None,
    }
    values.update(updates)
    return Namespace(**values)


def _result(status: str, **updates: object) -> ControlPlaneMutationResult:
    return ControlPlaneMutationResult.model_construct(
        status=status,
        op_id="op-cli-1",
        operation_kind="ownership_test",
        run_id="run-old",
        edge_bundle=None,
        **updates,
    )


def _challenge() -> TakeoverChallenge:
    return TakeoverChallenge(
        challenge_id="challenge-1",
        project_key="tenant-a",
        story_id="AG3-154",
        run_id="run-old",
        requesting_session_id="sess-new",
        requesting_principal_type="human_cli",
        current_owner_session_id="sess-old",
        ownership_epoch=1,
        binding_version="bind-1",
        phase_status="implementation",
        owner_principal_type="orchestrator",
        last_owner_api_contact_note="Activity is not a liveness diagnosis.",
        reason="operator decision",
        loss_corridor_notice_key="pushed_only_loss_corridor",
        loss_corridor_notice_text=LOSS_CORRIDOR_TEXT,
    )


def test_takeover_request_displays_complete_challenge_and_loss_corridor(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    client = _RecordingClient(_result("offered", takeover_challenge=_challenge()))
    code = _cmd_takeover_request(
        _args(tmp_path),
        client_builder=lambda *_args: client,
        password_reader=lambda _prompt: "secret",
    )

    assert code == 0
    captured = capsys.readouterr()
    assert '"challenge_id": "challenge-1"' in captured.out
    assert LOSS_CORRIDOR_TEXT in captured.out


def test_takeover_confirm_echoes_challenge_without_force_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    client = _RecordingClient(_result("committed"))
    code = _cmd_takeover_confirm(
        _args(tmp_path),
        client_builder=lambda *_args: client,
        password_reader=lambda _prompt: "secret",
        confirmation_reader=lambda _prompt: "YES",
    )

    assert code == 0
    assert isinstance(client.request, TakeoverConfirmRequest)
    captured = capsys.readouterr()
    assert '"challenge_id": "challenge-1"' in captured.out


def test_takeover_confirm_parser_has_no_force_bypass(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "takeover-confirm",
                "--story",
                "AG3-154",
                "--run",
                "run-old",
                "--challenge-id",
                "challenge-1",
                "--reason",
                "operator decision",
                "--project",
                "tenant-a",
                "--project-root",
                str(tmp_path),
                "--base-url",
                "http://127.0.0.1:9701",
                "--force",
            ]
        )

    assert exc_info.value.code == 2


@pytest.mark.parametrize(
    ("error_code", "status"),
    [("agent_confirm_forbidden", 403), ("challenge_invalidated", 409)],
)
def test_takeover_confirm_passes_403_and_409_contract_unchanged(
    error_code: str,
    status: int,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class _FailingClient(_RecordingClient):
        def takeover_confirm(
            self, *, run_id: str, request: TakeoverConfirmRequest
        ) -> ControlPlaneMutationResult:
            del run_id, request
            raise ControlPlaneApiError(
                "confirm refused",
                error_code=error_code,
                correlation_id="corr-confirm",
                http_status=status,
            )

    client = _FailingClient(_result("committed"))
    code = _cmd_takeover_confirm(
        _args(tmp_path),
        client_builder=lambda *_args: client,
        password_reader=lambda _prompt: "secret",
        confirmation_reader=lambda _prompt: "YES",
    )

    assert code == 1
    assert f"[{error_code}] HTTP {status}" in capsys.readouterr().err


def test_recover_story_maps_default_adopt_without_destructive_prompt(tmp_path: Path) -> None:
    client = _RecordingClient(_result("committed"))

    code = _cmd_recover_story(
        _args(tmp_path),
        client_builder=lambda *_args: client,
        password_reader=lambda _prompt: "secret",
        confirmation_reader=lambda _prompt: (_ for _ in ()).throw(AssertionError("prompted")),
    )

    assert code == 0
    assert isinstance(client.request, RecoveryRequest)
    assert client.request.worktree_disposition == "adopt"


def test_recover_story_discard_maps_reset_only_after_destructive_confirmation(
    tmp_path: Path,
) -> None:
    client = _RecordingClient(_result("committed"))
    prompts: list[str] = []

    code = _cmd_recover_story(
        _args(tmp_path, discard=True),
        client_builder=lambda *_args: client,
        password_reader=lambda _prompt: "secret",
        confirmation_reader=lambda prompt: prompts.append(prompt) or "DISCARD",
    )

    assert code == 0
    assert isinstance(client.request, RecoveryRequest)
    assert client.request.worktree_disposition == "reset"
    assert prompts == [
        "Discard ALL uncommitted work and reset the worktree to HEAD? Type DISCARD: "
    ]


def test_recover_story_discard_refuses_without_explicit_confirmation(tmp_path: Path) -> None:
    client = _RecordingClient(_result("committed"))

    code = _cmd_recover_story(
        _args(tmp_path, discard=True),
        client_builder=lambda *_args: client,
        password_reader=lambda _prompt: "secret",
        confirmation_reader=lambda _prompt: "no",
    )

    assert code == 1
    assert client.request is None


@pytest.mark.parametrize(
    "error_code",
    [
        "nothing_to_recover",
        "recovery_blocked_by_freeze",
        "takeover_reconcile_required",
        "conflict",
    ],
)
def test_recover_story_surfaces_distinct_fail_closed_reason_unchanged(
    error_code: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class _FailingClient(_RecordingClient):
        def recover(self, *, run_id: str, request: RecoveryRequest) -> ControlPlaneMutationResult:
            del run_id, request
            raise ControlPlaneApiError(
                "recovery refused",
                error_code=error_code,
                correlation_id="corr-recovery",
                http_status=409,
            )

    client = _FailingClient(_result("committed"))
    code = _cmd_recover_story(
        _args(tmp_path),
        client_builder=lambda *_args: client,
        password_reader=lambda _prompt: "secret",
    )

    assert code == 1
    assert f"[{error_code}] HTTP 409" in capsys.readouterr().err
