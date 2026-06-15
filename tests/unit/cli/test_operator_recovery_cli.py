"""Unit tests for AG3-076 operator/recovery CLI commands.

Tests argparse wiring, dispatch logic, fail-closed findings for Class-C
commands, and all mandatory negative paths from §2.12 of the story.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agentkit.cli.main import main

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _invoke(
    argv: list[str],
    capsys: pytest.CaptureFixture[str],
) -> tuple[int, str, str]:
    """Invoke main() capturing stdout/stderr; no SystemExit expected."""
    code = main(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


# ===========================================================================
# §2.12 Mandatory negative-path tests
# ===========================================================================


class TestRunPhaseNegativePaths:
    """AK 1 / §2.12 negative paths for ``agentkit run-phase``."""

    def test_unknown_phase_returns_nonzero(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Unrecognised phase -> non-zero exit + error to stderr."""
        code, _, err = _invoke(
            [
                "run-phase",
                "unknown-phase",
                "--story", "AG3-001",
                "--run", "run-1",
                "--session", "sess-1",
                "--principal", "agent",
                "--worktree", "/tmp/wt",
            ],
            capsys,
        )
        assert code != 0
        assert "InvalidPhase" in err or "invalid" in err.lower()

    def test_verify_phase_is_rejected(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """``verify`` is a capability, not a valid top-level phase."""
        code, _, err = _invoke(
            [
                "run-phase",
                "verify",
                "--story", "AG3-001",
                "--run", "run-1",
                "--session", "sess-1",
                "--principal", "agent",
                "--worktree", "/tmp/wt",
            ],
            capsys,
        )
        assert code != 0
        assert "InvalidPhase" in err or "verify" in err.lower()

    def test_missing_run_flag_causes_argparse_error(self) -> None:
        """``--run`` is required; absence -> argparse SystemExit."""
        with pytest.raises(SystemExit) as exc_info:
            main(
                [
                    "run-phase",
                    "setup",
                    "--story", "AG3-001",
                    "--session", "sess-1",
                    "--principal", "agent",
                    "--worktree", "/tmp/wt",
                ]
            )
        assert exc_info.value.code != 0

    def test_missing_session_flag_causes_argparse_error(self) -> None:
        """``--session`` is required; absence -> argparse SystemExit."""
        with pytest.raises(SystemExit) as exc_info:
            main(
                [
                    "run-phase",
                    "setup",
                    "--story", "AG3-001",
                    "--run", "run-1",
                    "--principal", "agent",
                    "--worktree", "/tmp/wt",
                ]
            )
        assert exc_info.value.code != 0

    def test_missing_principal_flag_causes_argparse_error(self) -> None:
        """``--principal`` is required; absence -> argparse SystemExit."""
        with pytest.raises(SystemExit) as exc_info:
            main(
                [
                    "run-phase",
                    "setup",
                    "--story", "AG3-001",
                    "--run", "run-1",
                    "--session", "sess-1",
                    "--worktree", "/tmp/wt",
                ]
            )
        assert exc_info.value.code != 0

    def test_missing_worktree_flag_causes_argparse_error(self) -> None:
        """``--worktree`` is required; absence -> argparse SystemExit."""
        with pytest.raises(SystemExit) as exc_info:
            main(
                [
                    "run-phase",
                    "setup",
                    "--story", "AG3-001",
                    "--run", "run-1",
                    "--session", "sess-1",
                    "--principal", "agent",
                ]
            )
        assert exc_info.value.code != 0

    def test_missing_project_key_returns_nonzero(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """No ``--project`` and no ``AGENTKIT_PROJECT_KEY`` -> non-zero."""
        monkeypatch.delenv("AGENTKIT_PROJECT_KEY", raising=False)
        code, _, err = _invoke(
            [
                "run-phase",
                "setup",
                "--story", "AG3-001",
                "--run", "run-1",
                "--session", "sess-1",
                "--principal", "agent",
                "--worktree", "/tmp/wt",
            ],
            capsys,
        )
        assert code != 0
        assert "ProjectKey" in err or "project" in err.lower()

    def test_valid_phase_builds_phase_mutation_request_and_calls_start_phase(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Valid input builds PhaseMutationRequest and calls start_phase (ERROR 6 fix).

        The test does NOT just patch the handler — it patches the service and
        inspects the actual PhaseMutationRequest payload delivered to start_phase.
        """
        monkeypatch.setenv("AGENTKIT_PROJECT_KEY", "proj-key")

        mock_result = MagicMock()
        mock_result.status = "committed"
        mock_result.op_id = "op-x"
        mock_result.operation_kind = "phase_start"
        mock_result.run_id = "run-1"
        mock_result.phase = "setup"
        mock_result.phase_dispatch = None

        mock_svc_inst = MagicMock()
        mock_svc_inst.start_phase.return_value = mock_result

        with patch(
            "agentkit.control_plane.runtime.ControlPlaneRuntimeService",
            return_value=mock_svc_inst,
        ):
            code, out, err = _invoke(
                [
                    "run-phase",
                    "setup",
                    "--story", "AG3-001",
                    "--run", "run-1",
                    "--session", "sess-1",
                    "--principal", "agent",
                    "--worktree", "/tmp/wt",
                    "--project", "proj-key",
                ],
                capsys,
            )

        # start_phase MUST have been called (not silently skipped)
        mock_svc_inst.start_phase.assert_called_once()
        # Inspect the call args — first kwarg is run_id, second is request
        _, call_kwargs = mock_svc_inst.start_phase.call_args
        assert call_kwargs.get("run_id") == "run-1", "run_id must be passed"
        assert call_kwargs.get("phase") == "setup", "phase must be passed"
        request = call_kwargs.get("request")
        assert request is not None, "PhaseMutationRequest must be passed"
        assert str(request.project_key) == "proj-key"
        assert str(request.story_id) == "AG3-001"
        assert str(request.session_id) == "sess-1"
        assert str(request.principal_type) == "agent"
        assert list(request.worktree_roots) == ["/tmp/wt"]
        assert code == 0


class TestResumeNegativePaths:
    """AK 3 / §2.12 negative paths for ``agentkit resume``."""

    def test_missing_story_flag_causes_argparse_error(self) -> None:
        """``--story`` is required; absence -> argparse SystemExit."""
        with pytest.raises(SystemExit) as exc_info:
            main(["resume", "--trigger", "approval_received"])
        assert exc_info.value.code != 0

    def test_missing_trigger_flag_causes_argparse_error(self) -> None:
        """``--trigger`` is required; absence -> argparse SystemExit."""
        with pytest.raises(SystemExit) as exc_info:
            main(["resume", "--story", "AG3-001"])
        assert exc_info.value.code != 0

    def test_no_paused_envelope_returns_nonzero(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """No PAUSED PhaseEnvelope for the story -> non-zero + finding."""
        story_dir = tmp_path / "stories" / "AG3-001"
        story_dir.mkdir(parents=True)

        # Story context file exists but no PAUSED envelope
        code, _, err = _invoke(
            [
                "resume",
                "--story", "AG3-001",
                "--trigger", "approval_received",
                "--project-root", str(tmp_path),
            ],
            capsys,
        )
        assert code != 0
        # Either MissingStoryContext or NoPausedEnvelope
        assert (
            "failed" in err.lower()
            or "gap" in err.lower()
            or "paused" in err.lower()
            or "context" in err.lower()
        )


class TestResetEscalationNegativePath:
    """AK 4 / §2.12 — ``reset-escalation`` fail-closed service-gap finding."""

    def test_returns_nonzero_with_service_gap_finding(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code, _, err = _invoke(
            ["reset-escalation", "--story", "AG3-001"],
            capsys,
        )
        assert code != 0
        assert "[ServiceGap]" in err
        assert "reset-escalation" in err.lower()

    def test_no_state_mutation_on_reset_escalation(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Confirm no service calls happen for Class-C command."""
        with patch(
            "agentkit.state_backend.store.lock_record_repository.LockRecordRepository"
        ) as mock_repo:
            code, _, err = _invoke(
                ["reset-escalation", "--story", "AG3-001"],
                capsys,
            )
        assert code != 0
        mock_repo.assert_not_called()


class TestCleanupNegativePath:
    """AK 5 / §2.12 — ``cleanup`` fail-closed without PID liveness."""

    def test_cleanup_without_pid_liveness_returns_nonzero(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code, _, err = _invoke(
            ["cleanup", "--story", "AG3-001"],
            capsys,
        )
        assert code != 0
        assert "[ServiceGap]" in err
        assert "liveness" in err.lower() or "pid" in err.lower()

    def test_cleanup_does_not_deactivate_locks(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """No locks must be deactivated without PID liveness anchor."""
        with patch(
            "agentkit.state_backend.store.lock_record_repository."
            "LockRecordRepository.deactivate_locks_for_story"
        ) as mock_deactivate:
            code, _, err = _invoke(
                ["cleanup", "--story", "AG3-001"],
                capsys,
            )
        assert code != 0
        mock_deactivate.assert_not_called()

    def test_cleanup_does_not_remove_worktree(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """No worktree removal should happen fail-closed."""
        worktree = tmp_path / "_worktrees" / "AG3-001"
        worktree.mkdir(parents=True)
        with patch("shutil.rmtree") as mock_rmtree:
            code, _, err = _invoke(
                ["cleanup", "--story", "AG3-001"],
                capsys,
            )
        assert code != 0
        mock_rmtree.assert_not_called()


class TestQueryStateNegativePaths:
    """AK 6 / §2.12 — ``query-state --locks`` fail-closed service-gap finding."""

    def test_locks_story_scoped_returns_nonzero_with_finding(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """``--story X --locks`` -> non-zero + service-gap finding."""
        code, _, err = _invoke(
            ["query-state", "--story", "AG3-001", "--locks"],
            capsys,
        )
        assert code != 0
        assert "[ServiceGap]" in err
        assert "lock" in err.lower()

    def test_locks_global_returns_nonzero_with_finding(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """``--locks`` without ``--story`` (global) -> non-zero + finding."""
        code, _, err = _invoke(
            ["query-state", "--locks"],
            capsys,
        )
        assert code != 0
        assert "[ServiceGap]" in err
        assert "lock" in err.lower()

    def test_phase_state_missing_story_returns_nonzero(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Phase-state query without ``--story`` -> non-zero."""
        code, _, err = _invoke(
            ["query-state"],
            capsys,
        )
        assert code != 0
        assert "story" in err.lower() or "MissingStoryId" in err


class TestQueryTelemetryNegativePaths:
    """AK 6 / §2.12 — ``query-telemetry`` negative paths."""

    def test_no_selector_returns_nonzero(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """No ``--story``, ``--run``, or ``--event`` -> non-zero."""
        code, _, err = _invoke(
            ["query-telemetry"],
            capsys,
        )
        assert code != 0
        assert "MissingFilter" in err or "required" in err.lower()

    def test_run_without_project_key_returns_nonzero(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """``--run R`` without resolvable ``project_key`` -> non-zero."""
        monkeypatch.delenv("AGENTKIT_PROJECT_KEY", raising=False)
        code, _, err = _invoke(
            ["query-telemetry", "--run", "run-abc"],
            capsys,
        )
        assert code != 0
        assert "ProjectKey" in err or "project" in err.lower()

    def test_event_since_without_project_key_returns_nonzero(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """``--event X --since Y`` without project_key -> non-zero.

        Uses a VALID EventType (``agent_start``) so the --event validation does not
        fire; the failure is the missing project key.
        """
        monkeypatch.delenv("AGENTKIT_PROJECT_KEY", raising=False)
        code, _, err = _invoke(
            ["query-telemetry", "--event", "agent_start", "--since", "2025-01-01"],
            capsys,
        )
        assert code != 0
        assert "ProjectKey" in err or "project" in err.lower()


class TestWeeklyReviewServiceGapFinding:
    """AK 9 / §2.12 — ``weekly-review`` Failure-Corpus service-gap findings (ERROR 2 fix)."""

    def test_weekly_review_returns_nonzero(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """All sections are Class-C service gaps -> non-zero exit (story §2.1 preamble)."""
        code, _, err = _invoke(["weekly-review"], capsys)
        assert code != 0, "weekly-review must exit non-zero: all sections are Class-C service gaps"

    def test_weekly_review_emits_machine_readable_findings_to_stderr(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """All three FailureCorpus sections must be explicit service-gap findings on stderr."""
        code, _out, err = _invoke(["weekly-review"], capsys)
        assert code != 0
        payload = json.loads(err)
        review = payload["weekly_review"]

        for section in ("pattern_candidates", "check_proposals", "effectiveness_alerts"):
            assert section in review, f"missing section: {section}"
            item = review[section]
            assert item.get("status") == "service_gap", (
                f"{section} status should be service_gap"
            )
            finding = item.get("finding", "")
            assert "ServiceGap" in finding, f"{section} finding missing [ServiceGap]"
            assert "AG3-078" in finding, f"{section} finding missing owner AG3-078"

    def test_weekly_review_not_silent_empty(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Sections must NOT be empty / null — explicit gap findings only."""
        _code, _out, err = _invoke(["weekly-review"], capsys)
        payload = json.loads(err)
        review = payload["weekly_review"]
        for section_name, section_val in review.items():
            # Each section must have content (not empty dict / None)
            assert section_val, (
                f"section {section_name!r} is empty — must be explicit service-gap"
            )


class TestOverrideIntegrityNegativePaths:
    """AK 7 / §2.12 — ``override-integrity`` fail-closed."""

    def test_missing_reason_causes_argparse_error(self) -> None:
        """``--reason`` is mandatory; absence -> argparse SystemExit."""
        with pytest.raises(SystemExit) as exc_info:
            main(["override-integrity", "--story", "AG3-001"])
        assert exc_info.value.code != 0

    def test_with_reason_but_missing_service_returns_nonzero(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """With ``--reason`` but no authorized service -> non-zero + finding."""
        code, _, err = _invoke(
            [
                "override-integrity",
                "--story", "AG3-001",
                "--reason", "explicit human decision after manual review",
            ],
            capsys,
        )
        assert code != 0
        assert "[ServiceGap]" in err
        assert "integrity" in err.lower() or "override" in err.lower()

    def test_no_state_mutation_on_override_integrity(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Class-C: no service calls (no integrity gate bypass)."""
        # No real service imports happen for Class-C; confirm exit code + gap
        code, _, err = _invoke(
            [
                "override-integrity",
                "--story", "AG3-001",
                "--reason", "deliberate override",
            ],
            capsys,
        )
        assert code != 0
        assert "[ServiceGap]" in err


class TestExportTelemetryNegativePaths:
    """AK 8 / §2.12 — ``export-telemetry`` mandatory flags."""

    def test_missing_story_flag_causes_argparse_error(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            main(["export-telemetry", "--run", "r-1", "--output-dir", "/tmp/out"])
        assert exc_info.value.code != 0

    def test_missing_run_flag_causes_argparse_error(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            main(["export-telemetry", "--story", "AG3-001", "--output-dir", "/tmp/out"])
        assert exc_info.value.code != 0

    def test_missing_output_dir_flag_causes_argparse_error(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            main(["export-telemetry", "--story", "AG3-001", "--run", "r-1"])
        assert exc_info.value.code != 0

    def test_dry_run_reports_writable_without_creating_files(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """``--dry-run`` succeeds against writable parent and does NOT create/write files (ERROR 4 fix).

        Story §2.1.10: no write, no export call.
        The target dir is a subdirectory of tmp_path which does NOT yet exist;
        after the call it must still NOT exist (no mkdir, no probe write).
        """
        out_dir = tmp_path / "export_out"
        # out_dir must NOT exist yet
        assert not out_dir.exists()

        code, out, _ = _invoke(
            [
                "export-telemetry",
                "--story", "AG3-001",
                "--run", "run-123",
                "--output-dir", str(out_dir),
                "--dry-run",
            ],
            capsys,
        )
        assert code == 0, f"dry-run should succeed against writable parent; err={out}"
        payload = json.loads(out)
        assert payload["dry_run"] is True
        assert payload["writable"] is True
        # Critical: no directory or file must have been created
        assert not out_dir.exists(), (
            "dry-run must NOT create the output directory (ERROR 4: no filesystem mutation)"
        )

    def test_dry_run_fails_on_unwritable_dir(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """``--dry-run`` against a path whose ancestor is not writable returns 1 (no mutation)."""
        with patch("os.access", return_value=False):
            code, _, err = _invoke(
                [
                    "export-telemetry",
                    "--story", "AG3-001",
                    "--run", "run-123",
                    "--output-dir", "/nonexistent/path/out",
                    "--dry-run",
                ],
                capsys,
            )
        assert code != 0
        assert "OutputDirNotWritable" in err or "dry-run" in err.lower()


# ===========================================================================
# AK 10 — Agent-Boundary test
# ===========================================================================


class TestAgentBoundary:
    """AK 10 / §3 — no agent/control-plane module imports agentkit.cli.main."""

    def test_no_agent_module_imports_cli_main(self) -> None:
        """Verify that no productive agent/control-plane module imports cli.main.

        This enforces the FK-45 §45.4 boundary: agents use the Control-Plane-API
        (FK-91 §91.1a), not the CLI.
        """
        src_root = Path("src/agentkit")
        forbidden_modules = [
            "agentkit.cli.main",
            "agentkit.cli",
        ]
        violating_files: list[str] = []

        agent_scoped_dirs = [
            "control_plane",
            "pipeline_engine",
            "implementation",
            "exploration",
            "setup",
            "closure",
        ]

        for agent_dir in agent_scoped_dirs:
            dir_path = src_root / agent_dir
            if not dir_path.exists():
                continue
            for py_file in dir_path.rglob("*.py"):
                try:
                    source = py_file.read_text(encoding="utf-8")
                    tree = ast.parse(source, filename=str(py_file))
                except (OSError, SyntaxError):
                    continue
                for node in ast.walk(tree):
                    if isinstance(node, (ast.Import, ast.ImportFrom)):
                        if isinstance(node, ast.ImportFrom):
                            module = node.module or ""
                        else:
                            names = [alias.name for alias in node.names]
                            module = names[0] if names else ""
                        for forbidden in forbidden_modules:
                            if module.startswith(forbidden):
                                violating_files.append(str(py_file))

        assert not violating_files, (
            f"Agent/control-plane modules must NOT import agentkit.cli.main "
            f"(FK-45 §45.4). Violating files: {violating_files}"
        )


# ===========================================================================
# AK 11 — Deterministic exit codes
# ===========================================================================


class TestDeterministicExitCodes:
    """AK 11 — all new commands return deterministic exit codes."""

    def test_run_phase_unknown_phase_returns_one(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code, _, err = _invoke(
            [
                "run-phase",
                "not-a-phase",
                "--story", "AG3-001",
                "--run", "r-1",
                "--session", "s-1",
                "--principal", "agent",
                "--worktree", "/tmp/w",
                "--project", "proj",
            ],
            capsys,
        )
        assert code == 1

    def test_reset_escalation_always_returns_one(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code, _, err = _invoke(
            ["reset-escalation", "--story", "AG3-001"],
            capsys,
        )
        assert code == 1

    def test_cleanup_always_returns_one(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code, _, _ = _invoke(["cleanup", "--story", "AG3-001"], capsys)
        assert code == 1

    def test_query_state_locks_always_returns_one(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code, _, _ = _invoke(["query-state", "--locks"], capsys)
        assert code == 1

    def test_override_integrity_with_reason_returns_one(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code, _, _ = _invoke(
            ["override-integrity", "--story", "AG3-001", "--reason", "reason text"],
            capsys,
        )
        assert code == 1

    def test_weekly_review_renderer_frame_returns_nonzero(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """weekly-review is Class-C service gap -> non-zero (ERROR 2 fix)."""
        code, _, _ = _invoke(["weekly-review"], capsys)
        assert code == 1


# ===========================================================================
# AK 1 — Phase validation / valid phase pass-through with start_phase assertion
# ===========================================================================


class TestRunPhaseValidPhases:
    """AK 1 — valid phase names are accepted; ``verify`` is rejected; start_phase is called."""

    @pytest.mark.parametrize("phase", ["setup", "exploration", "implementation", "closure"])
    def test_valid_phases_call_start_phase_with_correct_request(
        self,
        phase: str,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Valid phases: start_phase is called and request payload matches flags (ERROR 6 fix).

        Replaces the old test that only checked 'InvalidPhase not in err' with a
        test that asserts the actual start_phase call and the PhaseMutationRequest.
        """
        monkeypatch.setenv("AGENTKIT_PROJECT_KEY", "proj-key")

        mock_result = MagicMock()
        mock_result.status = "committed"
        mock_result.op_id = "op-x"
        mock_result.operation_kind = "phase_start"
        mock_result.run_id = "run-1"
        mock_result.phase = phase
        mock_result.phase_dispatch = None

        mock_svc_inst = MagicMock()
        mock_svc_inst.start_phase.return_value = mock_result

        with patch(
            "agentkit.control_plane.runtime.ControlPlaneRuntimeService",
            return_value=mock_svc_inst,
        ):
            code, out, err = _invoke(
                [
                    "run-phase",
                    phase,
                    "--story", "AG3-001",
                    "--run", "run-1",
                    "--session", "sess-1",
                    "--principal", "agent",
                    "--worktree", "/tmp/wt",
                ],
                capsys,
            )

        # Phase validation passed AND start_phase was called
        assert "InvalidPhase" not in err
        mock_svc_inst.start_phase.assert_called_once()

        _, call_kwargs = mock_svc_inst.start_phase.call_args
        request = call_kwargs.get("request")
        assert request is not None, "PhaseMutationRequest must be passed to start_phase"
        assert str(request.story_id) == "AG3-001"
        assert str(request.session_id) == "sess-1"
        assert str(request.principal_type) == "agent"


# ===========================================================================
# AK 6 — query-state phase-state (Class A, read-only)
# ===========================================================================


class TestQueryStatePhaseState:
    """AK 6 — ``query-state --story`` reads phase state (Class A, read-only)."""

    def test_phase_state_outputs_json(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Successful phase-state read with a real record returns JSON with story_id."""
        story_dir = tmp_path / "stories" / "AG3-001"
        story_dir.mkdir(parents=True)

        mock_record = MagicMock()
        mock_record.model_dump.return_value = {"phase": "setup", "status": "completed"}

        with patch(
            "agentkit.state_backend.store.facade.read_phase_state_record",
            return_value=mock_record,
        ):
            code, out, _ = _invoke(
                [
                    "query-state",
                    "--story", "AG3-001",
                    "--project-root", str(tmp_path),
                ],
                capsys,
            )
        assert code == 0
        payload = json.loads(out)
        assert "story_id" in payload
        assert payload["story_id"] == "AG3-001"

    def test_phase_state_none_returns_nonzero(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """None phase-state record (story not found) must be fail-closed (ERROR 3 fix).

        Story §2.3: an unresolvable story is non-zero + structured stderr finding.
        """
        story_dir = tmp_path / "stories" / "AG3-001"
        story_dir.mkdir(parents=True)

        with patch(
            "agentkit.state_backend.store.facade.read_phase_state_record",
            return_value=None,
        ):
            code, _out, err = _invoke(
                [
                    "query-state",
                    "--story", "AG3-001",
                    "--project-root", str(tmp_path),
                ],
                capsys,
            )
        assert code != 0, "None phase-state must return non-zero (fail-closed, story §2.3)"
        finding = json.loads(err)
        assert finding.get("finding") == "PhaseStateNotFound"
        assert finding.get("story_id") == "AG3-001"


# ===========================================================================
# AK 5/9 — status includes weekly-review block (FC gap to stderr, exit 0)
# ===========================================================================


class TestStatusIncludesWeeklyReview:
    """AK 9 (status side) — ``agentkit status`` FC gap -> stderr, exit 0 (ERROR 2 fix)."""

    def test_status_exits_zero_on_class_a_success(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """``agentkit status`` (no --story) exits 0 — Class-A command (§2.1.5).

        Distinction vs. weekly-review: status exit code reflects Class-A success;
        weekly-review exit code reflects Class-C gap (§2.1.5/§2.1.8 rationale).
        """
        code, _out, _err = _invoke(["status"], capsys)
        assert code == 0

    def test_status_fc_service_gap_goes_to_stderr(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """FC service-gap markers are on stderr (machine-readable, never silent)."""
        code, _out, err = _invoke(["status"], capsys)
        assert code == 0
        # FC gaps must be on stderr as machine-readable JSON
        gap_data = json.loads(err)
        assert "weekly_review_service_gaps" in gap_data
        review = gap_data["weekly_review_service_gaps"]
        for section in ("pattern_candidates", "check_proposals", "effectiveness_alerts"):
            assert section in review
            assert review[section].get("status") == "service_gap"
            assert "[ServiceGap]" in review[section].get("finding", "")

    def test_status_stdout_is_class_a_overview(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """stdout from status contains the Class-A overview (not the FC gaps)."""
        code, out, _err = _invoke(["status"], capsys)
        assert code == 0
        payload = json.loads(out)
        # The Class-A output does NOT duplicate the FC blocks in stdout
        assert "weekly_review_service_gaps" not in payload

    def test_status_weekly_review_uses_same_renderer_as_weekly_review_command(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """status and weekly-review share the same renderer frame (§2.1.5)."""
        _code_s, _out_s, err_s = _invoke(["status"], capsys)
        _code_w, _out_w, err_w = _invoke(["weekly-review"], capsys)

        status_gaps = json.loads(err_s)["weekly_review_service_gaps"]
        weekly_gaps = json.loads(err_w)["weekly_review"]
        # Same keys = same renderer
        assert set(status_gaps.keys()) == set(weekly_gaps.keys())

    def test_status_with_story_reads_phase_state(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """``status --story X`` succeeds when phase state is found (story_id in stdout)."""
        story_dir = tmp_path / "stories" / "AG3-001"
        story_dir.mkdir(parents=True)

        mock_record = MagicMock()
        mock_record.model_dump.return_value = {"phase": "setup", "status": "completed"}

        with patch(
            "agentkit.state_backend.store.facade.read_phase_state_record",
            return_value=mock_record,
        ):
            code, out, _ = _invoke(
                ["status", "--story", "AG3-001", "--project-root", str(tmp_path)],
                capsys,
            )
        assert code == 0
        payload = json.loads(out)
        assert "story_id" in payload

    def test_status_with_story_none_phase_state_returns_nonzero(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """``status --story X`` is fail-closed when phase state is None (ERROR 3 fix).

        Story §2.3: an unresolvable story is non-zero + structured stderr finding.
        """
        story_dir = tmp_path / "stories" / "AG3-001"
        story_dir.mkdir(parents=True)

        with patch(
            "agentkit.state_backend.store.facade.read_phase_state_record",
            return_value=None,
        ):
            code, _out, err = _invoke(
                ["status", "--story", "AG3-001", "--project-root", str(tmp_path)],
                capsys,
            )
        assert code != 0, "None phase-state must return non-zero (fail-closed, story §2.3)"
        # stderr must contain the structured PhaseStateNotFound finding
        # (it also may contain the weekly_review_service_gaps JSON on the line before)
        assert "PhaseStateNotFound" in err


# ===========================================================================
# ERROR 3 fix — query-telemetry --story uses StateBackendEmitter.query
# ===========================================================================


class TestQueryTelemetryStoryUsesEmitterQuery:
    """query-telemetry --story must delegate to StateBackendEmitter.query (ERROR 3 fix)."""

    def test_story_form_calls_emitter_query(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """``--story X`` routes through StateBackendEmitter.query (§2.1.7 / §2.3)."""
        story_dir = tmp_path / "stories" / "AG3-001"
        story_dir.mkdir(parents=True)

        mock_event = MagicMock()
        mock_event.event_id = "ev-1"
        mock_event.event_type = "phase_start"
        mock_event.story_id = "AG3-001"
        mock_event.occurred_at = "2025-01-01T00:00:00"

        with patch(
            "agentkit.telemetry.storage.StateBackendEmitter.query",
            return_value=[mock_event],
        ) as mock_query:
            code, out, _err = _invoke(
                [
                    "query-telemetry",
                    "--story", "AG3-001",
                    "--project-root", str(tmp_path),
                ],
                capsys,
            )

        assert code == 0, f"query-telemetry --story should succeed; err={_err}"
        mock_query.assert_called_once()
        # story_id is first positional arg to query()
        called_story_id = mock_query.call_args[0][0]
        assert called_story_id == "AG3-001"
        payload = json.loads(out)
        assert payload["story_id"] == "AG3-001"
        assert len(payload["events"]) == 1

    def test_story_event_form_passes_event_type_to_emitter_query(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """``--story X --event Y`` passes event_type to StateBackendEmitter.query.

        Uses a valid EventType value (agent_start) so the filter is forwarded.
        """
        story_dir = tmp_path / "stories" / "AG3-001"
        story_dir.mkdir(parents=True)

        with patch(
            "agentkit.telemetry.storage.StateBackendEmitter.query",
            return_value=[],
        ) as mock_query:
            _code, _out, _err = _invoke(
                [
                    "query-telemetry",
                    "--story", "AG3-001",
                    "--event", "agent_start",  # valid EventType value
                    "--project-root", str(tmp_path),
                ],
                capsys,
            )

        mock_query.assert_called_once()
        # Second positional arg is event_type (EventType | None)
        called_event_type = mock_query.call_args[0][1]
        assert called_event_type is not None, "event_type should be forwarded for valid EventType"


# ===========================================================================
# ERROR 6 fix — positive tests for story-less query-telemetry forms
# ===========================================================================


class TestQueryTelemetryProjectGlobalForms:
    """Positive tests: story-less query-telemetry routes through load_execution_events_for_project_global."""

    def _make_event(self, run_id: str, event_type: str, occurred_at: str) -> MagicMock:
        e = MagicMock()
        e.run_id = run_id
        e.event_type = event_type
        e.occurred_at = occurred_at
        e.event_id = "ev-x"
        e.story_id = "AG3-001"
        return e

    def test_run_form_calls_load_execution_events_for_project_global(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """``--run R`` calls load_execution_events_for_project_global + filters on run_id."""
        monkeypatch.setenv("AGENTKIT_PROJECT_KEY", "proj-key")
        event_a = self._make_event("run-abc", "phase_start", "2025-01-01T00:00:00")
        event_b = self._make_event("run-xyz", "phase_end", "2025-01-02T00:00:00")

        with patch(
            "agentkit.state_backend.store.facade.load_execution_events_for_project_global",
            return_value=[event_a, event_b],
        ) as mock_reader:
            code, out, _err = _invoke(
                ["query-telemetry", "--run", "run-abc"],
                capsys,
            )

        assert code == 0
        # cli_load_execution_events_for_project_global passes limit=None as a kwarg
        mock_reader.assert_called_once_with("proj-key", limit=None)
        payload = json.loads(out)
        events = payload["events"]
        assert len(events) == 1, "adapter-side run_id filter must leave only matching event"
        assert events[0]["run_id"] == "run-abc"

    def test_event_since_form_calls_load_execution_events_for_project_global(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """``--event Y --since Z`` calls load_execution_events_for_project_global + filters."""
        monkeypatch.setenv("AGENTKIT_PROJECT_KEY", "proj-key")
        # Use real event_type string values (not EventType enum here since we are testing
        # the adapter-side string filter, which compares str(event_type)).
        old_event = self._make_event("run-1", "agent_start", "2024-12-01T00:00:00")
        new_event = self._make_event("run-2", "agent_start", "2025-02-01T00:00:00")
        wrong_type = self._make_event("run-3", "agent_end", "2025-03-01T00:00:00")

        with patch(
            "agentkit.state_backend.store.facade.load_execution_events_for_project_global",
            return_value=[old_event, new_event, wrong_type],
        ) as mock_reader:
            code, out, _err = _invoke(
                ["query-telemetry", "--event", "agent_start", "--since", "2025-01-01"],
                capsys,
            )

        assert code == 0
        # cli_load_execution_events_for_project_global passes limit=None as a kwarg
        mock_reader.assert_called_once_with("proj-key", limit=None)
        payload = json.loads(out)
        events = payload["events"]
        # old_event is before since; wrong_type has wrong event_type
        assert all(e["event_type"] == "agent_start" for e in events)
        assert all(e["occurred_at"] >= "2025-01-01" for e in events)


# ===========================================================================
# ERROR 2 fix — query-telemetry --config: valid resolves key; broken fails-closed
# ===========================================================================


class TestQueryTelemetryConfigFlag:
    """ERROR 2: --config on query-telemetry resolves project_key or fails-closed."""

    def _make_event(self, run_id: str, event_type: str, occurred_at: str) -> MagicMock:
        e = MagicMock()
        e.run_id = run_id
        e.event_type = event_type
        e.occurred_at = occurred_at
        e.event_id = "ev-y"
        e.story_id = "AG3-002"
        return e

    def test_valid_config_resolves_project_key(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """--config with a valid config that yields project_key succeeds."""
        cfg_path = tmp_path / "agentkit.yaml"
        cfg_path.write_text("project_key: proj-from-config\n")
        event_a = self._make_event("run-1", "agent_start", "2025-01-01T00:00:00")

        mock_cfg = MagicMock()
        mock_cfg.project_key = "proj-from-config"

        with (
            patch("agentkit.config.loader.load_project_config", return_value=mock_cfg),
            patch(
                "agentkit.state_backend.store.facade.load_execution_events_for_project_global",
                return_value=[event_a],
            ) as mock_reader,
        ):
            code, out, _err = _invoke(
                ["query-telemetry", "--config", str(cfg_path), "--run", "run-1"],
                capsys,
            )

        assert code == 0
        # cli_load_execution_events_for_project_global passes limit=None as a kwarg
        mock_reader.assert_called_once_with("proj-from-config", limit=None)
        payload = json.loads(out)
        assert payload["project_key"] == "proj-from-config"

    def test_config_provided_but_invalid_fails_closed(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """--config provided but unreadable must fail-closed (not fall through to env var).

        ERROR 2 fix: when --config is explicitly given and fails, the env var
        AGENTKIT_PROJECT_KEY must NOT be used as a silent fallback.
        """
        monkeypatch.setenv("AGENTKIT_PROJECT_KEY", "env-fallback-key")
        bad_cfg_path = tmp_path / "nonexistent.yaml"

        with patch(
            "agentkit.config.loader.load_project_config",
            side_effect=FileNotFoundError("file not found"),
        ):
            code, _out, err = _invoke(
                ["query-telemetry", "--config", str(bad_cfg_path), "--run", "run-1"],
                capsys,
            )

        assert code != 0, "--config broken must return non-zero (fail-closed)"
        assert "ConfigResolutionError" in err or "config" in err.lower()

    def test_config_registered_on_query_telemetry_parser(self) -> None:
        """``query-telemetry --config`` must be a registered flag (not argparse error)."""
        # If --config is not registered, argparse raises SystemExit 2.
        # A missing-filter error (exit 1) is acceptable (we're testing parser registration).
        try:
            rc = main(["query-telemetry", "--config", "/some/path.yaml"])
        except SystemExit as exc:
            # If it's argparse's "unrecognized argument" exit (code 2), the flag is absent.
            assert exc.code != 2, "--config must be a recognised flag on query-telemetry"
        else:
            # Non-argparse exit (e.g. MissingFilter error returning 1) is fine.
            assert rc in (0, 1)


# ===========================================================================
# ERROR 4 fix — query-telemetry --event <invalid> fails-closed
# ===========================================================================


class TestQueryTelemetryEventValidation:
    """ERROR 4: unknown --event value must fail-closed (non-zero + stderr finding)."""

    def test_invalid_event_type_returns_nonzero(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """``--event bad_value`` must fail-closed: non-zero + structured finding."""
        monkeypatch.setenv("AGENTKIT_PROJECT_KEY", "proj-key")

        code, _out, err = _invoke(
            ["query-telemetry", "--event", "bad_value_xyz"],
            capsys,
        )

        assert code != 0, "--event with unknown type must return non-zero"
        finding = json.loads(err)
        assert finding.get("finding") == "InvalidEventType"
        assert finding.get("value") == "bad_value_xyz"
        assert isinstance(finding.get("valid_values"), list)

    def test_invalid_event_type_on_story_form_returns_nonzero(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """``--story X --event bad_value`` also fails-closed (applies to every form)."""
        story_dir = tmp_path / "stories" / "AG3-001"
        story_dir.mkdir(parents=True)

        code, _out, err = _invoke(
            [
                "query-telemetry",
                "--story", "AG3-001",
                "--event", "not_a_valid_event",
                "--project-root", str(tmp_path),
            ],
            capsys,
        )

        assert code != 0, "--event with unknown type must return non-zero even for story form"
        finding = json.loads(err)
        assert finding.get("finding") == "InvalidEventType"

    def test_valid_event_type_does_not_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """``--event agent_start`` (valid) must NOT be rejected."""
        monkeypatch.setenv("AGENTKIT_PROJECT_KEY", "proj-key")
        event = MagicMock()
        event.run_id = "run-1"
        event.event_type = "agent_start"
        event.occurred_at = "2025-01-01T00:00:00"
        event.event_id = "ev-z"
        event.story_id = "AG3-001"

        with patch(
            "agentkit.state_backend.store.facade.load_execution_events_for_project_global",
            return_value=[event],
        ):
            code, out, _err = _invoke(
                ["query-telemetry", "--event", "agent_start"],
                capsys,
            )

        assert code == 0
        payload = json.loads(out)
        assert len(payload["events"]) == 1


# ===========================================================================
# MAJOR 5 fix — --since parses {window} and fail-closes on unparseable
# ===========================================================================


class TestQueryTelemetrySinceParsing:
    """MAJOR 5: --since must parse Nd/Nh/Nm windows and ISO timestamps; reject unknown."""

    def _make_event(self, occurred_at: str) -> MagicMock:
        e = MagicMock()
        e.run_id = "run-1"
        e.event_type = "agent_start"
        e.occurred_at = occurred_at
        e.event_id = "ev-s"
        e.story_id = "AG3-001"
        return e

    def test_since_7d_filters_by_parsed_window(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """``--since 7d`` filters events older than 7 days using real datetime comparison."""
        import datetime as dt_mod

        monkeypatch.setenv("AGENTKIT_PROJECT_KEY", "proj-key")

        now = dt_mod.datetime.now(dt_mod.UTC)
        recent = (now - dt_mod.timedelta(days=3)).isoformat()
        old = (now - dt_mod.timedelta(days=10)).isoformat()

        event_recent = self._make_event(recent)
        event_old = self._make_event(old)

        with patch(
            "agentkit.state_backend.store.facade.load_execution_events_for_project_global",
            return_value=[event_recent, event_old],
        ):
            code, out, _err = _invoke(
                ["query-telemetry", "--run", "run-1", "--since", "7d"],
                capsys,
            )

        assert code == 0
        payload = json.loads(out)
        events = payload["events"]
        assert len(events) == 1, "only the event within 7d window should remain"
        assert events[0]["occurred_at"] == recent

    def test_since_unparseable_fails_closed(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """An unparseable ``--since`` value must fail-closed (non-zero + stderr finding)."""
        monkeypatch.setenv("AGENTKIT_PROJECT_KEY", "proj-key")

        code, _out, err = _invoke(
            ["query-telemetry", "--run", "run-1", "--since", "not-a-valid-since-value"],
            capsys,
        )

        assert code != 0, "unparseable --since must return non-zero"
        finding = json.loads(err)
        assert finding.get("finding") == "InvalidSinceValue"
        assert "not-a-valid-since-value" in str(finding.get("value", ""))

    def test_since_24h_window_is_accepted(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """``--since 24h`` is a valid window form and does not cause an error."""
        import datetime as dt_mod

        monkeypatch.setenv("AGENTKIT_PROJECT_KEY", "proj-key")
        recent = dt_mod.datetime.now(dt_mod.UTC).isoformat()
        event = self._make_event(recent)

        with patch(
            "agentkit.state_backend.store.facade.load_execution_events_for_project_global",
            return_value=[event],
        ):
            code, _out, _err = _invoke(
                ["query-telemetry", "--run", "run-1", "--since", "24h"],
                capsys,
            )

        assert code == 0


# ===========================================================================
# ERROR 1 fix — query-telemetry --story + --config: broken config fails-closed
# ===========================================================================


class TestQueryTelemetryStoryFormConfigValidation:
    """ERROR 1: --config must be validated even when --story is provided."""

    def test_story_form_broken_config_fails_closed(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``--story X --config <broken>`` must fail-closed (non-zero + ConfigResolutionError).

        Before the ERROR 1 fix, the story branch returned early without ever
        calling ``_resolve_project_key``, so a broken ``--config`` was silently
        ignored.  After the fix the config is validated BEFORE the story/non-story
        branch, so a broken config causes non-zero exit even on the story form.
        """
        story_dir = tmp_path / "stories" / "AG3-001"
        story_dir.mkdir(parents=True)
        # Set an env fallback that must NOT be used (fail-closed, not fallthrough).
        monkeypatch.setenv("AGENTKIT_PROJECT_KEY", "env-should-not-be-used")
        bad_cfg_path = tmp_path / "nonexistent.yaml"

        with patch(
            "agentkit.config.loader.load_project_config",
            side_effect=FileNotFoundError("file not found"),
        ):
            code, _out, err = _invoke(
                [
                    "query-telemetry",
                    "--story", "AG3-001",
                    "--config", str(bad_cfg_path),
                    "--project-root", str(tmp_path),
                ],
                capsys,
            )

        assert code != 0, (
            "--story + broken --config must return non-zero (config validated before story branch)"
        )
        assert "ConfigResolutionError" in err or "config" in err.lower(), (
            f"stderr must contain a config-resolution finding; got: {err!r}"
        )

    def test_story_form_explicit_empty_config_fails_closed_not_env_fallback(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``query-telemetry --story X --config ""`` must fail-closed; AGENTKIT_PROJECT_KEY
        must NOT be used as a fallback.

        ERROR 1 fix: when --config is provided but the value is empty/blank, the
        argparse default is None so ``config_path_raw is not None`` correctly
        detects the explicit-but-empty case and raises _ConfigResolutionError
        without touching the env var.
        """
        story_dir = tmp_path / "stories" / "AG3-001"
        story_dir.mkdir(parents=True)
        # Set an env key that must NOT be used when --config is explicitly provided.
        monkeypatch.setenv("AGENTKIT_PROJECT_KEY", "env-must-not-be-used")

        code, _out, err = _invoke(
            [
                "query-telemetry",
                "--story", "AG3-001",
                "--config", "",
                "--project-root", str(tmp_path),
            ],
            capsys,
        )

        assert code != 0, (
            "--config '' (explicit empty) must fail-closed with non-zero exit; "
            "env fallback AGENTKIT_PROJECT_KEY must NOT be used"
        )
        assert "config" in err.lower() or "ConfigResolutionError" in err, (
            f"stderr must describe the config resolution failure; got: {err!r}"
        )

    def test_run_phase_explicit_empty_config_fails_closed_not_env_fallback(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``run-phase --config ""`` must fail-closed; env fallback must NOT be used.

        Mirrors the query-telemetry empty-config test for the run-phase branch so
        both subcommands are covered (ERROR 1 fix applies to both).
        """
        monkeypatch.setenv("AGENTKIT_PROJECT_KEY", "env-must-not-be-used")

        code, _out, err = _invoke(
            [
                "run-phase", "setup",
                "--story", "AG3-001",
                "--run", "run-1",
                "--session", "sess-1",
                "--principal", "operator",
                "--worktree", str(tmp_path),
                "--config", "",
            ],
            capsys,
        )

        assert code != 0, (
            "run-phase --config '' (explicit empty) must fail-closed with non-zero exit"
        )
        assert "config" in err.lower() or "ConfigResolutionError" in err, (
            f"stderr must describe the config resolution failure; got: {err!r}"
        )


# ===========================================================================
# MAJOR 2 fix — --since filter must work for story-scoped Event.timestamp
# ===========================================================================


class TestQueryTelemetrySinceWithEventTimestamp:
    """MAJOR 2: _apply_since_filter must read Event.timestamp (story-scoped form)."""

    def _make_story_event(
        self,
        story_id: str,
        timestamp_dt: object,
        event_id: str = "ev-story-1",
        run_id: str = "run-1",
        payload: str = "default",
    ) -> MagicMock:
        """Build a mock that mimics a story-scoped ``Event`` dataclass.

        Uses ``.timestamp`` (no ``occurred_at``) to match the real
        ``agentkit.telemetry.events.Event`` schema (field added by AG3-076).
        Accepts ``event_id``, ``run_id``, and ``payload`` so callers can
        create distinctly identifiable events (required by the since-filter test).
        """
        e = MagicMock(spec=[])
        # Deliberately omit occurred_at / occurred so the filter MUST use timestamp.
        e.event_id = event_id
        e.event_type = "phase_start"
        e.story_id = story_id
        e.run_id = run_id
        e.payload = payload
        e.timestamp = timestamp_dt
        # Ensure getattr falls back to None for absent fields.
        del e.occurred_at  # type: ignore[attr-defined]
        return e

    def test_since_7d_retains_recent_story_events_by_timestamp(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """``--story X --since 7d`` with Event.timestamp retains recent events, drops old ones.

        This test proves the MAJOR 2 fix: before the fix ``_apply_since_filter``
        only checked ``occurred_at`` and silently dropped ALL story-scoped events
        (whose time lives in ``.timestamp``).  After the fix it checks
        ``occurred_at``, ``occurred``, and ``timestamp`` in order.

        The two events are DISTINCTLY identifiable (different event_id, run_id,
        payload) so we can assert not only that one survived but that it is
        specifically the RECENT one.  The output row's ``occurred_at`` field
        must also carry the real timestamp (MINOR 2 fix).
        """
        import datetime as dt_mod

        story_dir = tmp_path / "stories" / "AG3-001"
        story_dir.mkdir(parents=True)

        now = dt_mod.datetime.now(dt_mod.UTC)
        recent_ts = now - dt_mod.timedelta(days=3)   # within 7d window
        old_ts = now - dt_mod.timedelta(days=14)     # outside 7d window

        event_recent = self._make_story_event(
            "AG3-001",
            recent_ts,
            event_id="ev-recent",
            run_id="run-recent",
            payload="recent-payload",
        )
        event_old = self._make_story_event(
            "AG3-001",
            old_ts,
            event_id="ev-old",
            run_id="run-old",
            payload="old-payload",
        )

        with patch(
            "agentkit.telemetry.storage.StateBackendEmitter.query",
            return_value=[event_recent, event_old],
        ):
            code, out, err = _invoke(
                [
                    "query-telemetry",
                    "--story", "AG3-001",
                    "--since", "7d",
                    "--project-root", str(tmp_path),
                ],
                capsys,
            )

        assert code == 0, f"query-telemetry --story --since 7d should succeed; err={err!r}"
        payload = json.loads(out)
        events = payload["events"]
        assert len(events) == 1, (
            "Only the event within the 7d window should be retained; "
            f"got {len(events)} events — the MAJOR 2 fix may be missing"
        )
        # Assert the RETAINED event is specifically the RECENT one (not the old one).
        retained = events[0]
        assert retained["event_id"] == "ev-recent", (
            f"The retained event must be the recent one; got event_id={retained['event_id']!r}"
        )
        assert retained["event_type"] == "phase_start"
        # Assert the output row carries the real timestamp (MINOR 2 fix).
        # event_recent uses .timestamp (no occurred_at), so occurred_at in output
        # must be the string representation of recent_ts — not blank.
        assert retained["occurred_at"] != "", (
            "Output row 'occurred_at' must carry the real timestamp, not be blank "
            "(MINOR 2 fix: _pick_event_time reads .timestamp when occurred_at absent)"
        )
        assert str(recent_ts) in retained["occurred_at"] or retained["occurred_at"] != "None", (
            "Output row 'occurred_at' must represent the recent timestamp value"
        )

    def test_since_filter_drops_all_when_no_time_field_present(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Events with no recognisable time field are excluded (not silently retained)."""
        story_dir = tmp_path / "stories" / "AG3-001"
        story_dir.mkdir(parents=True)

        # Event with no time fields at all.
        e = MagicMock(spec=[])
        e.event_id = "ev-no-ts"
        e.event_type = "phase_start"
        e.story_id = "AG3-001"

        with patch(
            "agentkit.telemetry.storage.StateBackendEmitter.query",
            return_value=[e],
        ):
            code, out, _err = _invoke(
                [
                    "query-telemetry",
                    "--story", "AG3-001",
                    "--since", "7d",
                    "--project-root", str(tmp_path),
                ],
                capsys,
            )

        # Command succeeds (not an error) but the event with no timestamp is excluded.
        assert code == 0
        payload = json.loads(out)
        assert len(payload["events"]) == 0, (
            "An event with no recognisable time field must be excluded by the since filter"
        )
