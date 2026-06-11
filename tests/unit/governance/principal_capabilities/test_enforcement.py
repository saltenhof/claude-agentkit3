"""Unit tests for CapabilityEnforcement.evaluate (FK-55 §55.10.3, AK7)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.governance.guard_evaluation import HookEvent
from agentkit.governance.principal_capabilities import (
    CapabilityEnforcement,
    CapabilityMatrix,
    ConflictFreezeOverlay,
    EnforcementOutcome,
    OperationClassifier,
    PathClassifier,
    PrincipalResolver,
)
from agentkit.governance.principal_capabilities.enforcement import (
    UNCLASSIFIED_TARGET_REASON,
)
from agentkit.state_backend.store.freeze_repository import (
    FreezeRepository,
    LocalFreezeJsonExport,
)

if TYPE_CHECKING:
    from pathlib import Path

_STORY = "AG3-001"
_WORKTREE = "/work/wt-AG3-001"
_SCOPE = (_WORKTREE,)
_ATTEST = "--ak3-principal-attest"


def _enforcement(tmp_path: Path) -> CapabilityEnforcement:
    return CapabilityEnforcement(
        principal_resolver=PrincipalResolver(),
        path_classifier=PathClassifier(),
        op_classifier=OperationClassifier(),
        matrix=CapabilityMatrix(),
        freeze=ConflictFreezeOverlay(
            FreezeRepository(tmp_path),
            local_export=LocalFreezeJsonExport(tmp_path),
        ),
    )


def _event(tmp_path: Path, **kwargs: object) -> HookEvent:
    base: dict[str, object] = {
        "operation": "file_write",
        "freshness_class": "mutation",
        "cwd": str(tmp_path),
    }
    base.update(kwargs)
    return HookEvent.model_validate(base)


def test_happy_path_worker_writes_story_scope_allow(tmp_path: Path) -> None:
    # AK7 happy path: an ATTESTED worker writes into a worktree-root story scope
    # → ALLOW. (FK-55 §55.7.1 story scope = worktree roots; ERROR 3/5.)
    event = _event(
        tmp_path,
        principal_kind="subagent",
        session_id="run-1",
        cli_args=[_ATTEST, "worker"],
        operation_args={"file_path": f"{_WORKTREE}/src/module.py"},
    )
    result = _enforcement(tmp_path).evaluate(
        event, project_root=tmp_path, story_id=_STORY, story_scope_roots=_SCOPE
    )
    assert result.outcome is EnforcementOutcome.ALLOW


def test_fail_closed_worker_writes_qa_artifact_deny(tmp_path: Path) -> None:
    # AK7 fail-closed: worker writing a content-plane QA artifact → DENY.
    event = _event(
        tmp_path,
        principal_kind="subagent",
        session_id="run-1",
        cli_args=[_ATTEST, "worker"],
        operation_args={"file_path": f"var/{_STORY}/decision.json"},
    )
    result = _enforcement(tmp_path).evaluate(
        event, project_root=tmp_path, story_id=_STORY, story_scope_roots=_SCOPE
    )
    assert result.outcome is EnforcementOutcome.DENY


def test_unattested_subagent_cannot_write_story_scope(tmp_path: Path) -> None:
    # ERROR 5: an UNATTESTED sub-agent is llm_evaluator (no local fs capability)
    # → even a story-scope write is DENY (not silently granted worker rights).
    event = _event(
        tmp_path,
        principal_kind="subagent",
        session_id="run-1",
        operation_args={"file_path": f"{_WORKTREE}/src/module.py"},
    )
    result = _enforcement(tmp_path).evaluate(
        event, project_root=tmp_path, story_id=_STORY, story_scope_roots=_SCOPE
    )
    assert result.outcome is EnforcementOutcome.DENY


def test_bash_git_internal_mutation_blocked(tmp_path: Path) -> None:
    # ERROR 4 / FK-55 §55.10.2: a Bash mutation under .git is recognised and
    # blocked for a worker even with no git subcommand path arg.
    event = _event(
        tmp_path,
        operation="bash_command",
        principal_kind="subagent",
        session_id="run-1",
        cli_args=[_ATTEST, "worker"],
        operation_args={"command": "rm -rf .git/index"},
    )
    result = _enforcement(tmp_path).evaluate(
        event, project_root=tmp_path, story_id=_STORY, story_scope_roots=_SCOPE
    )
    assert result.outcome is EnforcementOutcome.DENY


def test_bash_git_commit_blocked_for_worker(tmp_path: Path) -> None:
    # ERROR 4: a git mutation (commit) targets git_internal → worker DENY.
    event = _event(
        tmp_path,
        operation="bash_command",
        principal_kind="subagent",
        session_id="run-1",
        cli_args=[_ATTEST, "worker"],
        operation_args={"command": "git commit -m x"},
    )
    result = _enforcement(tmp_path).evaluate(
        event, project_root=tmp_path, story_id=_STORY, story_scope_roots=_SCOPE
    )
    assert result.outcome is EnforcementOutcome.DENY


def test_unclassified_mutation_target_is_unclassified_mutation(tmp_path: Path) -> None:
    # ERROR 2 / FK-55 §55.10.2: an unclassifiable target on a MUTATING op
    # (file_write) yields UNCLASSIFIED_MUTATION with the unclassified_target
    # reason (the runner turns this into a fail-closed BLOCK in ALL modes).
    event = _event(
        tmp_path,
        principal_kind="subagent",
        session_id="run-1",
        cli_args=[_ATTEST, "worker"],
        operation_args={"file_path": "README.md"},
    )
    result = _enforcement(tmp_path).evaluate(
        event, project_root=tmp_path, story_id=_STORY, story_scope_roots=_SCOPE
    )
    assert result.outcome is EnforcementOutcome.UNCLASSIFIED_MUTATION
    assert result.verdict.reason == UNCLASSIFIED_TARGET_REASON


def test_unclassified_nonmutating_target_is_unresolved(tmp_path: Path) -> None:
    # ERROR 2 / FK-55 §55.10.2 + §55.6.1: an unclassifiable target on a
    # NON-mutating op (file_read) is a genuinely non-actionable event →
    # UNRESOLVED (the runner may defer this OUTSIDE a story run, mode-scharf).
    event = _event(
        tmp_path,
        operation="file_read",
        freshness_class="baseline_read",
        principal_kind="subagent",
        session_id="run-1",
        cli_args=[_ATTEST, "worker"],
        operation_args={"file_path": "README.md"},
    )
    result = _enforcement(tmp_path).evaluate(
        event, project_root=tmp_path, story_id=_STORY, story_scope_roots=_SCOPE
    )
    assert result.outcome is EnforcementOutcome.UNRESOLVED
    assert result.verdict.reason == UNCLASSIFIED_TARGET_REASON


def test_unclassified_mutation_via_bash_in_normal_mode(tmp_path: Path) -> None:
    # ERROR 2 / FK-55 §55.10.2: a Bash mutation (rm) on an unclassifiable target
    # is UNCLASSIFIED_MUTATION even with NO story binding (normal mode) — never
    # fail-open. (Path classifies to None; op normalizes to WRITE.)
    event = _event(
        tmp_path,
        operation="bash_command",
        principal_kind="subagent",
        session_id="run-1",
        cli_args=[_ATTEST, "worker"],
        operation_args={"command": "rm /elsewhere/random/NOTES.txt"},
    )
    result = _enforcement(tmp_path).evaluate(
        event, project_root=tmp_path, story_id=None, story_scope_roots=None
    )
    assert result.outcome is EnforcementOutcome.UNCLASSIFIED_MUTATION


def test_mutating_op_no_target_blocks_in_normal_mode(tmp_path: Path) -> None:
    # AG3-032 ERROR 2 / FK-55 §55.10.2: a MUTATING op (file_write) with NO
    # extractable target (empty args) does NOT resolve to an explicit ALLOW and
    # must fail-closed as UNCLASSIFIED_MUTATION in ALL modes — even normal mode
    # (no story binding). The dropped `has_concrete_target` precondition was the
    # fail-open hole: a missing/empty target is now a BLOCK, not UNRESOLVED.
    for args in ({}, {"file_path": ""}):
        event = _event(
            tmp_path,
            principal_kind="subagent",
            session_id="run-1",
            cli_args=[_ATTEST, "worker"],
            operation_args=args,
        )
        result = _enforcement(tmp_path).evaluate(
            event, project_root=tmp_path, story_id=None, story_scope_roots=None
        )
        assert result.outcome is EnforcementOutcome.UNCLASSIFIED_MUTATION
        assert result.verdict.reason == UNCLASSIFIED_TARGET_REASON


def test_unknown_tool_is_unknown_permission_not_allowed(tmp_path: Path) -> None:
    # AG3-032 ERROR C / FK-55 §55.6.1: an UNKNOWN tool is an UNKNOWN PERMISSION.
    # The matrix is NOT consulted for an ALLOW even when the (cwd) target would
    # classify as story_scope and the EXECUTE op would otherwise be matrix-ALLOW
    # for a worker. The outcome is UNKNOWN_PERMISSION in BOTH normal and story
    # mode; the runner resolves it mode-scharf. This is the critical regression
    # fix: an unknown worker tool in story scope was previously ALLOWED.
    event = _event(
        tmp_path,
        operation="unknown_tool",
        principal_kind="subagent",
        session_id="run-1",
        cli_args=[_ATTEST, "worker"],
        operation_args={},
    )
    normal = _enforcement(tmp_path).evaluate(
        event, project_root=tmp_path, story_id=None, story_scope_roots=None
    )
    assert normal.outcome is EnforcementOutcome.UNKNOWN_PERMISSION
    # In a story run with the cwd INSIDE the worktree (story_scope) the EXECUTE op
    # would be a matrix ALLOW — but an unknown TOOL must still be UNKNOWN_PERMISSION
    # (no ALLOW). story_scope_roots include the cwd to make that explicit.
    story_event = _event(
        tmp_path,
        operation="unknown_tool",
        principal_kind="subagent",
        session_id="run-1",
        cli_args=[_ATTEST, "worker"],
        operation_args={},
        cwd=_WORKTREE,
    )
    story = _enforcement(tmp_path).evaluate(
        story_event,
        project_root=tmp_path,
        story_id=_STORY,
        story_scope_roots=_SCOPE,
    )
    assert story.outcome is EnforcementOutcome.UNKNOWN_PERMISSION


def test_unknown_tool_targeting_git_is_hard_deny(tmp_path: Path) -> None:
    # FK-55 §55.10.3 ordering: a hard matrix DENY PRECEDES the unknown-permission
    # rule. An unknown tool whose structured target is under .git (git_internal)
    # is a hard DENY for a worker — not UNKNOWN_PERMISSION.
    event = _event(
        tmp_path,
        operation="unknown_tool",
        principal_kind="subagent",
        session_id="run-1",
        cli_args=[_ATTEST, "worker"],
        operation_args={"file_path": f"{_WORKTREE}/.git/config"},
    )
    result = _enforcement(tmp_path).evaluate(
        event, project_root=tmp_path, story_id=_STORY, story_scope_roots=_SCOPE
    )
    assert result.outcome is EnforcementOutcome.DENY


def test_nonmutating_no_target_remains_unresolved(tmp_path: Path) -> None:
    # AG3-032 ERROR 2 boundary: a NON-mutating op (file_read) with no extractable
    # target is genuinely non-actionable → UNRESOLVED (the runner may defer this
    # OUTSIDE a story run, §55.6.1 mode-scharf). The mutating-op fail-closed rule
    # must NOT over-block reads.
    event = _event(
        tmp_path,
        operation="file_read",
        freshness_class="baseline_read",
        principal_kind="subagent",
        session_id="run-1",
        cli_args=[_ATTEST, "worker"],
        operation_args={},
    )
    result = _enforcement(tmp_path).evaluate(
        event, project_root=tmp_path, story_id=None, story_scope_roots=None
    )
    assert result.outcome is EnforcementOutcome.UNRESOLVED


def test_enforcement_engages_in_normal_mode(tmp_path: Path) -> None:
    # ERROR 2 / FK-55 §55.10.3: enforcement engages with NO story binding
    # (normal mode). An orchestrator-like main writing a content-plane artifact
    # is still a hard DENY — enforcement is not skipped outside a story run.
    event = _event(
        tmp_path,
        principal_kind="main",
        session_id="run-1",  # orchestrator
        operation_args={"file_path": "var/context.json"},
    )
    result = _enforcement(tmp_path).evaluate(
        event, project_root=tmp_path, story_id=None, story_scope_roots=None
    )
    assert result.outcome is EnforcementOutcome.DENY


def test_freeze_overrides_allow(tmp_path: Path) -> None:
    # AK7: an active freeze turns the worker story-scope ALLOW into DENY.
    enforcement = _enforcement(tmp_path)
    enforcement._freeze.freeze(_STORY, reason="normative_conflict", freeze_version=1)
    event = _event(
        tmp_path,
        principal_kind="subagent",
        session_id="run-1",
        cli_args=[_ATTEST, "worker"],
        operation_args={"file_path": f"{_WORKTREE}/src/module.py"},
    )
    result = enforcement.evaluate(
        event, project_root=tmp_path, story_id=_STORY, story_scope_roots=_SCOPE
    )
    assert result.outcome is EnforcementOutcome.DENY


def test_pipeline_closure_service_path_allows_git_mutation(tmp_path: Path) -> None:
    event = _event(
        tmp_path,
        principal_kind="main",
        session_id="run-1",
        cli_args=[_ATTEST, "pipeline_deterministic"],
        operation_args={
            "file_path": ".git/index",
            "service_path": "agentkit run-phase closure",
        },
    )
    result = _enforcement(tmp_path).evaluate(
        event, project_root=tmp_path, story_id=_STORY, story_scope_roots=_SCOPE
    )
    assert result.outcome is EnforcementOutcome.ALLOW_VIA_OFFICIAL_SERVICE_PATH


def test_admin_reset_story_service_path_allows_git_mutation(tmp_path: Path) -> None:
    for principal in ("admin_service", "human_cli"):
        event = _event(
            tmp_path,
            principal_kind="main",
            session_id="run-1",
            cli_args=[_ATTEST, principal],
            operation_args={
                "file_path": ".git/index",
                "service_path": "agentkit reset-story",
            },
        )
        result = _enforcement(tmp_path).evaluate(
            event, project_root=tmp_path, story_id=_STORY, story_scope_roots=_SCOPE
        )
        assert result.outcome is EnforcementOutcome.ALLOW_VIA_OFFICIAL_SERVICE_PATH


def test_bash_spoofed_service_path_is_not_official(tmp_path: Path) -> None:
    event = _event(
        tmp_path,
        operation="bash_command",
        principal_kind="main",
        session_id="run-1",
        cli_args=[_ATTEST, "pipeline_deterministic"],
        operation_args={"command": "agentkit run-phase closure && git commit -m x"},
    )
    result = _enforcement(tmp_path).evaluate(
        event, project_root=tmp_path, story_id=_STORY, story_scope_roots=_SCOPE
    )
    assert result.outcome is EnforcementOutcome.DENY


def test_should_run_ccag_gate(tmp_path: Path) -> None:
    # AK7: CCAG (step 7) runs ONLY when the capability outcome is ALLOW.
    event = _event(
        tmp_path,
        principal_kind="subagent",
        session_id="run-1",
        cli_args=[_ATTEST, "worker"],
        operation_args={"file_path": f"{_WORKTREE}/src/module.py"},
    )
    enforcement = _enforcement(tmp_path)
    allow_result = enforcement.evaluate(
        event, project_root=tmp_path, story_id=_STORY, story_scope_roots=_SCOPE
    )
    assert CapabilityEnforcement.should_run_ccag(allow_result) is True

    deny_event = _event(
        tmp_path,
        principal_kind="main",
        session_id="run-1",  # orchestrator
        operation_args={"file_path": f"{_WORKTREE}/src/module.py"},
    )
    deny_result = enforcement.evaluate(
        deny_event, project_root=tmp_path, story_id=_STORY, story_scope_roots=_SCOPE
    )
    assert deny_result.outcome is EnforcementOutcome.DENY
    assert CapabilityEnforcement.should_run_ccag(deny_result) is False


def test_deny_does_not_invoke_ccag_via_spy(tmp_path: Path) -> None:
    # AK7: on a hard DENY the caller must NOT call CCAG.
    event = _event(
        tmp_path,
        principal_kind="main",
        session_id="run-1",  # orchestrator
        operation_args={"file_path": f"{_WORKTREE}/src/module.py"},
    )
    result = _enforcement(tmp_path).evaluate(
        event, project_root=tmp_path, story_id=_STORY, story_scope_roots=_SCOPE
    )
    assert result.outcome is EnforcementOutcome.DENY

    ccag_calls: list[str] = []

    if CapabilityEnforcement.should_run_ccag(result):
        ccag_calls.append("called")
    assert ccag_calls == []  # CCAG never consulted after a hard DENY.


# ---------------------------------------------------------------------------
# Sub-agent spawn routing (FIX A / FK-31 §31.7 / FK-91 §91.4)
# ---------------------------------------------------------------------------


def _agent_spawn_event(tmp_path: Path, **kwargs: object) -> HookEvent:
    """An ``Agent`` sub-agent spawn as it arrives at the harness-neutral edge."""
    base: dict[str, object] = {
        "operation": "unknown_tool",
        "freshness_class": "guarded_read",
        "cwd": str(tmp_path),
        "operation_args": {"tool_name": "Agent", "description": "", "prompt": ""},
    }
    base.update(kwargs)
    return HookEvent.model_validate(base)


def test_agent_spawn_orchestrator_routes_to_allow_not_path_matrix(
    tmp_path: Path,
) -> None:
    # FIX A: an orchestrator (is_subagent == false) spawning an Agent has no
    # EXECUTE grant on the cwd path-class. The path matrix would DENY it, killing
    # the dedicated prompt_integrity guard. FK-31 §31.7 / FK-91 §91.4: the spawn is
    # a KNOWN control-plane operation routed PAST the path matrix to its dedicated
    # guard -> ALLOW with a hull (so dispatch reaches prompt_integrity).
    event = _agent_spawn_event(tmp_path, principal_kind="main", session_id="run-1")
    result = _enforcement(tmp_path).evaluate(
        event, project_root=tmp_path, story_id=_STORY, story_scope_roots=_SCOPE
    )
    assert result.outcome is EnforcementOutcome.ALLOW
    assert result.hull is not None
    assert result.hull.principal_type == "orchestrator"


def test_agent_spawn_unattested_subagent_routes_to_allow(tmp_path: Path) -> None:
    # FIX A: even an unattested sub-agent (llm_evaluator, no fs capability) spawn
    # is routed to the dedicated guard rather than a path-matrix DENY — the spawn
    # schema is the prompt_integrity guard's authority, not the path matrix.
    event = _agent_spawn_event(tmp_path, principal_kind="subagent", session_id="run-1")
    result = _enforcement(tmp_path).evaluate(
        event, project_root=tmp_path, story_id=_STORY, story_scope_roots=_SCOPE
    )
    assert result.outcome is EnforcementOutcome.ALLOW
    assert result.hull is not None


def test_agent_spawn_is_not_unknown_permission(tmp_path: Path) -> None:
    # FIX A: the spawn must NEVER resolve as UNKNOWN_PERMISSION (the dead-path the
    # §55.6.1 mode-scharf block produced before the fix).
    event = _agent_spawn_event(tmp_path, principal_kind="subagent", session_id="run-1")
    result = _enforcement(tmp_path).evaluate(
        event, project_root=tmp_path, story_id=_STORY, story_scope_roots=_SCOPE
    )
    assert result.outcome is not EnforcementOutcome.UNKNOWN_PERMISSION


def test_non_agent_unknown_tool_still_unknown_permission(tmp_path: Path) -> None:
    # FIX A must NOT weaken the fail-closed for genuinely-unknown tools: any tool
    # the classifier has no rule for (and which is not the named Agent spawn) is
    # still UNKNOWN_PERMISSION (FK-55 §55.6.1).
    event = _agent_spawn_event(
        tmp_path,
        principal_kind="subagent",
        session_id="run-1",
        operation_args={"tool_name": "SomeRandomUnknownTool"},
    )
    result = _enforcement(tmp_path).evaluate(
        event, project_root=tmp_path, story_id=_STORY, story_scope_roots=_SCOPE
    )
    assert result.outcome is EnforcementOutcome.UNKNOWN_PERMISSION


def test_agent_spawn_unfrozen_story_freeze_verdict_allow(tmp_path: Path) -> None:
    # FIX B: an Agent spawn for a NON-frozen story carries the true freeze state in
    # the hull — freeze_verdict == "allow" (the story really is not frozen). The
    # spawn still routes to the dedicated guard (outcome ALLOW).
    event = _agent_spawn_event(tmp_path, principal_kind="main", session_id="run-1")
    result = _enforcement(tmp_path).evaluate(
        event, project_root=tmp_path, story_id=_STORY, story_scope_roots=_SCOPE
    )
    assert result.outcome is EnforcementOutcome.ALLOW
    assert result.hull is not None
    assert result.hull.freeze_verdict == "allow"


def test_agent_spawn_frozen_story_freeze_verdict_is_not_fabricated(
    tmp_path: Path,
) -> None:
    # FIX B: pre-fix the spawn hull HARDCODED freeze_verdict="allow", so a
    # conflict-frozen principal's Agent spawn was reported as freeze-allowed even
    # while the story was frozen. FK-42 §42.2.4 (the hull must report the ACTUAL
    # freeze/matrix verdicts) + FK-55 §55.8.2 (the freeze exists precisely to stop
    # an orchestrator spawning fresh sub-agents to circumvent guard barriers after
    # a HARD STOP): the hull must surface the REAL is_frozen() state.
    enforcement = _enforcement(tmp_path)
    enforcement._freeze.freeze(_STORY, reason="normative_conflict", freeze_version=1)
    event = _agent_spawn_event(tmp_path, principal_kind="main", session_id="run-1")
    result = enforcement.evaluate(
        event, project_root=tmp_path, story_id=_STORY, story_scope_roots=_SCOPE
    )
    # The spawn op-class (EXECUTE / control_plane_spawn) is OUTSIDE the freeze
    # overlay scope (FK-55 §55.10.6 = write/git_mutation/curate/admin_transition),
    # so the capability layer does NOT itself hard-DENY the spawn — it still routes
    # to the dedicated guard + CCAG (outcome ALLOW). But the hull's freeze_verdict
    # must be the NON-fabricated real state: "deny" (story is frozen), so CCAG /
    # the §55.8.2 adjudication downstream sees a real freeze signal.
    assert result.outcome is EnforcementOutcome.ALLOW
    assert result.hull is not None
    assert result.hull.freeze_verdict == "deny"
