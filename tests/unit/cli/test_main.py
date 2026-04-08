"""Unit tests for the AgentKit CLI entrypoint.

Tests the ``main()`` function from ``agentkit.cli.main`` to verify
that all subcommands parse correctly and return the expected exit codes.
"""

from __future__ import annotations

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
                "--project-name", "test",
                "--project-root", str(tmp_path / "nonexistent"),
            ])

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
