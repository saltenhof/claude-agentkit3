from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.auth.credentials import StrategistCredentialStore
from agentkit.backend.auth.entities import StrategistCredentials
from agentkit.backend.cli.main import main
from agentkit.harness_client.projectedge.credentials import (
    CredentialMissingError,
    CredentialStateError,
    activate_project_credentials,
    load_active_project_credentials,
    pending_project_credentials_path,
    prepare_project_api_token,
    project_credentials_path,
    write_pending_project_credentials,
)
from agentkit.harness_client.projectedge.private_files import atomic_write_private_text

if TYPE_CHECKING:
    from pathlib import Path


def test_bootstrap_without_terminal_fails_closed_without_reading_or_printing_secret(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "must-never-reach-captured-output"
    read_calls = 0

    def _secret_reader(_prompt: str) -> str:
        nonlocal read_calls
        read_calls += 1
        return secret

    monkeypatch.setattr("getpass.getpass", _secret_reader)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    monkeypatch.setattr(sys.stderr, "isatty", lambda: False)

    exit_code = main(["auth", "bootstrap"])

    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert exit_code == 1
    assert read_calls == 0
    assert secret not in combined
    assert "interactive terminal" in combined


def test_interactive_bootstrap_writes_only_operator_chosen_password_hash(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    auth_path = tmp_path / "auth.json"
    secret = "operator-knows-this-before-publication"
    answers = iter((secret, secret))
    monkeypatch.setattr("getpass.getpass", lambda _prompt: next(answers))
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(sys.stderr, "isatty", lambda: True)

    assert main(["auth", "bootstrap", "--auth-config", str(auth_path)]) == 0
    stored = auth_path.read_text(encoding="utf-8")
    assert secret not in stored
    StrategistCredentialStore(auth_path).verify(
        StrategistCredentials(username="admin", password=secret),
    )


def test_token_issue_without_terminal_fails_before_secret_or_transport_access(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "must-never-reach-captured-output"
    read_calls = 0

    def _secret_reader(_prompt: str) -> str:
        nonlocal read_calls
        read_calls += 1
        return secret

    monkeypatch.setattr("getpass.getpass", _secret_reader)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    monkeypatch.setattr(sys.stderr, "isatty", lambda: False)

    exit_code = main(
        [
            "auth",
            "issue-token",
            "--base-url",
            "https://127.0.0.1:9701",
            "--project-key",
            "project-a",
        ],
    )

    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert exit_code == 1
    assert read_calls == 0
    assert secret not in combined
    assert "Run it directly from an interactive terminal" in combined


def test_auth_help_lists_bootstrap_login_token_and_rotation_verbs(
    capsys: pytest.CaptureFixture[str],
) -> None:
    try:
        main(["auth", "--help"])
    except SystemExit as exc:
        assert exc.code == 0

    help_text = capsys.readouterr().out
    for verb in (
        "bootstrap",
        "login",
        "rotate-password",
        "issue-token",
        "store-token",
        "revoke-token",
    ):
        assert verb in help_text


def test_admin_issue_token_outputs_once_without_writing_client_credentials(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    from agentkit.harness_client.projectedge.auth_operator import IssuedProjectTokenResult

    issued_token = "ak3_adminissued_handed-off-secret"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(sys.stderr, "isatty", lambda: True)
    monkeypatch.setattr("getpass.getpass", lambda prompt: "admin-password")
    monkeypatch.setattr(
        "agentkit.backend.cli.auth_commands._build_transport",
        lambda _base_url, _ca_file: object(),
    )
    monkeypatch.setattr(
        "agentkit.backend.cli.auth_commands.authenticate_strategist",
        lambda transport, *, password, project_key: (transport, password, project_key),
    )
    monkeypatch.setattr(
        "agentkit.backend.cli.auth_commands.issue_project_token",
        lambda _transport, **_kwargs: IssuedProjectTokenResult(
            token_id="adminissued",
            project_api_token=issued_token,
        ),
    )

    exit_code = main(
        [
            "auth",
            "issue-token",
            "--base-url",
            "https://core.example.test",
            "--project-key",
            "project-a",
        ],
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out.count(issued_token) == 1
    assert issued_token not in captured.err
    assert "credential_path" not in captured.out
    assert not project_credentials_path(tmp_path).exists()


def test_client_store_token_uses_bearer_proof_without_strategist_password(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    prepared = prepare_project_api_token(project_key="project-a", label="handoff")
    prompts: list[str] = []
    validated: list[tuple[object, str]] = []
    transport = object()
    monkeypatch.delenv("AGENTKIT_AUTH_CONFIG", raising=False)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(sys.stderr, "isatty", lambda: True)

    def _read_token(prompt: str) -> str:
        prompts.append(prompt)
        return prepared.plaintext_token

    monkeypatch.setattr("getpass.getpass", _read_token)
    monkeypatch.setattr(
        "agentkit.backend.cli.auth_commands._build_project_token_transport",
        lambda *_args, **_kwargs: transport,
    )
    monkeypatch.setattr(
        "agentkit.backend.cli.auth_commands.validate_project_token",
        lambda received, *, project_key: validated.append((received, project_key)),
    )

    exit_code = main(
        [
            "auth",
            "store-token",
            "--base-url",
            "https://core.example.test",
            "--project-key",
            "project-a",
            "--project-root",
            str(tmp_path),
        ],
    )

    credential = load_active_project_credentials(
        project_credentials_path(tmp_path),
        project_key="project-a",
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert prompts == ["Project API token: "]
    assert validated == [(transport, "project-a")]
    assert credential.project_api_token == prepared.plaintext_token
    assert prepared.plaintext_token not in captured.out + captured.err
    assert not (tmp_path / "auth.json").exists()


def test_client_store_token_does_not_persist_failed_bearer_proof(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    prepared = prepare_project_api_token(project_key="project-a", label="handoff")
    credential_path = project_credentials_path(tmp_path)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(sys.stderr, "isatty", lambda: True)
    monkeypatch.setattr("getpass.getpass", lambda _prompt: prepared.plaintext_token)
    monkeypatch.setattr(
        "agentkit.backend.cli.auth_commands._build_project_token_transport",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        "agentkit.backend.cli.auth_commands.validate_project_token",
        lambda _transport, *, project_key: (_ for _ in ()).throw(
            CredentialStateError(f"token is not valid for {project_key}"),
        ),
    )

    exit_code = main(
        [
            "auth",
            "store-token",
            "--base-url",
            "https://core.example.test",
            "--project-key",
            "project-a",
            "--project-root",
            str(tmp_path),
        ],
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert not credential_path.exists()
    assert prepared.plaintext_token not in captured.out + captured.err


def test_register_project_without_handed_off_token_never_prompts_for_admin_password(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from agentkit.backend.cli.auth_commands import prepare_installer_auth_context

    reads = 0

    def _unexpected_prompt(_prompt: str) -> str:
        nonlocal reads
        reads += 1
        return "admin-password-must-not-be-read"

    monkeypatch.setattr("getpass.getpass", _unexpected_prompt)
    args = SimpleNamespace(
        project_root=str(tmp_path),
        project_key="project-a",
        control_plane_base_url="https://core.example.test",
        control_plane_ca_file=None,
    )

    with pytest.raises(CredentialMissingError, match="store-token"):
        prepare_installer_auth_context(args)
    assert reads == 0


def test_register_auth_context_rejects_unreconciled_pending_rotation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from agentkit.backend.cli.auth_commands import prepare_installer_auth_context

    credential_path = project_credentials_path(tmp_path)
    active_preparation = prepare_project_api_token(project_key="project-a", label="edge")
    write_pending_project_credentials(
        credential_path,
        project_key="project-a",
        prepared_token=active_preparation,
        issuance_op_id="op-active",
    )
    active = activate_project_credentials(credential_path)
    pending_preparation = prepare_project_api_token(project_key="project-a", label="edge")
    write_pending_project_credentials(
        credential_path,
        project_key="project-a",
        prepared_token=pending_preparation,
        issuance_op_id="op-pending",
        superseded_token_id=active.token_id,
    )
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    monkeypatch.setattr(sys.stderr, "isatty", lambda: False)
    args = SimpleNamespace(
        project_root=str(tmp_path),
        project_key="project-a",
        control_plane_base_url="https://127.0.0.1:9702",
        control_plane_ca_file=None,
    )

    with pytest.raises(CredentialStateError, match="different issuances"):
        prepare_installer_auth_context(args)


def test_register_auth_context_rejects_corrupt_pending_before_prompt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from agentkit.backend.cli.auth_commands import prepare_installer_auth_context
    from agentkit.harness_client.projectedge.credentials import CredentialInvalidError

    credential_path = project_credentials_path(tmp_path)
    atomic_write_private_text(
        pending_project_credentials_path(credential_path),
        '{"project_key":"project-a","project_api_token":"broken"}',
    )
    reads = 0

    def _unexpected_prompt(_prompt: str) -> str:
        nonlocal reads
        reads += 1
        return "must-not-be-read"

    monkeypatch.setattr("getpass.getpass", _unexpected_prompt)
    args = SimpleNamespace(
        project_root=str(tmp_path),
        project_key="project-a",
        control_plane_base_url="https://127.0.0.1:9702",
        control_plane_ca_file=None,
    )

    with pytest.raises(CredentialInvalidError, match="invalid"):
        prepare_installer_auth_context(args)
    assert reads == 0


def test_register_auth_context_rejects_foreign_pending_before_installer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from agentkit.backend.cli.auth_commands import prepare_installer_auth_context

    credential_path = project_credentials_path(tmp_path)
    prepared = prepare_project_api_token(project_key="project-a", label="edge-a")
    write_pending_project_credentials(
        credential_path,
        project_key="project-a",
        prepared_token=prepared,
        issuance_op_id="op-project-a",
    )
    reads = 0

    def _unexpected_prompt(_prompt: str) -> str:
        nonlocal reads
        reads += 1
        return "must-not-be-read"

    monkeypatch.setattr("getpass.getpass", _unexpected_prompt)
    args = SimpleNamespace(
        project_root=str(tmp_path),
        project_key="project-b",
        control_plane_base_url="https://127.0.0.1:9702",
        control_plane_ca_file=None,
    )

    with pytest.raises(CredentialStateError, match="cannot initialize"):
        prepare_installer_auth_context(args)
    assert reads == 0


def test_rotate_password_exposes_and_reuses_operator_operation_id(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[tuple[str, str]] = []
    answers = iter(("current-secret", "replacement-secret", "replacement-secret"))
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(sys.stderr, "isatty", lambda: True)
    monkeypatch.setattr("getpass.getpass", lambda _prompt: next(answers))
    monkeypatch.setattr(
        "agentkit.backend.cli.auth_commands._build_transport",
        lambda _base_url, _ca_file: object(),
    )
    monkeypatch.setattr(
        "agentkit.backend.cli.auth_commands.authenticate_strategist",
        lambda _transport, *, password, project_key: (password, project_key),
    )

    def _rotate(_transport: object, *, new_password: str, op_id: str) -> None:
        calls.append((new_password, op_id))

    monkeypatch.setattr(
        "agentkit.backend.cli.auth_commands.rotate_strategist_password",
        _rotate,
    )

    exit_code = main(
        [
            "auth",
            "rotate-password",
            "--base-url",
            "https://127.0.0.1:9702",
            "--project-key",
            "project-a",
            "--op-id",
            "op-recover-visible",
        ],
    )

    assert exit_code == 0
    assert calls == [("replacement-secret", "op-recover-visible")]
    rendered = capsys.readouterr().out
    assert '"status": "rotation_requested"' in rendered
    assert rendered.count("op-recover-visible") == 2
    assert "replacement-secret" not in rendered


def test_revoke_token_exposes_and_reuses_operator_operation_id(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[tuple[str, str, str]] = []
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(sys.stderr, "isatty", lambda: True)
    monkeypatch.setattr("getpass.getpass", lambda _prompt: "current-secret")
    monkeypatch.setattr(
        "agentkit.backend.cli.auth_commands._build_transport",
        lambda _base_url, _ca_file: object(),
    )
    monkeypatch.setattr(
        "agentkit.backend.cli.auth_commands.authenticate_strategist",
        lambda _transport, *, password, project_key: (password, project_key),
    )

    def _revoke(
        _transport: object,
        *,
        project_key: str,
        token_id: str,
        op_id: str,
        credential_path: Path | None,
    ) -> None:
        del credential_path
        calls.append((project_key, token_id, op_id))

    monkeypatch.setattr(
        "agentkit.backend.cli.auth_commands.revoke_project_token",
        _revoke,
    )

    exit_code = main(
        [
            "auth",
            "revoke-token",
            "--base-url",
            "https://127.0.0.1:9702",
            "--project-key",
            "project-a",
            "--token-id",
            "token-old",
            "--op-id",
            "op-revoke-visible",
        ],
    )

    assert exit_code == 0
    assert calls == [("project-a", "token-old", "op-revoke-visible")]
    rendered = capsys.readouterr().out
    assert '"status": "revocation_requested"' in rendered
    assert rendered.count("op-revoke-visible") == 2
    assert "current-secret" not in rendered


def test_successful_register_project_invokes_project_credential_provisioning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agentkit.backend.cli import installer_commands

    args = SimpleNamespace(dry_run=False, project_root="T:/project")
    called_with: list[object] = []
    config = SimpleNamespace(project_edge_client=None)
    auth_context = SimpleNamespace(
        project_edge_client=object(),
        clear_secret=lambda: None,
    )
    monkeypatch.setattr(installer_commands, "_build_engine_config", lambda _args: config)
    monkeypatch.setattr(
        "agentkit.backend.cli.auth_commands.prepare_installer_auth_context",
        lambda _args: auth_context,
    )
    monkeypatch.setattr(
        "agentkit.backend.installer.bootstrap_checkpoints.orchestrator.run_checkpoint_install",
        lambda _config, *, mode: SimpleNamespace(success=True, checkpoint_results=[]),
    )

    def _provision(received: object, context: object) -> int:
        called_with.extend((received, context))
        return 37

    monkeypatch.setattr(
        "agentkit.backend.cli.auth_commands.provision_installer_project_token",
        _provision,
    )

    result = installer_commands._cmd_register_project(args)

    assert result == 37
    assert called_with == [args, auth_context]
    assert config.project_edge_client is auth_context.project_edge_client
