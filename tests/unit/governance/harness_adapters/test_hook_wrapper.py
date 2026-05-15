"""End-to-end tests for the agentkit-hook-claude and agentkit-hook-codex CLIs.

Tests the full flow: argv -> stdin parse -> adapter normalisation ->
Governance.run_hook dispatch -> exit code.

Design rationale (CLAUDE.md §MOCKS/STUBS):
  - Post-hook IDs (telemetry, review_guard, budget, health_monitor):
    Governance.run_hook returns GuardVerdict.allow unconditionally for
    post-phase hooks — no mock needed.
  - Pre-hook IDs with ``tool_name="Task"`` / ``tool="unknown_tool"``:
    In ``ai_augmented`` mode (no .agentkit/ dir in tmp_path), BranchGuard
    returns ALLOW for ``unknown_tool`` operations — no mock needed.
  - Only the BLOCK path and the invalid-arg path require controlled
    outcomes; those use monkeypatching on Governance.run_hook or rely on
    deterministic guard logic (e.g. force-push command -> BranchGuard
    blocks).
"""

from __future__ import annotations

import io
import json
from typing import TYPE_CHECKING

import pytest

from agentkit.governance.harness_adapters.claude_code import main as claude_main
from agentkit.governance.harness_adapters.codex.cli import main as codex_main
from agentkit.governance.protocols import GuardVerdict
from agentkit.governance.runner import POST_HOOK_IDS, PRE_HOOK_IDS, SUPPORTED_HOOK_IDS

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_CLAUDE_ALLOW_EVENT = json.dumps({"tool_name": "Task", "tool_input": {}, "cwd": "."})
_CODEX_ALLOW_EVENT = json.dumps(
    {"tool": "read_file", "arguments": {"path": "a.py"}, "cwd": "."}
)

_CLAUDE_BLOCK_EVENT = json.dumps(
    {
        "tool_name": "Bash",
        "tool_input": {"command": "git push --force"},
        "cwd": ".",
    }
)
_CODEX_BLOCK_EVENT = json.dumps(
    {
        "tool": "shell_command",
        "arguments": {"command": "git push --force"},
        "cwd": ".",
    }
)


# ---------------------------------------------------------------------------
# AC-1 / AC-2: Both wrappers reachable via main(argv=[...])
# ---------------------------------------------------------------------------


class TestCLIEntryPoints:
    """Both CLI entry points are importable and callable."""

    def test_claude_main_is_callable(self) -> None:
        # If the import fails this test file would not even load.
        assert callable(claude_main)

    def test_codex_main_is_callable(self) -> None:
        assert callable(codex_main)


# ---------------------------------------------------------------------------
# AC-3: Both adapters share the same Governance.run_hook surface
# ---------------------------------------------------------------------------


class TestSharedDispatcher:
    """Both wrappers route through Governance.run_hook (ZERO DEBT / SSoT)."""

    def test_claude_allow_calls_governance_run_hook(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: list[str] = []

        def _spy(hook_id: str, *_args: object, **_kwargs: object) -> GuardVerdict:
            captured.append(hook_id)
            return GuardVerdict.allow("guard_evaluation")

        monkeypatch.setattr(
            "agentkit.governance.runner.Governance.run_hook",
            staticmethod(_spy),
        )
        monkeypatch.setattr("sys.stdin", io.StringIO(_CLAUDE_ALLOW_EVENT))
        result = claude_main(["pre", "branch_guard"])
        assert result == 0
        assert captured == ["branch_guard"]

    def test_codex_allow_calls_governance_run_hook(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: list[str] = []

        def _spy(hook_id: str, *_args: object, **_kwargs: object) -> GuardVerdict:
            captured.append(hook_id)
            return GuardVerdict.allow("guard_evaluation")

        monkeypatch.setattr(
            "agentkit.governance.runner.Governance.run_hook",
            staticmethod(_spy),
        )
        monkeypatch.setattr("sys.stdin", io.StringIO(_CODEX_ALLOW_EVENT))
        result = codex_main(["pre", "branch_guard"])
        assert result == 0
        assert captured == ["branch_guard"]


# ---------------------------------------------------------------------------
# Dispatcher: all 12 hook IDs (PRE + POST) -- real execution, no mocks
# ---------------------------------------------------------------------------


class TestDispatcherAllHookIds:
    """All supported hook_ids reach Governance.run_hook and return exit 0.

    Pre-hook IDs with an "unknown_tool" event in ai_augmented mode (no
    .agentkit/ binding in tmp_path) always allow -- no mock needed.
    Post-hook IDs always allow because run_hook returns allow directly.
    """

    @pytest.mark.parametrize("hook_id", sorted(POST_HOOK_IDS))
    def test_post_hook_ids_allow_claude(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        hook_id: str,
    ) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO(_CLAUDE_ALLOW_EVENT))
        monkeypatch.chdir(tmp_path)
        result = claude_main(["post", hook_id])
        assert result == 0, f"Expected 0 (ALLOW) for post/{hook_id}"

    @pytest.mark.parametrize("hook_id", sorted(POST_HOOK_IDS))
    def test_post_hook_ids_allow_codex(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        hook_id: str,
    ) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO(_CODEX_ALLOW_EVENT))
        monkeypatch.chdir(tmp_path)
        result = codex_main(["post", hook_id])
        assert result == 0, f"Expected 0 (ALLOW) for post/{hook_id}"

    @pytest.mark.parametrize("hook_id", sorted(PRE_HOOK_IDS))
    def test_pre_hook_ids_allow_claude_safe_event(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        hook_id: str,
    ) -> None:
        # ai_augmented mode (no .agentkit/) + unknown_tool -> BranchGuard ALLOWs
        monkeypatch.setattr("sys.stdin", io.StringIO(_CLAUDE_ALLOW_EVENT))
        monkeypatch.chdir(tmp_path)
        result = claude_main(["pre", hook_id])
        assert result == 0, f"Expected 0 (ALLOW) for pre/{hook_id}"

    @pytest.mark.parametrize("hook_id", sorted(PRE_HOOK_IDS))
    def test_pre_hook_ids_allow_codex_safe_event(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        hook_id: str,
    ) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO(_CODEX_ALLOW_EVENT))
        monkeypatch.chdir(tmp_path)
        result = codex_main(["pre", hook_id])
        assert result == 0, f"Expected 0 (ALLOW) for pre/{hook_id}"


# ---------------------------------------------------------------------------
# AC-4: Fail-closed on invalid hook_id and phase
# ---------------------------------------------------------------------------


class TestFailClosedInvalidArgs:
    """Falsche hook_id oder phase -> exit 2, aussagekraeftige stderr-Meldung."""

    def test_unknown_hook_id_claude_returns_exit_2(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO(_CLAUDE_ALLOW_EVENT))
        result = claude_main(["pre", "nonexistent_guard"])
        assert result == 2
        err = capsys.readouterr().err
        assert "nonexistent_guard" in err or "Unknown hook" in err

    def test_unknown_hook_id_codex_returns_exit_2(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO(_CODEX_ALLOW_EVENT))
        result = codex_main(["pre", "nonexistent_guard"])
        assert result == 2
        err = capsys.readouterr().err
        assert "nonexistent_guard" in err or "Unknown hook" in err

    def test_unknown_phase_claude_returns_exit_2(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO(_CLAUDE_ALLOW_EVENT))
        result = claude_main(["during", "branch_guard"])
        assert result == 2
        err = capsys.readouterr().err
        assert "during" in err or "Unknown hook" in err or "Usage" in err

    def test_unknown_phase_codex_returns_exit_2(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO(_CODEX_ALLOW_EVENT))
        result = codex_main(["during", "branch_guard"])
        assert result == 2
        err = capsys.readouterr().err
        assert "during" in err or "Unknown hook" in err or "Usage" in err

    def test_wrong_phase_for_hook_id_claude(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # telemetry is post-only; requesting it as pre should fail-closed
        monkeypatch.setattr("sys.stdin", io.StringIO(_CLAUDE_ALLOW_EVENT))
        result = claude_main(["pre", "telemetry"])
        assert result == 2
        err = capsys.readouterr().err
        assert "telemetry" in err or "Unknown hook" in err

    def test_wrong_phase_for_hook_id_codex(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO(_CODEX_ALLOW_EVENT))
        result = codex_main(["pre", "telemetry"])
        assert result == 2

    def test_missing_args_claude_returns_exit_2(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO(_CLAUDE_ALLOW_EVENT))
        result = claude_main([])
        assert result == 2
        err = capsys.readouterr().err
        assert "Usage" in err

    def test_missing_args_codex_returns_exit_2(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO(_CODEX_ALLOW_EVENT))
        result = codex_main([])
        assert result == 2
        err = capsys.readouterr().err
        assert "Usage" in err


# ---------------------------------------------------------------------------
# Invalid stdin JSON -> exit 2
# ---------------------------------------------------------------------------


class TestInvalidStdin:
    """Ungueltiges stdin-JSON -> exit 2."""

    def test_invalid_json_claude_returns_exit_2(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO("not json at all"))
        result = claude_main(["pre", "branch_guard"])
        assert result == 2
        err = capsys.readouterr().err
        assert err.strip()  # some error message on stderr

    def test_invalid_json_codex_returns_exit_2(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO("not json at all"))
        result = codex_main(["pre", "branch_guard"])
        assert result == 2
        err = capsys.readouterr().err
        assert err.strip()

    def test_json_array_claude_returns_exit_2(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO("[]"))
        result = claude_main(["pre", "branch_guard"])
        assert result == 2

    def test_json_array_codex_returns_exit_2(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO("[]"))
        result = codex_main(["pre", "branch_guard"])
        assert result == 2


# ---------------------------------------------------------------------------
# BLOCK path -- deterministic real guard (no mock)
# ---------------------------------------------------------------------------


class TestBlockPathRealGuard:
    """Force-push command triggers BranchGuard BLOCK -- no mock needed."""

    def test_claude_block_on_force_push_returns_exit_2(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO(_CLAUDE_BLOCK_EVENT))
        monkeypatch.chdir(tmp_path)
        result = claude_main(["pre", "branch_guard"])
        assert result == 2
        out = capsys.readouterr().out
        payload = json.loads(out)
        assert payload["decision"] == "block"
        assert payload["guard"] == "branch_guard"

    def test_codex_block_on_force_push_returns_exit_2(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO(_CODEX_BLOCK_EVENT))
        monkeypatch.chdir(tmp_path)
        result = codex_main(["pre", "branch_guard"])
        assert result == 2
        out = capsys.readouterr().out
        payload = json.loads(out)
        assert payload["decision"] == "block"
        assert payload["guard"] == "branch_guard"


# ---------------------------------------------------------------------------
# SUPPORTED_HOOK_IDS completeness check
# ---------------------------------------------------------------------------


class TestSupportedHookIdsCompleteness:
    """The union of PRE and POST hook IDs equals SUPPORTED_HOOK_IDS."""

    def test_supported_hook_ids_is_union_of_pre_and_post(self) -> None:
        assert SUPPORTED_HOOK_IDS == PRE_HOOK_IDS | POST_HOOK_IDS

    def test_pre_hook_ids_are_known(self) -> None:
        expected = {
            "branch_guard",
            "orchestrator_guard",
            "story_creation_guard",
            "integrity_guard",
            "qa_agent_guard",
            "adversarial_guard",
            "self_protection_guard",
            "health_monitor",
            "ccag_gatekeeper",
        }
        assert expected == PRE_HOOK_IDS

    def test_post_hook_ids_are_known(self) -> None:
        expected = {"telemetry", "review_guard", "budget", "health_monitor"}
        assert expected == POST_HOOK_IDS
