"""Regression pins for backend-owned third-system validation."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from agentkit.backend.cli.main import main
from agentkit.backend.installer.runner import InstallConfig
from agentkit.harness_client.projectedge.credentials import (
    activate_project_credentials,
    prepare_project_api_token,
    project_credentials_path,
    write_pending_project_credentials,
)

if TYPE_CHECKING:
    import argparse
    from pathlib import Path

    import pytest


def test_install_config_has_no_dev_third_system_client_slots() -> None:
    """The installer cannot receive a dev-side Sonar/Jenkins client."""
    forbidden = {
        "sonar_client",
        "sonar_token_permissions",
        "sonar_branch_plugin_self_test",
        "sonar_scan_runner",
        "ci_client",
    }
    assert forbidden.isdisjoint(InstallConfig.__dataclass_fields__)


def test_register_and_verify_instantiate_no_sonar_or_jenkins_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both CLI flows reach the engine without constructing third-system clients."""

    class _Result:
        success = True
        checkpoint_results: tuple[object, ...] = ()

    modes: list[str] = []

    def _run(_config: object, *, mode: object) -> _Result:
        modes.append(str(getattr(mode, "value", mode)))
        return _Result()

    def _forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("a third-system client was instantiated in the dev process")

    monkeypatch.setattr(
        "agentkit.backend.installer.bootstrap_checkpoints.orchestrator."
        "run_checkpoint_install",
        _run,
    )
    monkeypatch.setattr("agentkit.integration_clients.sonar.SonarClient.__init__", _forbidden)
    monkeypatch.setattr(
        "agentkit.integration_clients.jenkins.JenkinsClient.__init__", _forbidden
    )

    def _writer_ready(
        config: object,
        args: object,
        op_id: str,
    ) -> object:
        del config, op_id
        from agentkit.backend.cli.auth_commands import prepare_installer_auth_context

        return prepare_installer_auth_context(cast("argparse.Namespace", args))

    monkeypatch.setattr(
        "agentkit.backend.cli.installer_commands._wire_register_config_to_writer",
        _writer_ready,
    )
    monkeypatch.setattr(
        "agentkit.backend.installer.writer_client.InstallerWriterClient.assert_ready",
        lambda _client: None,
    )
    common = [
        "--project-key",
        "ak3",
        "--project-name",
        "AgentKit",
        "--project-root",
        str(tmp_path),
        "--github-owner",
        "openai",
        "--github-repo",
        "agentkit",
    ]
    prepared = prepare_project_api_token(project_key="ak3", label="project-edge")
    credential_path = project_credentials_path(tmp_path)
    write_pending_project_credentials(
        credential_path,
        project_key="ak3",
        prepared_token=prepared,
        issuance_op_id="op-existing-credential",
    )
    activate_project_credentials(credential_path)

    assert main(["register-project", *common]) == 0
    assert main(["verify-project", *common]) == 0
    assert modes == ["register", "verify"]


def test_register_project_backend_unreachable_preserves_every_local_artifact(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """register-project fails before any local effect when no writer exists."""
    prepared = prepare_project_api_token(project_key="ak3", label="project-edge")
    credential_path = project_credentials_path(tmp_path)
    write_pending_project_credentials(
        credential_path,
        project_key="ak3",
        prepared_token=prepared,
        issuance_op_id="op-backend-failure-prerequisite",
    )
    activate_project_credentials(credential_path)
    write_pending_project_credentials(
        credential_path,
        project_key="ak3",
        prepared_token=prepared,
        issuance_op_id="op-backend-failure-prerequisite",
    )
    before = {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }

    exit_code = main(
        [
            "register-project",
            "--project-key",
            "ak3",
            "--project-name",
            "AgentKit",
            "--project-root",
            str(tmp_path),
            "--github-owner",
            "openai",
            "--github-repo",
            "agentkit",
            "--control-plane-base-url",
            "https://127.0.0.1:1",
        ]
    )

    assert exit_code != 0
    assert "ControlPlaneWriterUnavailable" in capsys.readouterr().err
    assert {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    } == before


def test_upgrade_project_without_writer_preserves_every_local_artifact(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """upgrade-project names writer unavailability before mutating the project."""

    prepared = prepare_project_api_token(project_key="ak3", label="project-edge")
    credential_path = project_credentials_path(tmp_path)
    write_pending_project_credentials(
        credential_path,
        project_key="ak3",
        prepared_token=prepared,
        issuance_op_id="op-upgrade-writer-prerequisite",
    )
    activate_project_credentials(credential_path)
    write_pending_project_credentials(
        credential_path,
        project_key="ak3",
        prepared_token=prepared,
        issuance_op_id="op-upgrade-writer-prerequisite",
    )
    marker = tmp_path / "owned.txt"
    marker.write_text("unchanged", encoding="utf-8")
    before = {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }

    exit_code = main(
        [
            "upgrade-project",
            "--project-key",
            "ak3",
            "--project-root",
            str(tmp_path),
            "--github-owner",
            "openai",
            "--github-repo",
            "agentkit",
            "--target-config-version",
            "4.0",
            "--control-plane-base-url",
            "https://127.0.0.1:1",
        ]
    )

    assert exit_code != 0
    assert "ControlPlaneWriterUnavailable" in capsys.readouterr().err
    assert {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    } == before
