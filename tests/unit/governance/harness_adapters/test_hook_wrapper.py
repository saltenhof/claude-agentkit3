"""End-to-end tests for the agentkit-hook-claude and agentkit-hook-codex CLIs.

Tests the full flow: argv -> stdin parse -> adapter normalisation ->
Governance.run_hook dispatch -> exit code.

Design rationale (CLAUDE.md §MOCKS/STUBS):
  - Post-hook IDs (telemetry, budget, health_monitor):
    Governance.run_hook returns GuardVerdict.allow unconditionally for
    post-phase hooks — no mock needed.
  - Pre-hook IDs review_guard / budget_event_emitter (AG3-036 FIX-1/FIX-3):
    these are the double-role telemetry guards. With no .agentkit/ binding in
    tmp_path there is no active story, so both stay observational (ALLOW) —
    no mock needed.
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

from agentkit.backend.governance.protocols import GuardVerdict
from agentkit.backend.governance.runner import POST_HOOK_IDS, PRE_HOOK_IDS, SUPPORTED_HOOK_IDS
from agentkit.harness_client.harness_adapters.claude_code import main as claude_main
from agentkit.harness_client.harness_adapters.codex.cli import main as codex_main

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

# A genuinely SAFE event is a non-mutating read (mirrors the Codex read_file
# safe event). AG3-032 ERROR 2 / FK-55 §55.10.2: an unknown tool fail-closes to
# WRITE and — with no resolvable target — is now a hard BLOCK in ALL modes (see
# ``test_unknown_tool_event_blocks_fail_closed``), so it can no longer stand in
# for the dispatcher ALLOW path.
_CLAUDE_ALLOW_EVENT = json.dumps(
    {"tool_name": "Read", "tool_input": {"file_path": "a.py"}, "cwd": "."}
)
_CODEX_ALLOW_EVENT = json.dumps(
    {"tool": "read_file", "arguments": {"path": "a.py"}, "cwd": "."}
)
_CLAUDE_POST_ALLOW_EVENT = json.dumps(
    {
        "hook_event_name": "PostToolUse",
        "tool_name": "Read",
        "tool_input": {"file_path": "a.py"},
        "tool_response": {},
        "cwd": ".",
    }
)
_CODEX_POST_ALLOW_EVENT = json.dumps(
    {
        "hook_event_name": "PostToolUse",
        "tool_name": "read_file",
        "tool_input": {"path": "a.py"},
        "tool_response": {},
        "cwd": ".",
    }
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
            "agentkit.backend.governance.runner.Governance.run_hook",
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
            "agentkit.backend.governance.runner.Governance.run_hook",
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
        monkeypatch.setattr("sys.stdin", io.StringIO(_CLAUDE_POST_ALLOW_EVENT))
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
        monkeypatch.setattr("sys.stdin", io.StringIO(_CODEX_POST_ALLOW_EVENT))
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
        # ai_augmented mode (no .agentkit/) + a non-mutating Read -> ALLOW.
        monkeypatch.setattr("sys.stdin", io.StringIO(_CLAUDE_ALLOW_EVENT))
        monkeypatch.chdir(tmp_path)
        result = claude_main(["pre", hook_id])
        assert result == 0, f"Expected 0 (ALLOW) for pre/{hook_id}"

    def test_unknown_tool_event_defers_mode_scharf(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        # AG3-032 ERROR C / FK-55 §55.6.1 (mode-scharf): an UNKNOWN tool (Task /
        # TodoWrite / …) is an UNKNOWN PERMISSION. The enforcement signals
        # UNKNOWN_PERMISSION (the matrix is NOT consulted for an ALLOW). OUTSIDE a
        # story run (here: ai_augmented, no .agentkit/) the runner defers it to an
        # external prompt / CCAG rather than hard-blocking generic interactive
        # work — so the event flows to the legacy guards / CCAG and is allowed
        # (exit 0). Only story_execution would hard-block + open a request.
        event = json.dumps({"tool_name": "Task", "tool_input": {}, "cwd": "."})
        monkeypatch.setattr("sys.stdin", io.StringIO(event))
        monkeypatch.chdir(tmp_path)
        assert claude_main(["pre", "branch_guard"]) == 0

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
    """Force-push command is BLOCKED -- no mock needed.

    FK-55 §55.10.3 / §55.10.7: the hard Principal-Capability layer runs BEFORE
    the legacy guard chain. A free-bash ``git push --force`` is a git_mutation on
    ``git_internal``; the interactive_agent has no such capability (invariant
    ``git_internal_never_mutated_via_free_bash``) so the capability layer blocks
    it first (guard name ``principal_capability``). The operation is still
    blocked with exit 2 — the security property holds; only the (now-earlier)
    blocking layer changed (AG3-032 ERROR 2 — enforcement engages in all modes).
    """

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
        assert payload["guard"] == "principal_capability"

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
        assert payload["guard"] == "principal_capability"


# ---------------------------------------------------------------------------
# SUPPORTED_HOOK_IDS completeness check
# ---------------------------------------------------------------------------


class TestSupportedHookIdsCompleteness:
    """The union of PRE and POST hook IDs equals SUPPORTED_HOOK_IDS."""

    def test_supported_hook_ids_is_union_of_pre_and_post(self) -> None:
        assert SUPPORTED_HOOK_IDS == PRE_HOOK_IDS | POST_HOOK_IDS

    def test_pre_hook_ids_are_known(self) -> None:
        # AG3-031 Pass-2 FK-30-Korrektur 2026-05-24: FK-30 §30.5.1 values.
        # AG3-036 FIX-1: review_guard is a PreToolUse blocking double-role hook.
        # AG3-086 (FK-30 §30.5.1a): ``budget`` blocks PreToolUse via the single
        # governance owner WebCallBudgetGuard; the old ``budget_event_emitter``
        # PreToolUse block double role is REMOVED (the emitter is observational
        # PostToolUse only).
        expected = {
            "branch_guard",
            "orchestrator_guard",
            "integrity",
            "qa_agent_guard",
            "adversarial_guard",
            "self_protection",
            "story_creation_guard",
            "budget",
            "skill_usage_check",
            # AG3-086 (FK-31 §31.7): the new prompt-integrity spawn guard.
            "prompt_integrity",
            "health_monitor",
            "ccag_gatekeeper",
            "review_guard",
            "commit_hook",
        }
        assert expected == PRE_HOOK_IDS

    def test_post_hook_ids_are_known(self) -> None:
        expected = {"telemetry", "budget", "health_monitor", "commit_hook"}
        assert expected == POST_HOOK_IDS
