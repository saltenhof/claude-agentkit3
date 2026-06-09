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

    def test_exit_story_command_dispatches_with_required_story_reason(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict[str, object] = {}

        def fake_exit_story(args: SimpleNamespace, cli_args: list[str]) -> int:
            captured["story"] = args.story
            captured["reason"] = args.reason
            captured["note"] = args.note
            captured["cli_args"] = cli_args
            return 0

        monkeypatch.setattr("agentkit.cli.main._cmd_exit_story", fake_exit_story)

        exit_code = main([
            "exit-story",
            "--story",
            "AG3-073",
            "--reason",
            "solution_viability_requires_human_design",
            "--note",
            "handoff",
        ])

        assert exit_code == 0
        assert captured["story"] == "AG3-073"
        assert captured["reason"] == "solution_viability_requires_human_design"
        assert captured["note"] == "handoff"

    def test_exit_story_requires_story_and_reason(self) -> None:
        with pytest.raises(SystemExit):
            main(["exit-story", "--story", "AG3-073"])

    def test_watch_worker_command_dispatches(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict[str, object] = {}

        def fake_watch_worker(args: SimpleNamespace) -> int:
            captured["story_id"] = args.story_id
            captured["project_root"] = args.project_root
            return 0

        monkeypatch.setattr("agentkit.cli.main._cmd_watch_worker", fake_watch_worker)

        exit_code = main([
            "watch-worker",
            "AG3-080",
            "--project-root",
            "T:/codebase/claude-agentkit3",
        ])

        assert exit_code == 0
        assert captured == {
            "story_id": "AG3-080",
            "project_root": "T:/codebase/claude-agentkit3",
        }

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
            # AG3-039: github coordinates are MANDATORY for CP 7 registration.
            "--github-owner", "acme",
            "--github-repo", "test-cli-project",
            # AG3-052: conscious Sonar opt-out (no live Sonar in this test);
            # FK-03 §3 default would be available:true => CP 10d fail-closed.
            "--no-sonarqube-available",
            # AG3-056 (FIX-5): conscious CI opt-out (no live Jenkins in this
            # test); default would be available:true => CI preflight fail-closed.
            "--no-ci-available",
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
                "--github-owner", "acme",
                "--github-repo", "test",
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
            "--github-owner", "acme",
            "--github-repo", "test-cli-project",
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
            "--github-owner", "acme",
            "--github-repo", "test-cli-project",
        ])

        assert exit_code == 1
        captured = capsys.readouterr()
        assert "BundleNotFound" in captured.err
        # No partial install: no harness skill bind points were created.
        assert not (tmp_path / ".claude" / "skills").exists()
        assert not (tmp_path / ".codex" / "skills").exists()

    def test_install_fails_closed_without_github_coordinates(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """AG3-039 R5 FAIL-CLOSED: ``install`` without ``--github-owner``/
        ``--github-repo`` AND no derivable origin remote aborts with exit 1 and a
        clear message — it never silently produces an UNREGISTERED install.

        The origin-remote derivation is stubbed to ``None`` so the test does not
        depend on the ambient git state of ``tmp_path`` (which has no repo here,
        but the stub makes the precondition explicit and platform-independent).
        """
        monkeypatch.setattr(
            "agentkit.installer.github_coordinates.derive_github_coordinates",
            lambda _root: None,
        )
        exit_code = main([
            "install",
            "--project-key", "test-cli-project",
            "--project-name", "test-cli-project",
            "--project-root", str(tmp_path),
        ])

        assert exit_code == 1
        captured = capsys.readouterr()
        assert "MissingGithubCoordinates" in captured.err
        assert "--github-owner" in captured.err
        # FAIL-CLOSED before any write: nothing was scaffolded.
        assert not (tmp_path / ".agentkit").exists()
        assert not (tmp_path / ".claude" / "skills").exists()

    def test_install_fails_closed_on_whitespace_github_flags(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """AG3-039 R6 E-a: whitespace-only ``--github-*`` flags are truthy as
        raw strings but carry no GitHub identity. They must be treated as MISSING
        and fail closed BEFORE any scaffold is written — never sailing through to
        a late CP 7 failure after a neutral scaffold / project.yaml exists.
        """
        monkeypatch.setattr(
            "agentkit.installer.github_coordinates.derive_github_coordinates",
            lambda _root: None,
        )
        exit_code = main([
            "install",
            "--project-key", "test-cli-project",
            "--project-name", "test-cli-project",
            "--project-root", str(tmp_path),
            "--github-owner", "   ",
            "--github-repo", "   ",
        ])

        assert exit_code == 1
        captured = capsys.readouterr()
        assert "MissingGithubCoordinates" in captured.err
        # FAIL-CLOSED before any write: no scaffold was created.
        assert not (tmp_path / ".agentkit").exists()
        assert not (tmp_path / ".claude" / "skills").exists()

    def test_install_fails_closed_on_invalid_github_flags(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """AG3-039 R6 E-b: a malformed owner/repo on the flags (here a
        path-traversal token) is rejected fail-closed BEFORE any scaffold write
        — the invalid coordinate is never persisted into project_registry.
        """
        exit_code = main([
            "install",
            "--project-key", "test-cli-project",
            "--project-name", "test-cli-project",
            "--project-root", str(tmp_path),
            "--github-owner", "..",
            "--github-repo", "ok-repo",
        ])

        assert exit_code == 1
        captured = capsys.readouterr()
        assert "InvalidGithubCoordinates" in captured.err
        # FAIL-CLOSED before any write: no scaffold was created.
        assert not (tmp_path / ".agentkit").exists()

    def test_install_derives_github_coordinates_from_origin_remote(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """AG3-039 R5 FALLBACK: when the flags are omitted, the coordinates are
        derived from the project's ``origin`` remote and reach ``InstallConfig``.

        ``install_agentkit`` is stubbed to capture the resolved config (this test
        targets the CLI resolution, not the full install path).
        """
        captured_cfg: dict[str, object] = {}

        def fake_install_agentkit(config: object) -> SimpleNamespace:
            captured_cfg["github_owner"] = config.github_owner  # type: ignore[attr-defined]
            captured_cfg["github_repo"] = config.github_repo  # type: ignore[attr-defined]
            return SimpleNamespace(success=True, created_files=[], errors=[])

        monkeypatch.setattr(
            "agentkit.installer.install_agentkit",
            fake_install_agentkit,
        )
        monkeypatch.setattr(
            "agentkit.installer.github_coordinates.derive_github_coordinates",
            lambda _root: ("derived-org", "derived-repo"),
        )

        exit_code = main([
            "install",
            "--project-key", "test-cli-project",
            "--project-name", "test-cli-project",
            "--project-root", str(tmp_path),
        ])

        assert exit_code == 0
        assert captured_cfg == {
            "github_owner": "derived-org",
            "github_repo": "derived-repo",
        }

    def test_install_flags_take_precedence_over_origin_remote(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """AG3-039 R5: explicit ``--github-*`` flags win over the origin remote."""
        captured_cfg: dict[str, object] = {}

        def fake_install_agentkit(config: object) -> SimpleNamespace:
            captured_cfg["github_owner"] = config.github_owner  # type: ignore[attr-defined]
            captured_cfg["github_repo"] = config.github_repo  # type: ignore[attr-defined]
            return SimpleNamespace(success=True, created_files=[], errors=[])

        monkeypatch.setattr(
            "agentkit.installer.install_agentkit",
            fake_install_agentkit,
        )
        monkeypatch.setattr(
            "agentkit.installer.github_coordinates.derive_github_coordinates",
            lambda _root: ("derived-org", "derived-repo"),
        )

        exit_code = main([
            "install",
            "--project-key", "test-cli-project",
            "--project-name", "test-cli-project",
            "--project-root", str(tmp_path),
            "--github-owner", "flag-org",
            "--github-repo", "flag-repo",
        ])

        assert exit_code == 0
        assert captured_cfg == {
            "github_owner": "flag-org",
            "github_repo": "flag-repo",
        }

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
            "--github-owner", "acme",  # AG3-039: mandatory CP 7 coordinates
            "--github-repo", "test-cli-project",
            "--no-sonarqube-available",  # AG3-052: conscious opt-out, no live Sonar
            "--no-ci-available",  # AG3-056: conscious opt-out, no live Jenkins
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
