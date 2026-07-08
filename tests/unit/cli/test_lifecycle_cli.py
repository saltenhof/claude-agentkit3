"""Unit tests for the install-trinity lifecycle CLI verbs (AG3-122).

Covers the pure dispatch/flag logic: serve profiles share ONE implementation
with the ``serve-control-plane`` alias (incl. the 9080->9702 port-default
migration and cert/key compatibility), the ``update`` fail-closed path, and the
retirement of the level-conflating ``install``/``uninstall`` generics.
"""

from __future__ import annotations

import subprocess
from pathlib import Path, PurePath
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.cli.main import main

if TYPE_CHECKING:
    from collections.abc import Mapping


def _capture_serve(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    """Patch the single control-plane entrypoint and capture its call args."""
    captured: dict[str, object] = {}

    def fake_serve_control_plane(
        *, host: str, port: int, certfile: object, keyfile: object | None
    ) -> None:
        captured["host"] = host
        captured["port"] = port
        captured["certfile"] = str(certfile)
        captured["keyfile"] = str(keyfile) if keyfile is not None else None

    monkeypatch.setattr(
        "agentkit.backend.control_plane.http.serve_control_plane",
        fake_serve_control_plane,
    )
    return captured


class TestServe:
    def test_serve_project_api_default_port_9702(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured = _capture_serve(monkeypatch)
        exit_code = main(["serve", "--project-api", "--certfile", "tls/cp.pem"])
        assert exit_code == 0
        assert captured["port"] == 9702
        assert captured["certfile"] == str(PurePath("tls/cp.pem"))

    def test_serve_ui_bff_default_port_9701(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured = _capture_serve(monkeypatch)
        exit_code = main(["serve", "--ui-bff", "--certfile", "tls/cp.pem"])
        assert exit_code == 0
        assert captured["port"] == 9701

    def test_serve_explicit_port_overrides_profile_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured = _capture_serve(monkeypatch)
        main(["serve", "--project-api", "--port", "9999", "--certfile", "tls/cp.pem"])
        assert captured["port"] == 9999

    def test_serve_requires_a_profile(self) -> None:
        with pytest.raises(SystemExit):
            main(["serve", "--certfile", "tls/cp.pem"])

    def test_serve_profiles_are_mutually_exclusive(self) -> None:
        with pytest.raises(SystemExit):
            main(["serve", "--ui-bff", "--project-api", "--certfile", "tls/cp.pem"])

    def test_alias_delegates_to_same_impl_with_port_migration_and_cert_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The retired ``serve-control-plane`` alias funnels through the SAME serve
        implementation as ``serve --project-api`` (no second transport path), with
        the 9080->9702 port-default migration and cert/key flags intact."""
        alias_args = _capture_serve(monkeypatch)
        main([
            "serve-control-plane",
            "--certfile",
            "tls/cp.pem",
            "--keyfile",
            "tls/cp.key",
        ])
        # Port default migrated from the legacy 9080 to the Project-API 9702.
        assert alias_args["port"] == 9702
        assert alias_args["certfile"] == str(PurePath("tls/cp.pem"))
        assert alias_args["keyfile"] == str(PurePath("tls/cp.key"))

        serve_args = _capture_serve(monkeypatch)
        main([
            "serve",
            "--project-api",
            "--certfile",
            "tls/cp.pem",
            "--keyfile",
            "tls/cp.key",
        ])
        # The alias and the canonical profile produce identical serve calls: one
        # implementation, reached through a single ``run_serve`` seam.
        assert alias_args == serve_args


class TestUi:
    def test_ui_fails_closed_when_bundle_missing(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        missing = tmp_path / "no-dist"
        exit_code = main(["ui", "--dist-dir", str(missing)])
        assert exit_code == 1
        assert "UiBundleMissing" in capsys.readouterr().err

    def test_ui_starts_when_bundle_present(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        dist = tmp_path / "dist"
        dist.mkdir()
        (dist / "index.html").write_text("<html></html>", encoding="utf-8")
        captured: dict[str, object] = {}

        def fake_spa(*, host: str, port: int, dist_dir: Path) -> None:
            captured["host"] = host
            captured["port"] = port
            captured["dist_dir"] = dist_dir

        monkeypatch.setattr("agentkit.backend.cli.serve._serve_spa", fake_spa)
        exit_code = main(["ui", "--dist-dir", str(dist)])
        assert exit_code == 0
        assert captured["port"] == 9700

    @pytest.mark.parametrize("host", ["0.0.0.0", "192.168.0.20"])
    def test_serve_spa_rejects_non_loopback_cleartext_bind(
        self, host: str, tmp_path: Path
    ) -> None:
        from agentkit.backend.cli.serve import UiBindHostError, _serve_spa

        with pytest.raises(UiBindHostError, match="restricted to loopback"):
            _serve_spa(host=host, port=9700, dist_dir=tmp_path)

    @pytest.mark.parametrize("host", ["127.0.0.1", "localhost"])
    def test_serve_spa_allows_loopback_cleartext_bind(
        self, host: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from agentkit.backend.cli.serve import _serve_spa

        calls: list[tuple[str, object]] = []

        class FakeThreadingHTTPServer:
            def __init__(self, server_address: tuple[str, int], handler: object) -> None:
                self.server_address = server_address
                self.handler = handler
                calls.append(("bind", server_address))

            def serve_forever(self) -> None:
                calls.append(("serve_forever", self.server_address))

            def server_close(self) -> None:
                calls.append(("server_close", self.server_address))

        monkeypatch.setattr("http.server.ThreadingHTTPServer", FakeThreadingHTTPServer)
        _serve_spa(host=host, port=9700, dist_dir=tmp_path)
        assert calls == [
            ("bind", (host, 9700)),
            ("serve_forever", (host, 9700)),
            ("server_close", (host, 9700)),
        ]


class TestUpdate:
    def _patch_reader(
        self, monkeypatch: pytest.MonkeyPatch, window: Mapping[str, object]
    ) -> None:
        def fake_factory(base_url: str, *, skill_bundle_version: object = None):  # type: ignore[no-untyped-def]
            def _read() -> Mapping[str, object]:
                return window

            return _read

        monkeypatch.setattr(
            "agentkit.backend.bootstrap.composition_root.build_compat_window_reader",
            fake_factory,
        )

    def test_update_fail_closed_when_local_runtime_below_min(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._patch_reader(
            monkeypatch,
            {
                "agent_runtime": {
                    "min": "9.0.0",
                    "max": "9.9.9",
                    "recommended": "9.0.0",
                    "blocked": [],
                },
                "wire": {"min": "1", "max": "1", "recommended": "1", "blocked": []},
            },
        )
        exit_code = main(["update", "--base-url", "https://core.example"])
        assert exit_code == 1
        assert "blocked" in capsys.readouterr().err

    def test_update_warning_emits_reinstall_hint(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._patch_reader(
            monkeypatch,
            {
                "agent_runtime": {
                    "min": "0.0.1",
                    "max": "9.9.9",
                    "recommended": "9.0.0",
                    "blocked": [],
                },
                "wire": {"min": "1", "max": "1", "recommended": "1", "blocked": []},
            },
        )
        exit_code = main(["update", "--base-url", "https://core.example"])
        assert exit_code == 0
        # The §10.2.8 re-install obligation is surfaced.
        assert "restart running harness sessions" in capsys.readouterr().out


class TestDetachAndDecommissionDispatch:
    def test_detach_cli_dispatches_and_reports(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        project = tmp_path / "proj"
        (project / ".agentkit").mkdir(parents=True)
        exit_code = main(["detach", "--project-root", str(project)])
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "removed_bindings" in out
        assert not (project / ".agentkit").exists()

    def test_detach_cli_reports_preserved_foreign_files(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """F3 regression: the CLI JSON output reports ``preserved_foreign_files``.

        ``detach_project`` preserves a foreign ``.codex/config.toml`` (D5) and
        returns it on ``DetachResult.preserved_foreign_files``, but the operator
        only learned of removals — the preserve+report intent was half-defeated.
        The CLI now surfaces the preserved foreign files in its payload.
        """
        import json

        project = tmp_path / "proj"
        (project / ".codex").mkdir(parents=True)
        (project / ".codex" / "config.toml").write_text(
            "# foreign operator config, not AK3\n[foreign]\nkeep = true\n",
            encoding="utf-8",
        )

        exit_code = main(["detach", "--project-root", str(project)])

        assert exit_code == 0
        payload = json.loads(capsys.readouterr().out)
        assert str(PurePath(".codex/config.toml")) in payload["preserved_foreign_files"]
        # The foreign file itself was preserved on disk (never deleted wholesale).
        assert (project / ".codex" / "config.toml").is_file()

    def test_detach_cli_fails_closed_on_missing_root(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = main(["detach", "--project-root", str(tmp_path / "nope")])
        assert exit_code == 1
        assert "ProjectRootMissing" in capsys.readouterr().err

    def test_decommission_requires_a_level(self) -> None:
        with pytest.raises(SystemExit):
            main(["decommission"])

    def test_decommission_machine_cli_warns_orphaned(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        store = tmp_path / "bundles"
        (store / "1.0.0").mkdir(parents=True)
        exit_code = main([
            "decommission",
            "--machine",
            "--bundle-store-root",
            str(store),
            "--bundle-version",
            "1.0.0",
            "--pinned-project",
            "proj-a=1.0.0=/p/a",
        ])
        assert exit_code == 0
        out = capsys.readouterr()
        assert "orphaned" in out.err.lower()
        assert not (store / "1.0.0").exists()

    def test_decommission_core_cli_aborts_without_confirm(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = main(["decommission", "--core"])
        assert exit_code == 1
        assert "Precondition" in capsys.readouterr().err

    def test_decommission_core_cli_runs_with_confirm_and_export(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # A real (empty) SQLite backend so the default exporter reads the
        # canonical state (real, empty export — no fake manifest).
        from agentkit.backend.state_backend.store import facade

        monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
        monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
        monkeypatch.setenv("AGENTKIT_STORE_DIR", str(tmp_path))
        monkeypatch.chdir(tmp_path)
        facade.reset_backend_cache_for_tests()
        # Stub the teardown subprocess at the boundary (no Docker daemon in CI) —
        # the PRODUCTIVE default controller still executes the real command path.
        teardown_calls: list[tuple[str, ...]] = []

        def fake_run(
            argv: list[str], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            teardown_calls.append(tuple(argv))
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

        monkeypatch.setattr("agentkit.backend.cli.lifecycle.subprocess.run", fake_run)

        export_dir = tmp_path / "export"
        try:
            exit_code = main([
                "decommission",
                "--core",
                "--confirm",
                "--export-dir",
                str(export_dir),
            ])
        finally:
            facade.reset_backend_cache_for_tests()
        assert exit_code == 0
        # The default exporter wrote REAL per-record-class artifacts + a manifest.
        assert (export_dir / "state-backend-export-manifest.json").is_file()
        assert (export_dir / "audit-trail.jsonl").is_file()
        # The default controller actually executed the approved teardown command.
        assert teardown_calls == [("docker", "compose", "down")]
        assert "db_volume_preserved" in capsys.readouterr().out


class TestGenericsRetired:
    def test_uninstall_is_deprecated_alias_for_detach(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = main(["uninstall", "--project-root", str(tmp_path)])
        assert exit_code == 0
        out = capsys.readouterr()
        assert "deprecated" in out.err.lower()
        assert "detach" in out.err.lower()
        assert "uninstalled" in out.out.lower()

    def test_install_is_deprecated_and_points_to_level_verbs(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # No github coordinates -> install fails closed, but the deprecation
        # banner naming the level-specific verbs must already have been emitted.
        exit_code = main([
            "install",
            "--project-key",
            "k",
            "--project-name",
            "n",
            "--project-root",
            str(tmp_path),
        ])
        assert exit_code == 1
        err = capsys.readouterr().err.lower()
        assert "deprecated" in err
        assert "register-project" in err

    def test_each_level_has_its_own_verb(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The level semantics are no longer conflated: every install-trinity
        level owns a distinct verb and the generics are explicitly deprecated."""
        # ``main([])`` prints the full help (no SystemExit, unlike ``--help``).
        assert main([]) == 0
        help_text = capsys.readouterr().out
        for verb in ("serve", "ui", "update", "detach", "decommission", "register-project"):
            assert verb in help_text
        # The generics survive only as explicitly deprecated aliases (argparse may
        # wrap the help text, so assert on the stable tokens, not the full line).
        assert "deprecated" in help_text
        assert "register-project" in help_text


class TestInstallConvergence:
    """The deprecated ``install`` alias converges on the SINGLE checkpoint engine.

    ``install`` is NOT a divergent installer path: ``install_agentkit`` delegates
    to ``run_checkpoint_install`` — the exact engine ``register-project`` uses.
    This locks the single-engine invariant: both verbs reach
    ``run_checkpoint_install`` (FK-10 §2.1.5 / §10.2.0).
    """

    def test_install_and_register_both_reach_run_checkpoint_install(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[object] = []

        class _FakeResult:
            success = True
            created_files: tuple[str, ...] = ()
            errors: tuple[str, ...] = ()

        def spy(config: object, *, mode: object = None) -> _FakeResult:
            calls.append(mode)
            return _FakeResult()

        # Both cmd_install (via install_agentkit) and _cmd_register_project import
        # run_checkpoint_install from THIS module — the single checkpoint engine.
        monkeypatch.setattr(
            "agentkit.backend.installer.bootstrap_checkpoints.orchestrator."
            "run_checkpoint_install",
            spy,
        )
        common = [
            "--project-key",
            "demo-key",
            "--project-name",
            "Demo",
            "--project-root",
            str(tmp_path),
            "--github-owner",
            "octo",
            "--github-repo",
            "repo",
            "--no-sonarqube-available",
            "--no-ci-available",
        ]

        assert main(["install", *common]) == 0
        assert main(["register-project", *common]) == 0
        # Both verbs funnelled into the one engine (no divergent installer path).
        assert len(calls) == 2
