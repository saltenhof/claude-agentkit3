"""Integration: run_hook dispatches each hook id to the right guard module.

AG3-033 (governance-and-guards.C5): ``self_protection`` (FK-30 §30.5.4) and
``story_creation_guard`` (FK-31 §31.5) now own dedicated guard modules. The
differentiated dispatch must:

- route ``self_protection`` to :func:`_run_self_protection_guard` and
  ``story_creation_guard`` to :func:`_run_story_creation_guard`;
- keep every other pre-hook (branch_guard, qa_agent_guard, ... via
  ``evaluate_pre_tool_use``; ``ccag_gatekeeper`` separately) on its current path;
- run the AG3-032 capability enforcement FIRST — a hard capability DENY
  pre-empts the guards (FK-55 §55.10.3 / AC-8 fail-closed ordering not regressed).

Driven via the real ``run_hook`` and the real PrincipalResolver / classifiers;
no fabricated pipeline state.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from agentkit.governance import runner as runner_mod
from agentkit.governance.guard_evaluation import HookEvent
from agentkit.governance.protocols import GuardVerdict
from agentkit.governance.runner import run_hook

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(autouse=True)
def _sqlite_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    monkeypatch.delenv("AGENTKIT_STATE_DATABASE_URL", raising=False)


def _event(operation: str, operation_args: dict[str, object], **extra: object) -> HookEvent:
    payload: dict[str, object] = {
        "operation": operation,
        "operation_args": operation_args,
        "freshness_class": "mutation",
    }
    payload.update(extra)
    return HookEvent.model_validate(payload)


def test_self_protection_hook_routes_to_self_protection_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def _spy(event: HookEvent) -> GuardVerdict:
        calls.append("self_protection")
        return GuardVerdict.allow("self_protection")

    monkeypatch.setattr(runner_mod, "_run_self_protection_guard", _spy)
    # A non-mutating read reaches the guard (capability layer defers / allows a
    # plain read so the dispatch is exercised).
    event = _event(
        "file_read",
        {"file_path": str(tmp_path / "src" / "x.py")},
        cwd=str(tmp_path),
        principal_kind="main",
    )
    verdict = run_hook("self_protection", event, phase="pre", project_root=tmp_path)
    assert calls == ["self_protection"]
    assert verdict.guard_name == "self_protection"


def test_story_creation_hook_routes_to_story_creation_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def _spy(event: HookEvent) -> GuardVerdict:
        calls.append("story_creation_guard")
        return GuardVerdict.allow("story_creation_guard")

    monkeypatch.setattr(runner_mod, "_run_story_creation_guard", _spy)
    event = _event(
        "file_read",
        {"file_path": str(tmp_path / "src" / "x.py")},
        cwd=str(tmp_path),
        principal_kind="main",
    )
    verdict = run_hook("story_creation_guard", event, phase="pre", project_root=tmp_path)
    assert calls == ["story_creation_guard"]
    assert verdict.guard_name == "story_creation_guard"


def test_other_hook_keeps_generic_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # branch_guard must NOT be routed to the new guards; it stays on
    # evaluate_pre_tool_use.
    def _fail_self(event: HookEvent) -> GuardVerdict:
        raise AssertionError("self_protection guard must not run for branch_guard")

    def _fail_story(event: HookEvent) -> GuardVerdict:
        raise AssertionError("story_creation guard must not run for branch_guard")

    seen: list[str] = []

    def _spy_generic(event: HookEvent, *, project_root: Path) -> GuardVerdict:
        seen.append("generic")
        return GuardVerdict.allow("guard_evaluation")

    monkeypatch.setattr(runner_mod, "_run_self_protection_guard", _fail_self)
    monkeypatch.setattr(runner_mod, "_run_story_creation_guard", _fail_story)
    import agentkit.governance.guard_evaluation as ge_mod

    monkeypatch.setattr(ge_mod, "evaluate_pre_tool_use", _spy_generic)

    event = _event(
        "file_read",
        {"file_path": str(tmp_path / "src" / "x.py")},
        cwd=str(tmp_path),
        principal_kind="main",
    )
    verdict = run_hook("branch_guard", event, phase="pre", project_root=tmp_path)
    assert seen == ["generic"]
    assert verdict.guard_name == "guard_evaluation"


def test_ccag_hook_still_routes_to_ccag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _fail_self(event: HookEvent) -> GuardVerdict:
        raise AssertionError("self_protection guard must not run for ccag_gatekeeper")

    seen: list[str] = []

    def _spy_ccag(event: HookEvent, *, project_root: Path) -> GuardVerdict:
        _ = project_root
        seen.append("ccag")
        return GuardVerdict.allow("ccag_gatekeeper")

    monkeypatch.setattr(runner_mod, "_run_self_protection_guard", _fail_self)
    monkeypatch.setattr(runner_mod, "_run_ccag_hook", _spy_ccag)

    event = _event(
        "file_read",
        {"file_path": str(tmp_path / "src" / "x.py")},
        cwd=str(tmp_path),
        principal_kind="main",
    )
    verdict = run_hook("ccag_gatekeeper", event, phase="pre", project_root=tmp_path)
    assert seen == ["ccag"]
    assert verdict.guard_name == "ccag_gatekeeper"


def test_codex_hooks_json_write_blocked_end_to_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # AG3-033 ERROR A: a visible worker write to .codex/hooks.json (the
    # productive Codex HOOK-settings file, FK-76 §76.5.2) must be blocked
    # end-to-end through the real run_hook for the self_protection hook. The
    # capability layer + self_protection guard together fail-closed; the call is
    # never allowed.
    event = _event(
        "file_write",
        {"file_path": str(tmp_path / ".codex" / "hooks.json")},
        cwd=str(tmp_path),
        principal_kind="subagent",
        cli_args=["--ak3-principal-attest", "worker"],
    )
    verdict = run_hook("self_protection", event, phase="pre", project_root=tmp_path)
    assert verdict.allowed is False


def test_self_protection_blocks_codex_hooks_json_via_guard_direct(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Prove the self_protection GUARD itself (not only the capability layer)
    # owns .codex/hooks.json: drive the guard directly with a project-relative
    # path so the harness zone match fires regardless of capability ordering.
    from agentkit.governance.guards.self_protection_guard import SelfProtectionGuard
    from agentkit.governance.principal_capabilities import (
        OperationClassifier,
        PathClassifier,
        PrincipalResolver,
    )

    event = _event(
        "file_write",
        {"file_path": ".codex/hooks.json"},
        cwd=str(tmp_path),
        principal_kind="subagent",
        cli_args=["--ak3-principal-attest", "worker"],
    )
    verdict = SelfProtectionGuard(
        principal_resolver=PrincipalResolver(),
        path_classifier=PathClassifier(),
        op_classifier=OperationClassifier(),
    ).evaluate(event)
    assert verdict.allowed is False
    assert verdict.guard_name == "self_protection"
    assert verdict.detail is not None
    assert verdict.detail["protection_zone"] == "harness"


def _attested_event(
    operation: str,
    file_path: str,
    *,
    principal: str,
    principal_kind: str,
    cwd: Path,
) -> HookEvent:
    """Build a structurally-attested mutating event for ``principal``."""
    return _event(
        operation,
        {"file_path": file_path},
        cwd=str(cwd),
        principal_kind=principal_kind,
        cli_args=["--ak3-principal-attest", principal],
    )


def test_pipeline_deterministic_codex_hooks_json_allowed_end_to_end(
    tmp_path: Path,
) -> None:
    # AG3-033 (composed pipeline): with .codex/hooks.json now classified as
    # governance_plane (FK-55 §55.4 Guardrail-Zustaende), the capability matrix
    # ALLOWS pipeline_deterministic to WRITE it (FK-55 §55.7 official mutation
    # authority over governance_plane) AND the self_protection guard then narrows
    # the harness zone to pipeline_deterministic only (FK-30 §30.5.4) — so the
    # official Zone-2 installer principal passes the WHOLE pipeline end-to-end.
    # This is exactly the dead-whitelist case the over-narrowing produced before:
    # previously UNCLASSIFIED_MUTATION hard-blocked even pipeline_deterministic.
    event = _attested_event(
        "file_write",
        str(tmp_path / ".codex" / "hooks.json"),
        principal="pipeline_deterministic",
        principal_kind="main",
        cwd=tmp_path,
    )
    verdict = run_hook("self_protection", event, phase="pre", project_root=tmp_path)
    assert verdict.allowed is True


@pytest.mark.parametrize("principal", ["admin_service", "human_cli"])
def test_codex_hooks_json_write_blocked_for_non_installer_principals(
    tmp_path: Path, principal: str
) -> None:
    # AG3-033 (composed pipeline): admin_service / human_cli must NOT be able to
    # write the harness hook-settings. The two principals are blocked for
    # COMPLEMENTARY, both-consistent reasons (and either way the call is denied
    # end-to-end):
    #   - admin_service: capability matrix ALLOWS governance_plane WRITE, so the
    #     self_protection guard runs and DENIES it (harness zone = pipeline only,
    #     FK-30 §30.5.4 / FK-15 §15.4.1 grants no runtime hook-settings writer).
    #   - human_cli: the matrix itself DENIES governance_plane WRITE (only via an
    #     official, deferred service path — fail-closed, matrix_data) so the hard
    #     capability layer blocks before the guard.
    # The visible end-to-end contract is the same: a hard BLOCK.
    event = _attested_event(
        "file_write",
        str(tmp_path / ".codex" / "hooks.json"),
        principal=principal,
        principal_kind="main",
        cwd=tmp_path,
    )
    verdict = run_hook("self_protection", event, phase="pre", project_root=tmp_path)
    assert verdict.allowed is False


@pytest.mark.parametrize("principal", ["pipeline_deterministic", "admin_service"])
def test_governance_config_write_allowed_for_governance_zone_principals(
    tmp_path: Path, principal: str
) -> None:
    # AG3-033 (composed pipeline): the governance config / installer manifest is
    # the governance ZONE (not harness). FK-15 §15.4.1 grants the central-state /
    # lock-record mutation to Pipeline-Skript and (via Admin/CLI) the official
    # admin path. With .agentkit/config/project.yaml classified as
    # governance_plane, the matrix ALLOWS both pipeline_deterministic and
    # admin_service, and the self_protection guard's governance-zone whitelist
    # admits them — so the write passes end-to-end (FK-15 §15.4.1).
    event = _attested_event(
        "file_write",
        str(tmp_path / ".agentkit" / "config" / "project.yaml"),
        principal=principal,
        principal_kind="main",
        cwd=tmp_path,
    )
    verdict = run_hook("self_protection", event, phase="pre", project_root=tmp_path)
    assert verdict.allowed is True


def test_worker_governance_freeze_export_blocked_end_to_end(
    tmp_path: Path,
) -> None:
    # AG3-033 (composed pipeline / regression guard): a worker rm of the
    # governance-plane freeze export stays a hard BLOCK end-to-end. This is the
    # pre-existing governance_plane (.agentkit/governance/**) case — the new
    # self-protection classification must NOT weaken it. worker has no
    # governance_plane mutation in the matrix → hard capability DENY.
    event = _event(
        "bash_command",
        {"command": "rm .agentkit/governance/freeze.json"},
        cwd=str(tmp_path),
        principal_kind="subagent",
        cli_args=["--ak3-principal-attest", "worker"],
    )
    verdict = run_hook("self_protection", event, phase="pre", project_root=tmp_path)
    assert verdict.allowed is False


def test_capability_deny_preempts_self_protection_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # AC-8 / FK-55 §55.10.3: a hard capability DENY (an unattested sub-agent
    # MUTATING an unclassifiable target → UNCLASSIFIED_MUTATION, fail-closed in
    # all modes) must pre-empt the self_protection guard entirely. The guard's
    # dispatch function must NOT be called.
    def _fail_self(event: HookEvent) -> GuardVerdict:
        raise AssertionError("self_protection guard must not run after capability DENY")

    monkeypatch.setattr(runner_mod, "_run_self_protection_guard", _fail_self)

    event = _event(
        "file_write",
        {"file_path": "/elsewhere/random/NOTES.txt"},
        cwd=str(tmp_path),
        principal_kind="subagent",
        cli_args=["--ak3-principal-attest", "worker"],
    )
    verdict = run_hook("self_protection", event, phase="pre", project_root=tmp_path)
    assert verdict.allowed is False
    assert verdict.guard_name == "principal_capability"
