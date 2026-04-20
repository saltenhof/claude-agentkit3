"""Unit tests for the AgentKit CLI entrypoint.

Tests the ``main()`` function from ``agentkit.cli.main`` to verify
that all subcommands parse correctly and return the expected exit codes.
"""

from __future__ import annotations

from pathlib import PurePath
from types import SimpleNamespace
from typing import TYPE_CHECKING

from agentkit.cli.main import main

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


class TestCLIMain:
    """Tests for the top-level CLI ``main()`` function."""

    def test_version_flag(self, capsys: pytest.CaptureFixture[str]) -> None:
        """``--version`` prints version string and returns 0."""
        exit_code = main(["--version"])

        assert exit_code == 0
        captured = capsys.readouterr()
        assert "agentkit" in captured.out
        # Version should be a valid semver-like string
        assert "." in captured.out

    def test_no_args_shows_help(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """No arguments prints help and returns 0."""
        exit_code = main([])

        assert exit_code == 0
        captured = capsys.readouterr()
        assert "agentkit" in captured.out.lower() or "usage" in captured.out.lower()

    def test_install_command(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """``install`` subcommand creates .agentkit/ in target project."""
        exit_code = main([
            "install",
            "--project-key", "test-cli-project",
            "--project-name", "test-cli-project",
            "--project-root", str(tmp_path),
        ])

        assert exit_code == 0
        assert (tmp_path / ".agentkit").is_dir()
        assert (tmp_path / ".agentkit" / "config" / "project.yaml").exists()

        captured = capsys.readouterr()
        assert "installed" in captured.out.lower()

    def test_install_command_nonexistent_root(
        self, tmp_path: Path,
    ) -> None:
        """``install`` into non-existent directory raises ProjectError."""
        import pytest as pt

        from agentkit.exceptions import ProjectError

        with pt.raises(ProjectError):
            main([
                "install",
                "--project-key", "test",
                "--project-name", "test",
                "--project-root", str(tmp_path / "nonexistent"),
            ])

    def test_install_command_returns_failure_code(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """``install`` returns 1 when installer reports failure."""

        def fake_install_agentkit(_config: object) -> SimpleNamespace:
            return SimpleNamespace(
                success=False,
                created_files=[],
                errors=["broken state"],
            )

        monkeypatch.setattr(
            "agentkit.installer.install_agentkit",
            fake_install_agentkit,
        )

        exit_code = main([
            "install",
            "--project-key", "test-cli-project",
            "--project-name", "test-cli-project",
            "--project-root", str(tmp_path),
        ])

        assert exit_code == 1
        captured = capsys.readouterr()
        assert "Install failed: broken state" in captured.err

    def test_doctor_command(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """``doctor`` subcommand returns 0 and prints diagnostics."""
        exit_code = main(["doctor"])

        assert exit_code == 0
        captured = capsys.readouterr()
        assert "AgentKit Doctor" in captured.out
        assert "version:" in captured.out
        assert "git:" in captured.out

    def test_run_story_command(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """``run-story`` subcommand parses all required arguments."""
        exit_code = main([
            "run-story",
            "--story", "TEST-001",
            "--issue-nr", "42",
            "--owner", "testorg",
            "--repo", "testrepo",
            "--project-root", "/tmp/test",
        ])

        assert exit_code == 0
        captured = capsys.readouterr()
        assert "TEST-001" in captured.out
        assert "#42" in captured.out

    def test_serve_control_plane_command(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``serve-control-plane`` dispatches to the HTTP entrypoint."""
        captured: dict[str, object] = {}

        def fake_serve_control_plane(
            *,
            host: str,
            port: int,
            certfile: object,
            keyfile: object | None,
        ) -> None:
            captured["host"] = host
            captured["port"] = port
            captured["certfile"] = str(certfile)
            captured["keyfile"] = str(keyfile) if keyfile is not None else None

        monkeypatch.setattr(
            "agentkit.control_plane.serve_control_plane",
            fake_serve_control_plane,
        )

        exit_code = main([
            "serve-control-plane",
            "--host",
            "0.0.0.0",
            "--port",
            "9910",
            "--certfile",
            "tls/control-plane.pem",
            "--keyfile",
            "tls/control-plane.key",
        ])

        assert exit_code == 0
        assert captured == {
            "host": "0.0.0.0",
            "port": 9910,
            "certfile": str(PurePath("tls/control-plane.pem")),
            "keyfile": str(PurePath("tls/control-plane.key")),
        }
