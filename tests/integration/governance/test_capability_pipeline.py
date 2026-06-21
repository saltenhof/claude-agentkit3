"""Integration: run_hook runs CapabilityEnforcement before CCAG (AK7/AK8, B5 fix).

FK-55 §55.10.3 / FK-30 §30.2.6: in an active story run the hard Principal-
Capability matrix + freeze overlay run BEFORE the legacy guard chain and BEFORE
CCAG. A capability DENY is hard — CCAG is never consulted and cannot soften it.
The capability layer is story-scoped: it engages only when a story-execution
binding is published (otherwise the legacy guards / CCAG govern).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.control_plane.models import (
    EdgeBundle,
    EdgePointer,
    SessionRunBindingView,
    StoryExecutionLockView,
)
from agentkit.backend.governance import runner as runner_mod
from agentkit.backend.governance.guard_evaluation import HookEvent
from agentkit.backend.governance.runner import run_hook
from agentkit.harness_client.projectedge.client import LocalEdgePublisher

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

_STORY = "AG3-100"
_SESSION = "sess-001"


@pytest.fixture(autouse=True)
def _sqlite_backend(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    monkeypatch.delenv("AGENTKIT_STATE_DATABASE_URL", raising=False)
    yield


def _publish_story_binding(
    project_root: Path,
    worktree: str,
    *,
    lock_status: str = "ACTIVE",
) -> None:
    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    bundle = EdgeBundle(
        current=EdgePointer(
            project_key="tenant-a",
            export_version="edge-001",
            operating_mode="story_execution",
            bundle_dir="_temp/governance/bundles/edge-001",
            sync_after=now + timedelta(minutes=5),
            freshness_class="guarded_read",
            generated_at=now,
        ),
        session=SessionRunBindingView(
            session_id=_SESSION,
            project_key="tenant-a",
            story_id=_STORY,
            run_id="run-100",
            principal_type="orchestrator",
            worktree_roots=[worktree],
            binding_version="bind-001",
            operating_mode="story_execution",
        ),
        lock=StoryExecutionLockView(
            project_key="tenant-a",
            story_id=_STORY,
            run_id="run-100",
            lock_type="story_execution",
            status=lock_status,
            worktree_roots=[worktree],
            binding_version="bind-001",
            activated_at=now,
            updated_at=now,
        ),
        qa_lock=None,
    )
    LocalEdgePublisher(project_root=project_root).publish(bundle)


def _write_corrupt_freeze_export(project_root: Path) -> None:
    """Write a corrupt local freeze.json export (invalid JSON) under project_root."""
    export = project_root / ".agentkit" / "governance" / "freeze.json"
    export.parent.mkdir(parents=True, exist_ok=True)
    export.write_text("{ this is not valid json ", encoding="utf-8")


def test_corrupt_freeze_export_blocks_not_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # ERROR 6 / FK-55 §55.10.5 / FK-31 §31.2.7: a corrupt local freeze export is a
    # stale/incoherent freeze context → fail-closed BLOCK, NOT an escaping
    # runtime exception. run_hook must return a principal_capability BLOCK.
    # Scenario: an attested worker write into story scope would be ALLOWED by the
    # matrix; worker is a frozen principal + WRITE is mutating, so the freeze
    # overlay consults the (corrupt) local export and the fault must be caught.
    worktree = str(tmp_path / "worktree")
    _publish_story_binding(tmp_path, worktree)
    _write_corrupt_freeze_export(tmp_path)

    def _spy_ccag(event: HookEvent, *, project_root: object = None) -> object:
        _ = project_root
        raise AssertionError("CCAG must not run after a fail-closed freeze fault")

    monkeypatch.setattr(runner_mod, "_run_ccag_hook", _spy_ccag)

    event = HookEvent.model_validate(
        {
            "operation": "file_write",
            "freshness_class": "mutation",
            "cwd": worktree,
            "principal_kind": "subagent",
            "session_id": _SESSION,
            "cli_args": ["--ak3-principal-attest", "worker"],
            "operation_args": {"file_path": f"{worktree}/src/module.py"},
        }
    )
    # Must NOT raise; must return a deterministic fail-closed BLOCK.
    verdict = run_hook("ccag_gatekeeper", event, phase="pre", project_root=tmp_path)
    assert verdict.allowed is False
    assert verdict.guard_name == "principal_capability"
    assert verdict.detail is not None
    assert verdict.detail.get("fault_class") == "FreezePersistenceError"


def test_freeze_repository_backend_fault_blocks_not_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # ERROR D / FAIL-CLOSED: the injected FreezeRepository raises a PLAIN
    # RuntimeError when its backend is unusable (SQLite disabled / no Postgres
    # URL). That fault is raised INSIDE the freeze read during capability
    # evaluation (worker = frozen principal + WRITE = mutating → the overlay
    # consults the backend record). run_hook must catch it and return a
    # deterministic capability-fault BLOCK (exit 2), NEVER an unhandled raise.
    worktree = str(tmp_path / "worktree")
    _publish_story_binding(tmp_path, worktree)
    # Disable the SQLite backend so FreezeRepository.read_freeze raises RuntimeError.
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.delenv("AGENTKIT_ALLOW_SQLITE", raising=False)
    monkeypatch.delenv("AGENTKIT_STATE_DATABASE_URL", raising=False)

    def _spy_ccag(event: HookEvent, *, project_root: object = None) -> object:
        _ = project_root
        raise AssertionError("CCAG must not run after a fail-closed backend fault")

    monkeypatch.setattr(runner_mod, "_run_ccag_hook", _spy_ccag)

    event = HookEvent.model_validate(
        {
            "operation": "file_write",
            "freshness_class": "mutation",
            "cwd": worktree,
            "principal_kind": "subagent",
            "session_id": _SESSION,
            "cli_args": ["--ak3-principal-attest", "worker"],
            "operation_args": {"file_path": f"{worktree}/src/module.py"},
        }
    )
    # Must NOT raise; must return a deterministic fail-closed BLOCK.
    verdict = run_hook("ccag_gatekeeper", event, phase="pre", project_root=tmp_path)
    assert verdict.allowed is False
    assert verdict.guard_name == "principal_capability"
    assert verdict.detail is not None
    assert verdict.detail.get("fault_class") == "RuntimeError"


def test_capability_deny_blocks_before_ccag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # AK8: an orchestrator writing into the story worktree is a hard capability
    # DENY. CCAG must NOT be invoked. We spy on the CCAG hook entry point.
    worktree = str(tmp_path / "worktree")
    _publish_story_binding(tmp_path, worktree)

    def _spy_ccag(event: HookEvent, *, project_root: object = None) -> object:
        _ = project_root
        raise AssertionError("CCAG must not run after a hard capability DENY")

    monkeypatch.setattr(runner_mod, "_run_ccag_hook", _spy_ccag)

    event = HookEvent.model_validate(
        {
            "operation": "file_write",
            "freshness_class": "mutation",
            "cwd": worktree,
            "principal_kind": "main",  # orchestrator (active story binding)
            "session_id": _SESSION,
            "operation_args": {"file_path": f"{worktree}/src/module.py"},
        }
    )
    verdict = run_hook("ccag_gatekeeper", event, phase="pre", project_root=tmp_path)
    assert verdict.allowed is False
    assert verdict.guard_name == "principal_capability"


def test_capability_allow_proceeds_to_ccag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # AK8: a permitted operation (an attested worker reading inside its story
    # worktree scope) passes the capability gate and reaches the CCAG dispatch
    # (step 7). The worker role comes from the structural attestation (ERROR 5).
    worktree = str(tmp_path / "worktree")
    _publish_story_binding(tmp_path, worktree)

    ccag_calls: list[str] = []

    def _spy_ccag(event: HookEvent, *, project_root: object = None) -> object:
        _ = project_root
        from agentkit.backend.governance.protocols import GuardVerdict

        ccag_calls.append("ccag")
        return GuardVerdict.allow("ccag_gatekeeper")

    monkeypatch.setattr(runner_mod, "_run_ccag_hook", _spy_ccag)

    event = HookEvent.model_validate(
        {
            "operation": "file_read",
            "freshness_class": "guarded_read",
            "cwd": worktree,
            "principal_kind": "subagent",
            "session_id": _SESSION,
            "cli_args": ["--ak3-principal-attest", "worker"],
            "operation_args": {"file_path": f"{worktree}/src/module.py"},
        }
    )
    verdict = run_hook("ccag_gatekeeper", event, phase="pre", project_root=tmp_path)
    assert verdict.allowed is True
    assert ccag_calls == ["ccag"]


def test_capability_unclassified_target_blocks_in_story_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # ERROR 1 + 2 / FK-55 §55.10.2: in story_execution an unclassifiable target
    # is a fail-closed BLOCK (unclassified_target). CCAG must NOT be consulted.
    worktree = str(tmp_path / "worktree")
    _publish_story_binding(tmp_path, worktree)

    def _spy_ccag(event: HookEvent, *, project_root: object = None) -> object:
        _ = project_root
        raise AssertionError("CCAG must not run after a fail-closed BLOCK")

    monkeypatch.setattr(runner_mod, "_run_ccag_hook", _spy_ccag)

    event = HookEvent.model_validate(
        {
            "operation": "file_write",
            "freshness_class": "mutation",
            "cwd": worktree,
            "principal_kind": "subagent",
            "session_id": _SESSION,
            "cli_args": ["--ak3-principal-attest", "worker"],
            "operation_args": {"file_path": "/elsewhere/random/NOTES.txt"},
        }
    )
    verdict = run_hook("ccag_gatekeeper", event, phase="pre", project_root=tmp_path)
    assert verdict.allowed is False
    assert verdict.guard_name == "principal_capability"


def test_capability_engages_in_normal_mode_blocks_protected_zone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # ERROR 2 / FK-55 §55.10.3: with NO story binding (normal mode) enforcement
    # still engages — it is NOT skipped/fail-open. A main orchestrator writing a
    # content-plane artifact is a hard DENY in normal mode too. CCAG never runs.
    def _spy_ccag(event: HookEvent, *, project_root: object = None) -> object:
        _ = project_root
        raise AssertionError("CCAG must not run after a hard capability DENY")

    monkeypatch.setattr(runner_mod, "_run_ccag_hook", _spy_ccag)

    event = HookEvent.model_validate(
        {
            "operation": "file_write",
            "freshness_class": "mutation",
            "cwd": str(tmp_path),
            "principal_kind": "main",  # orchestrator (session bound, no story)
            "session_id": _SESSION,
            "operation_args": {"file_path": "var/context.json"},
        }
    )
    verdict = run_hook("ccag_gatekeeper", event, phase="pre", project_root=tmp_path)
    assert verdict.allowed is False
    assert verdict.guard_name == "principal_capability"


def test_capability_normal_mode_defers_unclassified_nonmutating_to_ccag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # ERROR 2 / FK-55 §55.6.1 (mode-scharf): outside a story run an unclassifiable
    # NON-mutating target (a pure read) is NOT a hard block — it defers to CCAG /
    # the mode rule (the §55.6.1 unknown-permission rule only blocks in
    # story_execution). This keeps legitimate interactive READ work flowing
    # WITHOUT bypassing enforcement.
    ccag_calls: list[str] = []

    def _spy_ccag(event: HookEvent, *, project_root: object = None) -> object:
        _ = project_root
        from agentkit.backend.governance.protocols import GuardVerdict

        ccag_calls.append("ccag")
        return GuardVerdict.allow("ccag_gatekeeper")

    monkeypatch.setattr(runner_mod, "_run_ccag_hook", _spy_ccag)

    event = HookEvent.model_validate(
        {
            "operation": "file_read",
            "freshness_class": "baseline_read",
            "cwd": str(tmp_path),
            "principal_kind": "main",
            # No session → interactive_agent, no story binding → normal mode.
            "operation_args": {"file_path": "README.md"},
        }
    )
    verdict = run_hook("ccag_gatekeeper", event, phase="pre", project_root=tmp_path)
    assert verdict.allowed is True
    assert ccag_calls == ["ccag"]


def test_capability_normal_mode_blocks_unclassified_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # ERROR 2 / FK-55 §55.10.2: outside a story run (normal mode) an unclassified
    # MUTATION target is a fail-closed BLOCK in ALL modes — normal mode is NOT a
    # fail-open escape. The §55.6.1 deferral applies only to non-mutating events.
    # CCAG must NOT be consulted.
    def _spy_ccag(event: HookEvent, *, project_root: object = None) -> object:
        _ = project_root
        raise AssertionError("CCAG must not run after an unclassified-mutation BLOCK")

    monkeypatch.setattr(runner_mod, "_run_ccag_hook", _spy_ccag)

    event = HookEvent.model_validate(
        {
            "operation": "file_write",
            "freshness_class": "mutation",
            "cwd": str(tmp_path),
            "principal_kind": "main",
            # No session → interactive_agent, no story binding → normal mode.
            "operation_args": {"file_path": "/elsewhere/random/NOTES.txt"},
        }
    )
    verdict = run_hook("ccag_gatekeeper", event, phase="pre", project_root=tmp_path)
    assert verdict.allowed is False
    assert verdict.guard_name == "principal_capability"


def test_capability_unknown_tool_normal_mode_defers_to_ccag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # FK-55 §55.6.1 (corrected): outside a story run an UNKNOWN tool (Task /
    # TodoWrite / … — NOT WebFetch/WebSearch, which are now a KNOWN READ per
    # AG3-036 FIX-1) is an UNKNOWN PERMISSION, not a mutation. It
    # normalizes to the inert EXECUTE; with no file/mutation target it is
    # UNRESOLVED and — mode-scharf — defers to CCAG / the mode rule rather than
    # hard-blocking generic interactive work. CCAG must be consulted (NOT a hard
    # capability block). This is the over-block this rework removes.
    ccag_calls: list[str] = []

    def _spy_ccag(event: HookEvent, *, project_root: object = None) -> object:
        _ = project_root
        from agentkit.backend.governance.protocols import GuardVerdict

        ccag_calls.append("ccag")
        return GuardVerdict.allow("ccag_gatekeeper")

    monkeypatch.setattr(runner_mod, "_run_ccag_hook", _spy_ccag)

    event = HookEvent.model_validate(
        {
            "operation": "unknown_tool",
            "freshness_class": "baseline_read",
            "cwd": str(tmp_path),
            "principal_kind": "main",
            # No session → interactive_agent, no story binding → normal mode.
            "operation_args": {"todos": []},
        }
    )
    verdict = run_hook("ccag_gatekeeper", event, phase="pre", project_root=tmp_path)
    assert verdict.allowed is True
    assert ccag_calls == ["ccag"]


def test_capability_unknown_tool_story_mode_blocks_and_opens_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # AG3-032 ERROR C / FK-55 §55.6.1 (mode-scharf): in story_execution an UNKNOWN
    # tool is an UNKNOWN_PERMISSION. Even at the worktree (a story_scope target
    # that would make an EXECUTE matrix-ALLOW), an unknown TOOL must NOT be
    # allowed — the runner fail-closes it to a hard BLOCK AND opens an auditable
    # permission_request (no native prompt may hang a run). CCAG must NOT run.
    # cwd == the worktree so the locally-derived execution_mode is genuinely
    # story_execution (this is the CRITICAL regression case: an unknown worker
    # tool in story scope was previously ALLOWED).
    worktree = str(tmp_path / "worktree")
    _publish_story_binding(tmp_path, worktree)

    def _spy_ccag(event: HookEvent, *, project_root: object = None) -> object:
        _ = project_root
        raise AssertionError("CCAG must not run after a story-mode unknown-permission block")

    monkeypatch.setattr(runner_mod, "_run_ccag_hook", _spy_ccag)

    event = HookEvent.model_validate(
        {
            "operation": "unknown_tool",
            "freshness_class": "baseline_read",
            "cwd": worktree,  # at the worktree → genuine story_execution mode.
            "principal_kind": "subagent",
            "session_id": _SESSION,
            "cli_args": ["--ak3-principal-attest", "worker"],
            "operation_args": {"todos": []},
        }
    )
    verdict = run_hook("ccag_gatekeeper", event, phase="pre", project_root=tmp_path)
    assert verdict.allowed is False
    assert verdict.guard_name == "principal_capability"
    # FK-55 §55.6.1: a permission_request must be opened (auditable, not a prompt).
    assert verdict.detail is not None
    assert verdict.detail.get("permission_request_opened") is True
    assert verdict.detail.get("permission_request_id")


def _binding_invalid_event_kwargs(*, operation: str) -> dict[str, object]:
    """Operation_args for the two probe shapes used by the binding_invalid tests.

    - ``unknown_tool``  → an UNKNOWN_PERMISSION (a tool with no matrix zone).
    - ``file_read``     → an UNRESOLVED non-mutating event (unclassifiable target,
      a pure read that cannot be classified to a story-scope PathClass).
    """
    if operation == "unknown_tool":
        return {"todos": []}
    return {"file_path": "/elsewhere/random/NOTES.txt"}


@pytest.mark.parametrize(
    ("session_id", "cwd_fn", "lock_status", "expected_reason"),
    [
        # session_binding_mismatch: a lock+session EXIST but the live session id
        # does not match the bound session id.
        ("sess-OTHER", lambda wt, tp: wt, "ACTIVE", "session_binding_mismatch"),
        # inactive_story_execution_lock: the matching session id but the lock is
        # not ACTIVE.
        (_SESSION, lambda wt, tp: wt, "INACTIVE", "inactive_story_execution_lock"),
        # worktree_root_mismatch: matching session + ACTIVE lock but cwd is OUTSIDE
        # the bound worktree roots.
        (_SESSION, lambda wt, tp: str(tp), "ACTIVE", "worktree_root_mismatch"),
    ],
    ids=[
        "session_binding_mismatch",
        "inactive_story_execution_lock",
        "worktree_root_mismatch",
    ],
)
@pytest.mark.parametrize("operation", ["unknown_tool", "file_read"])
def test_binding_invalid_fail_closed_blocks_without_ccag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    session_id: str,
    cwd_fn: object,
    lock_status: str,
    expected_reason: str,
    operation: str,
) -> None:
    # AG3-032 / FK-55 §55.10.1/§55.10.4 (FK-56 §51, FK-59 §175): an INCONSISTENT
    # story-execution binding (binding_invalid) is fail-closed HARD BLOCK for an
    # UNKNOWN_PERMISSION (unknown_tool) AND for an UNRESOLVED non-mutating event
    # (unclassifiable file_read). A broken binding must NOT degrade to free mode
    # and must NOT defer to CCAG. Previously these returned None → ccag_gatekeeper
    # → allow (the confirmed fail-open). CCAG must NOT be consulted.
    worktree = str(tmp_path / "worktree")
    _publish_story_binding(tmp_path, worktree, lock_status=lock_status)

    def _spy_ccag(event: HookEvent, *, project_root: object = None) -> object:
        _ = project_root
        raise AssertionError(
            "CCAG must not run for a binding_invalid fail-closed block"
        )

    monkeypatch.setattr(runner_mod, "_run_ccag_hook", _spy_ccag)

    cwd = cwd_fn(worktree, tmp_path)  # type: ignore[operator]
    event = HookEvent.model_validate(
        {
            "operation": operation,
            "freshness_class": "baseline_read",
            "cwd": cwd,
            "principal_kind": "subagent",
            "session_id": session_id,
            "cli_args": ["--ak3-principal-attest", "worker"],
            "operation_args": _binding_invalid_event_kwargs(operation=operation),
        }
    )
    verdict = run_hook("ccag_gatekeeper", event, phase="pre", project_root=tmp_path)
    # Fail-closed HARD BLOCK from the capability layer (NOT a ccag_gatekeeper
    # verdict, NOT a grantable in-story permission_request).
    assert verdict.allowed is False
    assert verdict.guard_name == "principal_capability"
    assert verdict.detail is not None
    assert verdict.detail.get("operating_mode") == "binding_invalid"
    assert verdict.detail.get("block_reason") == expected_reason
    assert verdict.detail.get("capability_rule_id") == "FK-55-55.10.1/55.10.4"
    # A broken binding is NOT a grantable in-story permission: no request opened.
    assert "permission_request_opened" not in verdict.detail


def test_ai_augmented_unknown_tool_still_defers_to_ccag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Regression guard: genuine ai_augmented (NO lock/session at all) is the ONLY
    # mode that may defer. An unknown tool here must still reach CCAG (NOT a
    # binding_invalid block). This proves the three-way split did not over-block
    # the genuine free mode.
    ccag_calls: list[str] = []

    def _spy_ccag(event: HookEvent, *, project_root: object = None) -> object:
        _ = project_root
        from agentkit.backend.governance.protocols import GuardVerdict

        ccag_calls.append("ccag")
        return GuardVerdict.allow("ccag_gatekeeper")

    monkeypatch.setattr(runner_mod, "_run_ccag_hook", _spy_ccag)

    # No story binding published → resolver returns ai_augmented, bundle None.
    event = HookEvent.model_validate(
        {
            "operation": "unknown_tool",
            "freshness_class": "baseline_read",
            "cwd": str(tmp_path),
            "principal_kind": "main",
            "operation_args": {"todos": []},
        }
    )
    verdict = run_hook("ccag_gatekeeper", event, phase="pre", project_root=tmp_path)
    assert verdict.allowed is True
    assert ccag_calls == ["ccag"]


def test_capability_normal_mode_blocks_bash_mutation_chain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # ERROR 4 + 2 / FK-55 §55.10.2: a chained Bash mutation under .git (hidden
    # behind a benign leading command) is recognised and blocked even in normal
    # mode. CCAG must NOT be consulted.
    def _spy_ccag(event: HookEvent, *, project_root: object = None) -> object:
        _ = project_root
        raise AssertionError("CCAG must not run after a hard capability BLOCK")

    monkeypatch.setattr(runner_mod, "_run_ccag_hook", _spy_ccag)

    event = HookEvent.model_validate(
        {
            "operation": "bash_command",
            "freshness_class": "mutation",
            "cwd": str(tmp_path),
            "principal_kind": "main",
            "session_id": _SESSION,  # orchestrator, no story binding
            "operation_args": {"command": "git status && rm .git/index"},
        }
    )
    verdict = run_hook("ccag_gatekeeper", event, phase="pre", project_root=tmp_path)
    assert verdict.allowed is False
    assert verdict.guard_name == "principal_capability"
