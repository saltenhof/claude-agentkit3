"""Unit tests for the AgentKit CLI entrypoint.

Tests the ``main()`` function from ``agentkit.backend.cli.main`` to verify
that all subcommands parse correctly and return the expected exit codes.
"""

from __future__ import annotations

import tempfile
from pathlib import Path, PurePath
from types import SimpleNamespace

import pytest
from tests.fixtures.git_repo import ensure_git_repo

from agentkit.backend.cli.main import main
from agentkit.backend.skills import create_directory_link, is_directory_link


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


@pytest.fixture(autouse=True)
def _stub_repo_existence_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace CP 2's LIVE ``gh`` repo probe for the CLI unit tests.

    ``register-project`` wires the productive :class:`GhCliRepoExistenceProbe`,
    which shells out to ``gh``. These tests target CLI wiring, not GitHub
    reachability, and the only allowed fake boundary is that external client
    (MOCKS/STUBS rule 2). CP 2's fail-closed behaviour on a MISSING repo has its
    own dedicated installer tests.
    """
    from agentkit.backend.installer.repo_probe import RepoProbeResult

    class _PresentRepoProbe:
        def __call__(self, owner: str, repo: str) -> RepoProbeResult:
            return RepoProbeResult(exists=True, detail=f"{owner}/{repo} present (test stub)")

    monkeypatch.setattr(
        "agentkit.backend.installer.repo_probe.GhCliRepoExistenceProbe",
        _PresentRepoProbe,
    )


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
        self,
        capsys: pytest.CaptureFixture[str],
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

        monkeypatch.setattr("agentkit.backend.cli.main._cmd_exit_story", fake_exit_story)

        exit_code = main(
            [
                "exit-story",
                "--story",
                "AG3-073",
                "--reason",
                "solution_viability_requires_human_design",
                "--note",
                "handoff",
            ]
        )

        assert exit_code == 0
        assert captured["story"] == "AG3-073"
        assert captured["reason"] == "solution_viability_requires_human_design"
        assert captured["note"] == "handoff"

    def test_exit_story_requires_story_and_reason(self) -> None:
        with pytest.raises(SystemExit):
            main(["exit-story", "--story", "AG3-073"])

    def test_split_story_command_dispatches_with_required_params(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict[str, object] = {}

        def fake_split_story(args: SimpleNamespace, cli_args: list[str]) -> int:
            captured["story"] = args.story
            captured["plan"] = args.plan
            captured["reason"] = args.reason
            return 0

        monkeypatch.setattr("agentkit.backend.cli.main._cmd_split_story", fake_split_story)

        exit_code = main(
            [
                "split-story",
                "--story",
                "AG3-042",
                "--plan",
                "plan.json",
                "--reason",
                "scope explosion",
            ]
        )

        assert exit_code == 0
        assert captured["story"] == "AG3-042"
        assert captured["plan"] == "plan.json"
        assert captured["reason"] == "scope explosion"

    def test_split_story_requires_story_plan_reason(self) -> None:
        with pytest.raises(SystemExit):
            main(["split-story", "--story", "AG3-042"])

    def test_reset_story_command_dispatches_with_required_params(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict[str, object] = {}

        def fake_reset_story(args: SimpleNamespace) -> int:
            captured["story"] = args.story
            captured["reason"] = args.reason
            captured["escalation_ref"] = args.escalation_ref
            captured["dry_run"] = args.dry_run
            captured["force"] = args.force
            return 0

        monkeypatch.setattr("agentkit.backend.cli.main._cmd_reset_story", fake_reset_story)

        exit_code = main(
            [
                "reset-story",
                "--story",
                "AG3-071",
                "--reason",
                "irreparable merge conflict",
                "--escalation-ref",
                "ESC-9",
                "--dry-run",
            ]
        )

        assert exit_code == 0
        assert captured["story"] == "AG3-071"
        assert captured["reason"] == "irreparable merge conflict"
        assert captured["escalation_ref"] == "ESC-9"
        assert captured["dry_run"] is True
        assert captured["force"] is False

    def test_reset_story_requires_story_and_reason(self) -> None:
        with pytest.raises(SystemExit):
            main(["reset-story", "--story", "AG3-071"])

    def test_reset_story_dry_run_reports_domains_without_mutation(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """AC2: --dry-run prints the planned purge domains and does not mutate."""
        import json as _json

        from agentkit.backend.story_reset import (
            PlannedPurge,
            ResetPurgeDomain,
            StoryResetService,
        )

        monkeypatch.setenv("AGENTKIT_PROJECT_KEY", "ak3")

        class _DryRunService(StoryResetService):
            def __init__(self) -> None:  # bypass the heavy real wiring
                pass

            def request_reset(self, request: object) -> object:  # type: ignore[override]
                assert request.dry_run is True
                return PlannedPurge(
                    project_key="ak3",
                    story_id=request.story_id,
                    run_id="run-x",
                    reason=request.reason,
                    planned_domains=(
                        ResetPurgeDomain.RUNTIME_EXECUTION,
                        ResetPurgeDomain.READ_MODELS,
                    ),
                )

        monkeypatch.setattr(
            "agentkit.backend.bootstrap.composition_root.build_story_reset_service",
            lambda **_kw: _DryRunService(),
        )

        exit_code = main(
            [
                "reset-story",
                "--story",
                "AG3-071",
                "--reason",
                "irreparable",
                "--dry-run",
            ]
        )

        assert exit_code == 0
        out = _json.loads(capsys.readouterr().out.strip())
        assert out["mode"] == "dry-run"
        assert out["planned_domains"] == ["runtime_execution", "read_models"]

    def test_split_story_spec_command_succeeds_end_to_end(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Finding #2: the EXACT §54.6 command (only --story/--plan/--reason)
        succeeds end to end. The human-started CLI path IS the §54.4 approval, so
        the resolved principal is human_cli and the entry gate (AK2/AK5) holds —
        no hidden --ak3-principal-attest flag is required or accepted.

        Drives the REAL CLI -> real principal -> real StorySplitService ->
        real StoryService create/cancel/lineage. Only the storage seams
        (control-plane, dependency repo, export, superseded reindex) are
        in-memory; the productive split logic runs unchanged.
        """
        import json as _json

        from tests.unit.story_split.test_service import (
            _build_harness,
            _good_source_state,
        )

        from agentkit.backend.governance.principal_capabilities.principals import Principal

        # The hidden attestation flag must no longer exist on the split parser:
        # passing it is an argparse error (the bare interface is the contract).
        with pytest.raises(SystemExit):
            main(
                [
                    "split-story",
                    "--story",
                    "AK3-001",
                    "--plan",
                    "p.json",
                    "--reason",
                    "r",
                    "--ak3-principal-attest",
                    "human_cli",
                ]
            )

        harness = _build_harness(source_state_loader=_good_source_state)
        captured_principal: dict[str, object] = {}
        original_split = harness.split_service.split_story

        def _spy_split(request: object) -> object:
            captured_principal["principal"] = getattr(request, "principal", None)
            return original_split(request)  # type: ignore[arg-type]

        harness.split_service.split_story = _spy_split  # type: ignore[assignment]

        def _fake_build(**_kwargs: object) -> object:
            return harness.split_service

        monkeypatch.setattr(
            "agentkit.backend.bootstrap.composition_root.build_story_split_service",
            _fake_build,
        )
        monkeypatch.setenv("AGENTKIT_PROJECT_KEY", "ak3")
        monkeypatch.setenv("AGENTKIT_RUN_ID", "run-1")

        plan_path = tmp_path / "plan.json"
        plan_path.write_text(
            _json.dumps(
                {
                    "project_key": "ak3",
                    "source_story_id": "AK3-001",
                    "reason": "scope_explosion",
                    "successors": [
                        {"story_id": "AK3-107", "title": "Slice A", "scope_slice": "A"},
                        {"story_id": "AK3-108", "title": "Slice B", "scope_slice": "B"},
                    ],
                }
            ),
            encoding="utf-8",
        )

        exit_code = main(
            [
                "split-story",
                "--story",
                "AK3-001",
                "--plan",
                str(plan_path),
                "--reason",
                "scope explosion",
            ]
        )

        assert exit_code == 0
        # The CLI resolved the human_cli principal (the bare command IS approval).
        assert captured_principal["principal"] is Principal.HUMAN_CLI
        out = _json.loads(capsys.readouterr().out)
        assert out["status"] == "committed"
        assert out["resumed"] is False
        assert len(out["successor_ids"]) == 2
        # Source ended Cancelled via the administrative split-cancel path.
        source = harness.story_service.get_story("AK3-001")
        assert source is not None
        assert source.status.value == "Cancelled"

    def test_split_story_maps_an_unresolvable_vectordb_to_exit_one(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A fail-closed composition error must not surface as a traceback.

        ``build_story_split_service`` refuses to default the Weaviate endpoints
        (PO decision D-2). Refusing is right; leaving the exception uncaught at
        the CLI boundary is not — the documented contract is a controlled exit
        code with a message on stderr.
        """
        import json as _json

        from agentkit.integration_clients.vectordb.errors import VectorDbUnavailableError

        monkeypatch.setenv("AGENTKIT_PROJECT_KEY", "ak3")
        monkeypatch.setenv("AGENTKIT_RUN_ID", "run-1")

        def _refuse(**_kwargs: object) -> object:
            raise VectorDbUnavailableError("story split requires an explicit project root")

        monkeypatch.setattr(
            "agentkit.backend.bootstrap.composition_root.build_story_split_service",
            _refuse,
        )

        plan_path = tmp_path / "plan.json"
        plan_path.write_text(
            _json.dumps(
                {
                    "project_key": "ak3",
                    "source_story_id": "AK3-001",
                    "reason": "scope_explosion",
                    "successors": [
                        {"story_id": "AK3-107", "title": "Slice A", "scope_slice": "A"},
                        {"story_id": "AK3-108", "title": "Slice B", "scope_slice": "B"},
                    ],
                }
            ),
            encoding="utf-8",
        )

        exit_code = main(
            [
                "split-story",
                "--story",
                "AK3-001",
                "--plan",
                str(plan_path),
                "--reason",
                "scope explosion",
            ]
        )

        assert exit_code == 1
        assert "explicit project root" in capsys.readouterr().err

    def test_split_story_rejects_invalid_plan_before_mutation(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # AK2: an unreadable/invalid plan fails closed BEFORE the service builds.
        monkeypatch.setenv("AGENTKIT_PROJECT_KEY", "ak3")
        monkeypatch.setenv("AGENTKIT_RUN_ID", "run-1")
        monkeypatch.setenv("AGENTKIT_SESSION_ID", "sess-1")

        def _explode(**_kwargs: object) -> object:
            raise AssertionError("service must not be built for an invalid plan")

        monkeypatch.setattr(
            "agentkit.backend.bootstrap.composition_root.build_story_split_service",
            _explode,
        )
        bad_plan = tmp_path / "plan.json"
        bad_plan.write_text("not json {", encoding="utf-8")

        exit_code = main(["split-story", "--story", "AG3-042", "--plan", str(bad_plan), "--reason", "r"])

        assert exit_code == 1
        assert "InvalidPlan" in capsys.readouterr().err

    def test_watch_worker_command_dispatches(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict[str, object] = {}

        def fake_watch_worker(args: SimpleNamespace) -> int:
            captured["story_id"] = args.story_id
            captured["project_root"] = args.project_root
            return 0

        monkeypatch.setattr("agentkit.backend.cli.main._cmd_watch_worker", fake_watch_worker)

        exit_code = main(
            [
                "watch-worker",
                "AG3-080",
                "--project-root",
                "T:/codebase/claude-agentkit3",
            ]
        )

        assert exit_code == 0
        assert captured == {
            "story_id": "AG3-080",
            "project_root": "T:/codebase/claude-agentkit3",
        }

    @pytest.mark.skipif(
        not _LINKS_AVAILABLE,
        reason="Filesystem supports neither symlinks nor directory junctions",
    )
    def test_register_project_command(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``register-project`` creates .agentkit/ in target project.

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
        from agentkit.backend.installer.runner import MANDATORY_SKILLS
        from agentkit.backend.skills import Skills
        from agentkit.backend.skills.binding import SkillLifecycleStatus
        from agentkit.backend.skills.bundle_store import SkillBundleStore
        from agentkit.backend.state_backend.store.skill_binding_repository import (
            StateBackendSkillBindingRepository,
        )

        monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
        from tests.fixtures.vectordb_installer import (
            GRPC_ENDPOINT,
            HTTP_ENDPOINT,
            wire_ready_vectordb,
        )

        wire_ready_vectordb(monkeypatch)
        # CP 11 configures core.hooksPath on the target; real targets are git
        # repos, so provision one (else CP 11 aborts on a clean CI agent).
        ensure_git_repo(tmp_path)
        exit_code = main(
            [
                "register-project",
                "--project-key",
                "test-cli-project",
                "--project-name",
                "test-cli-project",
                "--project-root",
                str(tmp_path),
                "--weaviate-http-endpoint",
                HTTP_ENDPOINT,
                "--weaviate-grpc-endpoint",
                GRPC_ENDPOINT,
                # AG3-039: github coordinates are MANDATORY for CP 7 registration.
                "--github-owner",
                "acme",
                "--github-repo",
                "test-cli-project",
                # AG3-052: conscious Sonar opt-out (no live Sonar in this test);
                # FK-03 §3 default would be available:true => CP 10d fail-closed.
                "--no-sonarqube-available",
                # AG3-056 (FIX-5): conscious CI opt-out (no live Jenkins in this
                # test); default would be available:true => CI preflight fail-closed.
                "--no-ci-available",
            ]
        )

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
        assert "registered" in captured.out.lower()

    def test_register_project_nonexistent_root(
        self,
        tmp_path: Path,
    ) -> None:
        """``register-project`` into a non-existent directory fails closed (exit 1).

        The engine raises ``ProjectError``; the CLI boundary turns it into a
        clean non-zero exit with the reason on stderr instead of a traceback.
        """
        exit_code = main(
                [
                    "register-project",
                    "--project-key",
                    "test",
                    "--project-name",
                    "test",
                    "--project-root",
                    str(tmp_path / "nonexistent"),
                    "--github-owner",
                    "acme",
                    "--github-repo",
                    "test",
            ]
        )

        assert exit_code == 1

    def test_register_project_returns_failure_code(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """``register-project`` returns 1 when the checkpoint engine reports failure."""

        def fake_run_checkpoint_install(_config: object, *, mode: object = None) -> SimpleNamespace:
            return SimpleNamespace(
                success=False,
                created_files=[],
                errors=["broken state"],
                checkpoint_results=[],
            )

        monkeypatch.setattr(
            "agentkit.backend.installer.bootstrap_checkpoints.orchestrator.run_checkpoint_install",
            fake_run_checkpoint_install,
        )

        exit_code = main(
            [
                "register-project",
                "--project-key",
                "test-cli-project",
                "--project-name",
                "test-cli-project",
                "--project-root",
                str(tmp_path),
                "--github-owner",
                "acme",
                "--github-repo",
                "test-cli-project",
            ]
        )

        # A FAILED engine result is a non-zero exit, and the failing checkpoint
        # summary reaches the operator instead of a silent success.
        assert exit_code == 1
        assert "register" in capsys.readouterr().out.lower()

    def test_register_project_fails_closed_without_provisioned_bundles(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A normal CLI install with an UNPROVISIONED systemwide skill store
        fails closed (exit 1, BundleNotFound) — it does NOT silently produce an
        install without the four mandatory skills (AG3-048 ERROR 1, AC#5/AC#7).
        """
        from tests.fixtures.vectordb_installer import (
            GRPC_ENDPOINT,
            HTTP_ENDPOINT,
            wire_ready_vectordb,
        )

        from agentkit.backend.skills.bundle_store import SKILL_BUNDLE_STORE_ENV

        # Point the default systemwide store at an empty dir (no bundles).
        wire_ready_vectordb(monkeypatch)
        monkeypatch.setenv(SKILL_BUNDLE_STORE_ENV, str(tmp_path / "empty-system-store"))
        exit_code = main(
            [
                "register-project",
                "--project-key",
                "test-cli-project",
                "--project-name",
                "test-cli-project",
                "--project-root",
                str(tmp_path),
                "--weaviate-http-endpoint",
                HTTP_ENDPOINT,
                "--weaviate-grpc-endpoint",
                GRPC_ENDPOINT,
                "--github-owner",
                "acme",
                "--github-repo",
                "test-cli-project",
            ]
        )

        assert exit_code == 1
        captured = capsys.readouterr()
        assert "not found in the systemwide store" in captured.err
        assert "no partial install" in captured.err
        # No partial install: no harness skill bind points were created.
        assert not (tmp_path / ".claude" / "skills").exists()
        assert not (tmp_path / ".codex" / "skills").exists()

    def test_register_project_fails_closed_without_github_coordinates(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """AG3-039 R5 FAIL-CLOSED: ``register-project`` without ``--github-owner``/
        ``--github-repo`` AND no derivable origin remote aborts with exit 1 and a
        clear message — it never silently produces an UNREGISTERED install.

        The origin-remote derivation is stubbed to ``None`` so the test does not
        depend on the ambient git state of ``tmp_path`` (which has no repo here,
        but the stub makes the precondition explicit and platform-independent).
        """
        monkeypatch.setattr(
            "agentkit.backend.installer.github_coordinates.derive_github_coordinates",
            lambda _root: None,
        )
        exit_code = main(
            [
                "register-project",
                "--project-key",
                "test-cli-project",
                "--project-name",
                "test-cli-project",
                "--project-root",
                str(tmp_path),
            ]
        )

        assert exit_code == 1
        captured = capsys.readouterr()
        assert "MissingGithubCoordinates" in captured.err
        assert "--github-owner" in captured.err
        # FAIL-CLOSED before any write: nothing was scaffolded.
        assert not (tmp_path / ".agentkit").exists()
        assert not (tmp_path / ".claude" / "skills").exists()

    def test_register_project_fails_closed_on_whitespace_github_flags(
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
            "agentkit.backend.installer.github_coordinates.derive_github_coordinates",
            lambda _root: None,
        )
        exit_code = main(
            [
                "register-project",
                "--project-key",
                "test-cli-project",
                "--project-name",
                "test-cli-project",
                "--project-root",
                str(tmp_path),
                "--github-owner",
                "   ",
                "--github-repo",
                "   ",
            ]
        )

        assert exit_code == 1
        captured = capsys.readouterr()
        assert "MissingGithubCoordinates" in captured.err
        # FAIL-CLOSED before any write: no scaffold was created.
        assert not (tmp_path / ".agentkit").exists()
        assert not (tmp_path / ".claude" / "skills").exists()

    def test_register_project_fails_closed_on_invalid_github_flags(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """AG3-039 R6 E-b: a malformed owner/repo on the flags (here a
        path-traversal token) is rejected fail-closed BEFORE any scaffold write
        — the invalid coordinate is never persisted into project_registry.
        """
        exit_code = main(
            [
                "register-project",
                "--project-key",
                "test-cli-project",
                "--project-name",
                "test-cli-project",
                "--project-root",
                str(tmp_path),
                "--github-owner",
                "..",
                "--github-repo",
                "ok-repo",
            ]
        )

        assert exit_code == 1
        captured = capsys.readouterr()
        assert "InvalidGithubCoordinates" in captured.err
        # FAIL-CLOSED before any write: no scaffold was created.
        assert not (tmp_path / ".agentkit").exists()

    def test_register_project_derives_github_coordinates_from_origin_remote(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """AG3-039 R5 FALLBACK: when the flags are omitted, the coordinates are
        derived from the project's ``origin`` remote and reach ``InstallConfig``.

        ``run_checkpoint_install`` is stubbed to capture the resolved config (this test
        targets the CLI resolution, not the full install path).
        """
        captured_cfg: dict[str, object] = {}

        def fake_run_checkpoint_install(config: object, *, mode: object = None) -> SimpleNamespace:
            captured_cfg["github_owner"] = config.github_owner  # type: ignore[attr-defined]
            captured_cfg["github_repo"] = config.github_repo  # type: ignore[attr-defined]
            return SimpleNamespace(success=True, created_files=[], errors=[], checkpoint_results=[])

        monkeypatch.setattr(
            "agentkit.backend.installer.bootstrap_checkpoints.orchestrator.run_checkpoint_install",
            fake_run_checkpoint_install,
        )
        monkeypatch.setattr(
            "agentkit.backend.installer.github_coordinates.derive_github_coordinates",
            lambda _root: ("derived-org", "derived-repo"),
        )

        exit_code = main(
            [
                "register-project",
                "--project-key",
                "test-cli-project",
                "--project-name",
                "test-cli-project",
                "--project-root",
                str(tmp_path),
            ]
        )

        assert exit_code == 0
        assert captured_cfg == {
            "github_owner": "derived-org",
            "github_repo": "derived-repo",
        }

    def test_register_project_flags_take_precedence_over_origin_remote(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """AG3-039 R5: explicit ``--github-*`` flags win over the origin remote."""
        captured_cfg: dict[str, object] = {}

        def fake_run_checkpoint_install(config: object, *, mode: object = None) -> SimpleNamespace:
            captured_cfg["github_owner"] = config.github_owner  # type: ignore[attr-defined]
            captured_cfg["github_repo"] = config.github_repo  # type: ignore[attr-defined]
            return SimpleNamespace(success=True, created_files=[], errors=[], checkpoint_results=[])

        monkeypatch.setattr(
            "agentkit.backend.installer.bootstrap_checkpoints.orchestrator.run_checkpoint_install",
            fake_run_checkpoint_install,
        )
        monkeypatch.setattr(
            "agentkit.backend.installer.github_coordinates.derive_github_coordinates",
            lambda _root: ("derived-org", "derived-repo"),
        )

        exit_code = main(
            [
                "register-project",
                "--project-key",
                "test-cli-project",
                "--project-name",
                "test-cli-project",
                "--project-root",
                str(tmp_path),
                "--github-owner",
                "flag-org",
                "--github-repo",
                "flag-repo",
            ]
        )

        assert exit_code == 0
        assert captured_cfg == {
            "github_owner": "flag-org",
            "github_repo": "flag-repo",
        }

    def test_doctor_command(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """``doctor`` subcommand returns 0 and prints diagnostics."""
        exit_code = main(["doctor", "--project-root", str(tmp_path)])

        assert exit_code == 0
        captured = capsys.readouterr()
        assert "AgentKit Doctor" in captured.out
        assert "project root:" in captured.out
        assert "project config:" in captured.out
        assert "version:" in captured.out
        assert "git:" in captured.out

    def test_register_project_engine_config_keeps_sonar_ci_available_by_default(self, tmp_path: Path) -> None:
        from agentkit.backend.cli.main import _build_engine_config

        cfg = _build_engine_config(
            SimpleNamespace(
                project_key="ak3",
                project_name="AgentKit 3",
                project_root=str(tmp_path),
                github_owner="saltenhof",
                github_repo="claude-agentkit3",
                default_project_structure=True,
                multi_repo=False,
                code_repo=[],
                sonarqube_available=True,
                ci_available=True,
            )
        )

        assert cfg is not None
        assert cfg.sonarqube_available is True
        assert cfg.ci_available is True

    def test_register_project_engine_config_requires_explicit_sonar_ci_opt_out(self, tmp_path: Path) -> None:
        from agentkit.backend.cli.main import _build_engine_config

        cfg = _build_engine_config(
            SimpleNamespace(
                project_key="ak3",
                project_name="AgentKit 3",
                project_root=str(tmp_path),
                github_owner="saltenhof",
                github_repo="claude-agentkit3",
                default_project_structure=True,
                multi_repo=False,
                code_repo=[],
                sonarqube_available=False,
                ci_available=False,
            )
        )

        assert cfg is not None
        assert cfg.sonarqube_available is False
        assert cfg.ci_available is False

    @pytest.mark.skipif(
        not _LINKS_AVAILABLE,
        reason="Filesystem supports neither symlinks nor directory junctions",
    )
    def test_detach_command(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``uninstall`` removes AgentKit harness settings."""
        monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
        from tests.fixtures.vectordb_installer import (
            GRPC_ENDPOINT,
            HTTP_ENDPOINT,
            wire_ready_vectordb,
        )

        wire_ready_vectordb(monkeypatch)
        # CP 11 configures core.hooksPath on the target; real targets are git
        # repos, so provision one (else CP 11 aborts on a clean CI agent).
        ensure_git_repo(tmp_path)
        install_code = main(
            [
                "register-project",
                "--project-key",
                "test-cli-project",
                "--project-name",
                "test-cli-project",
                "--project-root",
                str(tmp_path),
                "--weaviate-http-endpoint",
                HTTP_ENDPOINT,
                "--weaviate-grpc-endpoint",
                GRPC_ENDPOINT,
                "--github-owner",
                "acme",  # AG3-039: mandatory CP 7 coordinates
                "--github-repo",
                "test-cli-project",
                "--no-sonarqube-available",  # AG3-052: conscious opt-out, no live Sonar
                "--no-ci-available",  # AG3-056: conscious opt-out, no live Jenkins
            ]
        )

        exit_code = main(["detach", "--project-root", str(tmp_path)])

        assert install_code == 0
        assert exit_code == 0
        assert not (tmp_path / ".claude" / "settings.json").exists()
        assert not (tmp_path / ".codex" / "config.toml").exists()
        captured = capsys.readouterr()
        assert "removed_bindings" in captured.out

    def test_run_story_command(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """``run-story`` identifies the story via ``story_id`` (AG3-120, AC8).

        AK3 owns the story via ``story_id``; GitHub is only the code backend, so
        ``--issue-nr`` is no longer a parameter and the story is addressed by id.
        """
        exit_code = main(
            [
                "run-story",
                "--story",
                "TEST-001",
                "--owner",
                "testorg",
                "--repo",
                "testrepo",
                "--project-root",
                "/tmp/test",
            ]
        )

        assert exit_code == 0
        captured = capsys.readouterr()
        assert "TEST-001" in captured.out
        # The GitHub issue number is no longer rendered.
        assert "#42" not in captured.out

    def test_run_story_rejects_issue_nr_option(self) -> None:
        """AG3-120 AC8: ``--issue-nr`` is removed from the ``run-story`` adapter."""
        with pytest.raises(SystemExit):
            main(
                [
                    "run-story",
                    "--story",
                    "TEST-001",
                    "--issue-nr",
                    "42",
                    "--owner",
                    "testorg",
                    "--repo",
                    "testrepo",
                    "--project-root",
                    "/tmp/test",
                ]
            )

    def test_serve_project_api_command(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``serve --project-api`` dispatches to the HTTP entrypoint.

        The former ``serve-control-plane`` alias that also reached this seam is
        REMOVED (2026-08-02): it carried the dead ``9080`` port default.
        """
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
            "agentkit.backend.control_plane.http.serve_control_plane",
            fake_serve_control_plane,
        )

        exit_code = main(
            [
                "serve",
                "--project-api",
                "--host",
                "0.0.0.0",
                "--port",
                "9910",
                "--certfile",
                "tls/control-plane.pem",
                "--keyfile",
                "tls/control-plane.key",
            ]
        )

        assert exit_code == 0
        assert captured == {
            "host": "0.0.0.0",
            "port": 9910,
            "certfile": str(PurePath("tls/control-plane.pem")),
            "keyfile": str(PurePath("tls/control-plane.key")),
        }

    def test_upgrade_project_dispatches_register_mode(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``upgrade-project`` routes to the engine-driven upgrade entry (FIX 1).

        Proves the CLI is wired to ``run_checkpoint_upgrade`` (the engine-driven
        boundary control), the default mode is mutating ``register`` and the
        target version is forwarded.
        """
        from agentkit.backend.installer.checkpoint_engine.execution_mode import ExecutionMode

        captured: dict[str, object] = {}

        def fake_upgrade(project_root: Path, **kwargs: object) -> object:
            captured["project_root"] = project_root
            captured.update(kwargs)
            return SimpleNamespace(
                scenario=SimpleNamespace(scenario=SimpleNamespace(value="unchanged")),
                detail="ok",
                failed=False,
                failed_checkpoints=(),
            )

        monkeypatch.setattr("agentkit.backend.installer.upgrade.entry.run_checkpoint_upgrade", fake_upgrade)

        exit_code = main(
            [
                "upgrade-project",
                "--project-key",
                "demo",
                "--project-root",
                str(tmp_path),
                "--github-owner",
                "acme",
                "--github-repo",
                "demo",
                "--target-config-version",
                "4.0",
            ]
        )

        assert exit_code == 0
        assert captured["mode"] is ExecutionMode.REGISTER
        assert captured["target_config_version"] == "4.0"
        assert captured["project_key"] == "demo"

    def test_upgrade_project_dry_run_maps_to_dry_run_mode(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``--dry-run`` maps to the read-only ``dry_run`` mode (no mutation)."""
        from agentkit.backend.installer.checkpoint_engine.execution_mode import ExecutionMode

        captured: dict[str, object] = {}

        def fake_upgrade(project_root: Path, **kwargs: object) -> object:
            captured.update(kwargs)
            return SimpleNamespace(
                scenario=SimpleNamespace(scenario=SimpleNamespace(value="unchanged")),
                detail="planned",
                failed=False,
                failed_checkpoints=(),
            )

        monkeypatch.setattr("agentkit.backend.installer.upgrade.entry.run_checkpoint_upgrade", fake_upgrade)

        exit_code = main(
            [
                "upgrade-project",
                "--project-key",
                "demo",
                "--project-root",
                str(tmp_path),
                "--github-owner",
                "acme",
                "--github-repo",
                "demo",
                "--target-config-version",
                "4.0",
                "--dry-run",
            ]
        )

        assert exit_code == 0
        assert captured["mode"] is ExecutionMode.DRY_RUN

    def test_upgrade_project_reports_a_failed_checkpoint_as_non_zero(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A blocked checkpoint must reach the exit code, not just the engine.

        The engine already stops before further mutations — but reporting exit 0
        with "upgraded" would tell operators and automation that an upgrade
        happened which was in fact refused.
        """

        def fake_upgrade(project_root: Path, **kwargs: object) -> object:
            return SimpleNamespace(
                scenario=SimpleNamespace(scenario=SimpleNamespace(value="unchanged")),
                detail="Norm-violating skill pin(s): create-userstory-core@4.0.0 < 4.1.0.",
                failed=True,
                failed_checkpoints=("up_02_guard_binding",),
            )

        monkeypatch.setattr("agentkit.backend.installer.upgrade.entry.run_checkpoint_upgrade", fake_upgrade)

        exit_code = main(
            [
                "upgrade-project",
                "--project-key",
                "demo",
                "--project-root",
                str(tmp_path),
                "--github-owner",
                "acme",
                "--github-repo",
                "demo",
                "--target-config-version",
                "3.0",
            ]
        )

        assert exit_code == 1
        stderr = capsys.readouterr().err
        assert "up_02_guard_binding" in stderr
        assert "upgraded" not in stderr

    def test_upgrade_project_reports_preservation_block(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A F-51-023 preservation block surfaces as a non-zero exit (fail-closed)."""
        from agentkit.backend.installer.upgrade.footprint import (
            CustomizationPreservationError,
        )

        def fake_upgrade(project_root: Path, **kwargs: object) -> object:
            raise CustomizationPreservationError("blocked by F-51-023", detail={"invariant": "F-51-023"})

        monkeypatch.setattr("agentkit.backend.installer.upgrade.entry.run_checkpoint_upgrade", fake_upgrade)

        exit_code = main(
            [
                "upgrade-project",
                "--project-key",
                "demo",
                "--project-root",
                str(tmp_path),
                "--github-owner",
                "acme",
                "--github-repo",
                "demo",
                "--target-config-version",
                "3.0",
            ]
        )

        assert exit_code == 1
        assert "F-51-023" in capsys.readouterr().err
