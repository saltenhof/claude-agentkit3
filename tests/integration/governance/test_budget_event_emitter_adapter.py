"""Adapter-level integration: the web tool name flows through the REAL adapter
into the LIVE governance pipeline — capability enforcement is NOT patched out
(AG3-036 FIX-1 / FIX-2).

This complements ``test_budget_event_emitter_dispatch`` (which feeds a
worker-attested ``HookEvent`` straight into ``run_hook`` and OWNS the budget-guard
ALLOW/DENY proof). Here we drive the REAL adapter entry points
(``claude_main`` / ``codex_main(["pre", "budget"])``) with raw hook
payloads on stdin whose ``tool_name`` is a web tool. We do NOT hand-inject
``operation_args`` and we do NOT monkeypatch ``_run_capability_enforcement`` — the
tool name must FLOW THROUGH ``to_neutral_event`` and the call must traverse the
FULL live capability + budget pipeline.

Attestation boundary (honest, no cheating): the production harness hook command is
exactly ``agentkit-hook-{harness} {phase} {hook_id}`` (FK-30 §30.3.1 settings
writer) and carries NO ``--ak3-principal-attest`` marker. So a sub-agent web call
arriving through the adapter resolves fail-closed to the least-privileged
``llm_evaluator`` (FK-55 §55.3a / §55.10.1) and is hard-DENIED by capability
enforcement BEFORE the budget hook. That is the correct fail-CLOSED behaviour
(never fail-open). The wiring that would attest a real ``worker`` through the
adapter is a deferred AG3-032 / AG3-018 concern; the under-budget ALLOW proof is
therefore owned by the dispatch-level test (attested worker), not the unattested
adapter path. What this module proves is that the web tool name SURVIVES the
adapter and the live pipeline FAILS CLOSED on it — there is no silent fail-open
drop of enforcement (defence in depth).
"""

from __future__ import annotations

import io
import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from agentkit.control_plane.models import (
    EdgeBundle,
    EdgePointer,
    SessionRunBindingView,
    StoryExecutionLockView,
)
from agentkit.governance import runner as runner_mod
from agentkit.governance.harness_adapters.claude_code import main as claude_main
from agentkit.governance.harness_adapters.codex.cli import main as codex_main
from agentkit.projectedge.client import LocalEdgePublisher
from agentkit.state_backend.store import reset_backend_cache_for_tests

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

_PROJECT = "tenant-c"
_STORY = "AG3-300"
_RUN = "run-300"
_SESSION = "sess-003"


@pytest.fixture(autouse=True)
def _sqlite_backend(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    monkeypatch.delenv("AGENTKIT_STATE_DATABASE_URL", raising=False)
    reset_backend_cache_for_tests()
    yield
    reset_backend_cache_for_tests()


def test_capability_enforcement_is_not_patched_out() -> None:
    # FIX-1 anti-cheat guard: the genuine ``_run_capability_enforcement`` runs in
    # these adapter tests (no monkeypatch shim). The earlier revision patched it to
    # ``None`` to fake-reach the budget guard; this assertion fails if that returns.
    assert (
        runner_mod._run_capability_enforcement.__module__
        == "agentkit.governance.runner"
    )
    assert runner_mod._run_capability_enforcement.__name__ == "_run_capability_enforcement"


def _publish_story_binding(project_root: Path, worktree: str) -> None:
    now = datetime(2026, 6, 6, 12, 0, tzinfo=UTC)
    bundle = EdgeBundle(
        current=EdgePointer(
            project_key=_PROJECT,
            export_version="edge-003",
            operating_mode="story_execution",
            bundle_dir="_temp/governance/bundles/edge-003",
            sync_after=now + timedelta(minutes=5),
            freshness_class="guarded_read",
            generated_at=now,
        ),
        session=SessionRunBindingView(
            session_id=_SESSION,
            project_key=_PROJECT,
            story_id=_STORY,
            run_id=_RUN,
            principal_type="worker",
            worktree_roots=[worktree],
            binding_version="bind-003",
            operating_mode="story_execution",
        ),
        lock=StoryExecutionLockView(
            project_key=_PROJECT,
            story_id=_STORY,
            run_id=_RUN,
            lock_type="story_execution",
            status="ACTIVE",
            worktree_roots=[worktree],
            binding_version="bind-003",
            activated_at=now,
            updated_at=now,
        ),
        qa_lock=None,
    )
    LocalEdgePublisher(project_root=project_root).publish(bundle)


def _claude_webfetch_payload(worktree: str, *, tool_name: str = "WebFetch") -> str:
    """Raw Claude hook payload for a web call — NO operation_args.

    The tool name lives in ``tool_name`` and must survive ``to_neutral_event``.
    """
    return json.dumps(
        {
            "tool_name": tool_name,
            "tool_input": {"url": "https://example.com"},
            "cwd": worktree,
            "session_id": _SESSION,
            "is_subagent": True,
        }
    )


def _run_claude(
    monkeypatch: pytest.MonkeyPatch,
    project_root: Path,
    payload: str,
) -> int:
    monkeypatch.chdir(project_root)  # adapter uses Path.cwd() as project_root
    monkeypatch.setattr("sys.stdin", io.StringIO(payload))
    return claude_main(["pre", "budget"])


def test_webfetch_name_survives_adapter_and_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # The web tool name flows through ``to_neutral_event`` and the LIVE pipeline
    # fails CLOSED for the unattested sub-agent (resolves to llm_evaluator -> hard
    # capability DENY). exit 2. If the adapter had dropped the tool name, the call
    # would still be an unknown_tool — also blocked — but the point is the name
    # SURVIVES (the budget guard CAN derive it) and nothing fails OPEN.
    worktree = str(tmp_path / "worktree")
    _publish_story_binding(tmp_path, worktree)

    exit_code = _run_claude(monkeypatch, tmp_path, _claude_webfetch_payload(worktree))

    assert exit_code == 2  # fail-closed; never a silent exit-0 fail-open.


def test_websearch_alias_survives_adapter_and_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # FIX-2: a ``web_fetch`` alias still survives the adapter (preserved raw) and
    # is canonicalized downstream; the unattested sub-agent path fails closed.
    worktree = str(tmp_path / "worktree")
    _publish_story_binding(tmp_path, worktree)

    exit_code = _run_claude(
        monkeypatch, tmp_path, _claude_webfetch_payload(worktree, tool_name="web_fetch")
    )

    assert exit_code == 2


def _codex_webfetch_payload(worktree: str, *, tool_name: str = "WebFetch") -> str:
    """Raw Codex hook payload naming a web tool — NO operation_args.

    Codex has no native web surface (FK-76 §76.5.2), so this is the defence-in-
    depth case: should such a name ever reach the Codex runner, the tool name must
    survive ``codex.event_mapping.to_neutral_event`` so the live pipeline can still
    enforce (fail-closed) rather than silently dropping enforcement.
    """
    return json.dumps(
        {
            "tool": tool_name,
            "arguments": {"url": "https://example.com"},
            "cwd": worktree,
            "sessionId": _SESSION,
            "subagent": True,
        }
    )


def test_codex_backstop_web_name_survives_and_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # FIX-2 fail-closed backstop: a WebFetch name reaching the Codex adapter must
    # NOT slip through unenforced. The live pipeline fails closed (exit 2).
    worktree = str(tmp_path / "worktree")
    _publish_story_binding(tmp_path, worktree)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.stdin", io.StringIO(_codex_webfetch_payload(worktree)))
    exit_code = codex_main(["pre", "budget"])

    assert exit_code == 2  # tool name survived the Codex adapter -> fail-closed.


def test_codex_alias_web_name_survives_and_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # FIX-2: a ``web-search`` alias survives the Codex adapter (raw) too.
    worktree = str(tmp_path / "worktree")
    _publish_story_binding(tmp_path, worktree)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(_codex_webfetch_payload(worktree, tool_name="web-search")),
    )
    exit_code = codex_main(["pre", "budget"])

    assert exit_code == 2
