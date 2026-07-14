"""Regression pins for backend-owned third-system validation."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.cli.main import main
from agentkit.backend.installer.runner import InstallConfig

if TYPE_CHECKING:
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

    assert main(["register-project", *common]) == 0
    assert main(["verify-project", *common]) == 0
    assert modes == ["register", "verify"]


def test_register_project_backend_unreachable_returns_nonzero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The CLI preserves the CP10d fail-closed exception as exit code 1."""
    from agentkit.backend.exceptions import InstallationError

    def _unreachable(_config: object, *, mode: object) -> None:
        del mode
        raise InstallationError(
            "Third-party validation backend is unreachable",
            detail={"error_code": "third_party_backend_unreachable"},
        )

    monkeypatch.setattr(
        "agentkit.backend.installer.bootstrap_checkpoints.orchestrator."
        "run_checkpoint_install",
        _unreachable,
    )

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
        ]
    )

    assert exit_code != 0
    assert "backend is unreachable" in capsys.readouterr().err
