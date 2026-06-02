"""Unit tests for :class:`SelfProtectionGuard` (FK-30 §30.5.4).

Drives the guard via real :class:`HookEvent`s and the real PrincipalResolver /
PathClassifier / OperationClassifier (no fabricated pipeline state, no mocks —
CLAUDE.md MOCKS/STUBS NUR IM ENGEN AUSNAHMEFALL).
"""

from __future__ import annotations

import pytest

from agentkit.governance.guard_evaluation import HookEvent
from agentkit.governance.guards.self_protection_guard import (
    RULE_ID,
    SelfProtectionGuard,
)
from agentkit.governance.principal_capabilities import (
    OperationClassifier,
    PathClassifier,
    PrincipalResolver,
)


def _guard() -> SelfProtectionGuard:
    return SelfProtectionGuard(
        principal_resolver=PrincipalResolver(),
        path_classifier=PathClassifier(),
        op_classifier=OperationClassifier(),
    )


def _event(
    *,
    operation: str,
    operation_args: dict[str, object],
    principal_kind: str = "subagent",
    attest: str | None = None,
    session_id: str | None = None,
) -> HookEvent:
    cli_args = ["--ak3-principal-attest", attest] if attest is not None else None
    return HookEvent.model_validate(
        {
            "operation": operation,
            "operation_args": operation_args,
            "freshness_class": "mutation",
            "cwd": "/proj",
            "principal_kind": principal_kind,
            "session_id": session_id,
            "cli_args": cli_args,
        }
    )


class TestSelfProtectionDeny:
    """Non-official principals must not mutate protected governance paths."""

    def test_worker_write_claude_settings_denied(self) -> None:
        verdict = _guard().evaluate(
            _event(
                operation="file_write",
                operation_args={"file_path": ".claude/settings.json"},
                attest="worker",
            )
        )
        assert verdict.allowed is False
        assert verdict.guard_name == "self_protection"
        assert verdict.detail is not None
        assert verdict.detail["rule_id"] == RULE_ID

    def test_worker_edit_codex_config_denied(self) -> None:
        verdict = _guard().evaluate(
            _event(
                operation="file_edit",
                operation_args={"file_path": ".codex/config.toml"},
                attest="worker",
            )
        )
        assert verdict.allowed is False

    def test_worker_write_codex_hooks_json_denied(self) -> None:
        # AG3-033 ERROR A: .codex/hooks.json is the productive Codex HOOK-settings
        # file (FK-76 §76.5.2 / CodexSettingsWriter); a visible write must block.
        verdict = _guard().evaluate(
            _event(
                operation="file_write",
                operation_args={"file_path": ".codex/hooks.json"},
                attest="worker",
            )
        )
        assert verdict.allowed is False
        assert verdict.detail is not None
        assert verdict.detail["protection_zone"] == "harness"

    def test_worker_write_canonical_ccag_rules_denied(self) -> None:
        # AG3-033 ERROR A: FK-15 §15.7.1 lists the canonical .agentkit/ccag/rules/
        # as a protected path (not just the .claude/ccag/rules symlink).
        verdict = _guard().evaluate(
            _event(
                operation="file_write",
                operation_args={"file_path": ".agentkit/ccag/rules/subagents.yaml"},
                attest="worker",
            )
        )
        assert verdict.allowed is False
        assert verdict.detail is not None
        assert verdict.detail["protection_zone"] == "harness"

    def test_worker_write_skill_symlink_denied(self) -> None:
        verdict = _guard().evaluate(
            _event(
                operation="file_write",
                operation_args={"file_path": ".claude/skills/create-userstory/SKILL.md"},
                attest="worker",
            )
        )
        assert verdict.allowed is False

    def test_worker_write_project_yaml_denied(self) -> None:
        verdict = _guard().evaluate(
            _event(
                operation="file_write",
                operation_args={"file_path": ".agentkit/config/project.yaml"},
                attest="worker",
            )
        )
        assert verdict.allowed is False

    def test_worker_write_installed_manifest_denied(self) -> None:
        verdict = _guard().evaluate(
            _event(
                operation="file_write",
                operation_args={"file_path": ".installed-manifest.json"},
                attest="worker",
            )
        )
        assert verdict.allowed is False

    def test_shell_rm_freeze_export_by_worker_denied(self) -> None:
        verdict = _guard().evaluate(
            _event(
                operation="bash_command",
                operation_args={"command": "rm .agentkit/governance/freeze.json"},
                attest="worker",
            )
        )
        assert verdict.allowed is False
        assert verdict.detail is not None
        assert verdict.detail["operation_class"] == "write"

    def test_shell_rm_agent_guard_lock_by_worker_denied(self) -> None:
        verdict = _guard().evaluate(
            _event(
                operation="bash_command",
                operation_args={"command": "rm .agent-guard/lock.json"},
                attest="worker",
            )
        )
        assert verdict.allowed is False

    def test_write_git_internals_denied(self) -> None:
        verdict = _guard().evaluate(
            _event(
                operation="file_write",
                operation_args={"file_path": ".git/index"},
                attest="worker",
            )
        )
        assert verdict.allowed is False

    def test_unattested_subagent_denied(self) -> None:
        # An unattested sub-agent fails closed to llm_evaluator — not official.
        verdict = _guard().evaluate(
            _event(
                operation="file_write",
                operation_args={"file_path": ".claude/settings.json"},
                attest=None,
            )
        )
        assert verdict.allowed is False


class TestSelfProtectionHarnessZone:
    """harness zone (hook settings / symlinks): ONLY pipeline_deterministic.

    AG3-033 ERROR B: the harness binding points are installer-only (FK-30
    §30.3.1 "Aufrufer: Installer", a Zone-2 process). FK-15 §15.4.1 grants no
    runtime writer; concept silent → fail-closed to pipeline only. admin_service
    / human_cli must NOT bypass the harness zone.
    """

    def test_pipeline_write_settings_allowed(self) -> None:
        verdict = _guard().evaluate(
            _event(
                operation="file_write",
                operation_args={"file_path": ".claude/settings.json"},
                principal_kind="main",
                attest="pipeline_deterministic",
            )
        )
        assert verdict.allowed is True

    @pytest.mark.parametrize("principal", ["admin_service", "human_cli"])
    def test_non_installer_principal_write_settings_denied(
        self, principal: str
    ) -> None:
        verdict = _guard().evaluate(
            _event(
                operation="file_write",
                operation_args={"file_path": ".claude/settings.json"},
                principal_kind="main",
                attest=principal,
            )
        )
        assert verdict.allowed is False
        assert verdict.detail is not None
        assert verdict.detail["protection_zone"] == "harness"


class TestSelfProtectionGovernanceZone:
    """governance zone (lock-records / config / manifest / git): pipeline + admin + human.

    AG3-033 ERROR B: FK-15 §15.4.1 ("Lock-Record erstellen/beenden": Pipeline ✅,
    Mensch ✅ über Admin/CLI) + FK-30 §30.3.3 (official reset/split service).
    """

    @pytest.mark.parametrize(
        "principal",
        ["pipeline_deterministic", "admin_service", "human_cli"],
    )
    def test_official_principal_rm_freeze_allowed(self, principal: str) -> None:
        verdict = _guard().evaluate(
            _event(
                operation="bash_command",
                operation_args={"command": "rm .agentkit/governance/freeze.json"},
                principal_kind="main",
                attest=principal,
            )
        )
        assert verdict.allowed is True

    @pytest.mark.parametrize(
        "principal",
        ["pipeline_deterministic", "admin_service", "human_cli"],
    )
    def test_official_principal_write_project_yaml_allowed(
        self, principal: str
    ) -> None:
        verdict = _guard().evaluate(
            _event(
                operation="file_write",
                operation_args={"file_path": ".agentkit/config/project.yaml"},
                principal_kind="main",
                attest=principal,
            )
        )
        assert verdict.allowed is True

    def test_worker_governance_plane_still_denied(self) -> None:
        verdict = _guard().evaluate(
            _event(
                operation="bash_command",
                operation_args={"command": "rm .agentkit/governance/freeze.json"},
                attest="worker",
            )
        )
        assert verdict.allowed is False
        assert verdict.detail is not None
        assert verdict.detail["protection_zone"] == "governance"


class TestSelfProtectionAllow:
    """Non-protected paths and non-mutating ops are allowed."""

    def test_non_protected_path_allowed(self) -> None:
        verdict = _guard().evaluate(
            _event(
                operation="file_write",
                operation_args={"file_path": "src/agentkit/module.py"},
                attest="worker",
            )
        )
        assert verdict.allowed is True

    def test_read_protected_path_allowed(self) -> None:
        # Self-protection only blocks mutations; a read is not its concern.
        verdict = _guard().evaluate(
            _event(
                operation="file_read",
                operation_args={"file_path": ".claude/settings.json"},
                attest="worker",
            )
        )
        assert verdict.allowed is True

    def test_empty_target_allowed(self) -> None:
        # A target that normalises to no segments (e.g. ``.``) is not protected.
        verdict = _guard().evaluate(
            _event(
                operation="file_write",
                operation_args={"file_path": "."},
                attest="worker",
            )
        )
        assert verdict.allowed is True

    def test_plain_exec_on_protected_dir_allowed(self) -> None:
        # A non-mutating shell command (no file mutation) is not blocked.
        verdict = _guard().evaluate(
            _event(
                operation="bash_command",
                operation_args={"command": "cat .claude/settings.json"},
                attest="worker",
            )
        )
        assert verdict.allowed is True
