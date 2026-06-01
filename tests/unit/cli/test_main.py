"""Unit tests for the AgentKit CLI entrypoint.

Tests the ``main()`` function from ``agentkit.cli.main`` to verify
that all subcommands parse correctly and return the expected exit codes.
"""

from __future__ import annotations

import tempfile
from pathlib import Path, PurePath
from types import SimpleNamespace

import pytest

from agentkit.cli.main import main
from agentkit.skills import create_directory_link, is_directory_link


def _directory_links_supported() -> bool:
    """Probe the production link layer (symlink on POSIX, junction on Windows;
    the junction needs no Developer Mode, so this is True on every supported
    platform — the probe only guards an exotic filesystem)."""
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "src"
        src.mkdir()
        link = Path(d) / "link"
        try:
            create_directory_link(link, src)
            return True
        except OSError:
            return False


_LINKS_AVAILABLE = _directory_links_supported()


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

    @pytest.mark.skipif(
        not _LINKS_AVAILABLE,
        reason="Filesystem supports neither symlinks nor directory junctions",
    )
    def test_install_command(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``install`` subcommand creates .agentkit/ in target project.

        AG3-048 (Codex-r3 ERROR 1): a normal install binds the four mandatory
        skills. The success path is proven by REAL code — the default-built
        ``SkillBundleStore`` discovers the four SHIPPED bundles from the
        packaged resources (no monkeypatch crutch). Only the SQLite backend
        is enabled for the binding-repository persistence.

        Runs on every supported platform (the Windows junction needs no
        Developer Mode): the assertion below proves each of the four mandatory
        skills is REALLY bound — both harness links (``.claude/skills`` +
        ``.codex/skills``, symlink or junction) AND the persisted
        ``skill_bindings`` row exist. A weaker ``.agentkit``/``project.yaml``
        check would not prove binding.
        """
        from agentkit.installer.runner import MANDATORY_SKILLS
        from agentkit.skills import Skills
        from agentkit.skills.binding import SkillLifecycleStatus
        from agentkit.skills.bundle_store import SkillBundleStore
        from agentkit.state_backend.store.skill_binding_repository import (
            StateBackendSkillBindingRepository,
        )

        monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
        exit_code = main([
            "install",
            "--project-key", "test-cli-project",
            "--project-name", "test-cli-project",
            "--project-root", str(tmp_path),
        ])

        assert exit_code == 0
        assert (tmp_path / ".agentkit").is_dir()
        assert (tmp_path / ".agentkit" / "config" / "project.yaml").exists()

        # REAL binding proof: links for all four mandatory skills in BOTH
        # harness bind points (symlink on POSIX, junction on Windows), plus a
        # VERIFIED persisted binding for each.
        skills = Skills(
            bundle_store=SkillBundleStore(),
            binding_repo=StateBackendSkillBindingRepository(tmp_path),
        )
        for skill_name in MANDATORY_SKILLS:
            claude_link = tmp_path / ".claude" / "skills" / skill_name
            codex_link = tmp_path / ".codex" / "skills" / skill_name
            assert is_directory_link(claude_link), f"missing .claude link for {skill_name}"
            assert is_directory_link(codex_link), f"missing .codex link for {skill_name}"
            binding = skills.resolve_binding(tmp_path, skill_name)
            assert binding is not None, f"no persisted binding for {skill_name}"
            assert binding.status == SkillLifecycleStatus.VERIFIED

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

    def test_install_command_fails_closed_without_provisioned_bundles(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A normal CLI install with an UNPROVISIONED systemwide skill store
        fails closed (exit 1, BundleNotFound) — it does NOT silently produce an
        install without the four mandatory skills (AG3-048 ERROR 1, AC#5/AC#7).
        """
        from agentkit.skills.bundle_store import SKILL_BUNDLE_STORE_ENV

        # Point the default systemwide store at an empty dir (no bundles).
        monkeypatch.setenv(
            SKILL_BUNDLE_STORE_ENV, str(tmp_path / "empty-system-store")
        )
        exit_code = main([
            "install",
            "--project-key", "test-cli-project",
            "--project-name", "test-cli-project",
            "--project-root", str(tmp_path),
        ])

        assert exit_code == 1
        captured = capsys.readouterr()
        assert "BundleNotFound" in captured.err
        # No partial install: no harness skill bind points were created.
        assert not (tmp_path / ".claude" / "skills").exists()
        assert not (tmp_path / ".codex" / "skills").exists()

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

    @pytest.mark.skipif(
        not _LINKS_AVAILABLE,
        reason="Filesystem supports neither symlinks nor directory junctions",
    )
    def test_uninstall_command(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``uninstall`` removes AgentKit harness settings."""
        monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
        install_code = main([
            "install",
            "--project-key", "test-cli-project",
            "--project-name", "test-cli-project",
            "--project-root", str(tmp_path),
        ])

        exit_code = main(["uninstall", "--project-root", str(tmp_path)])

        assert install_code == 0
        assert exit_code == 0
        assert not (tmp_path / ".claude" / "settings.json").exists()
        assert not (tmp_path / ".codex" / "config.toml").exists()
        captured = capsys.readouterr()
        assert "uninstalled" in captured.out.lower()

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
            "agentkit.control_plane.http.serve_control_plane",
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
