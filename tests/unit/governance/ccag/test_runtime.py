"""Tests for agentkit.governance.ccag.runtime — CcagPermissionRuntime."""

from __future__ import annotations

from typing import TYPE_CHECKING

import yaml

from agentkit.governance.ccag.requests import PermissionRequestStore
from agentkit.governance.ccag.runtime import (
    _AI_AUGMENTED,
    _INTERACTIVE_AGENT,
    _STORY_EXECUTION,
    CcagDecisionKind,
    CcagPermissionRuntime,
    _extract_operating_mode,
)
from agentkit.governance.guard_evaluation import HookEvent

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.projectedge.runtime import FreshnessClass

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(
    operation: str = "bash_command",
    tool_name: str = "Bash",
    command: str = "git push",
    is_subagent: bool = False,
    operating_mode: str = "",
    session_id: str | None = None,
    freshness: FreshnessClass = "mutation",
) -> HookEvent:
    args: dict[str, object] = {
        "tool_name": tool_name,
        "command": command,
    }
    if operating_mode:
        args["operating_mode"] = operating_mode
    return HookEvent(
        operation=operation,
        operation_args=args,
        freshness_class=freshness,
        cwd=".",
        session_id=session_id,
        principal_kind="subagent" if is_subagent else "main",
    )


def _write_rules(rules_dir: Path, filename: str, rules: list[dict]) -> None:
    rules_dir.mkdir(parents=True, exist_ok=True)
    (rules_dir / filename).write_text(
        yaml.dump({"rules": rules}, allow_unicode=True),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# _extract_operating_mode
# ---------------------------------------------------------------------------


class TestExtractOperatingMode:
    def test_story_execution_extracted(self) -> None:
        event = _make_event(operating_mode="story_execution")
        assert _extract_operating_mode(event) == _STORY_EXECUTION

    def test_ai_augmented_extracted(self) -> None:
        event = _make_event(operating_mode="ai_augmented")
        assert _extract_operating_mode(event) == _AI_AUGMENTED

    def test_interactive_agent_extracted(self) -> None:
        event = _make_event(operating_mode="interactive_agent")
        assert _extract_operating_mode(event) == _INTERACTIVE_AGENT

    def test_unknown_mode_defaults_to_ai_augmented(self) -> None:
        event = _make_event(operating_mode="")
        assert _extract_operating_mode(event) == _AI_AUGMENTED

    def test_invalid_mode_defaults_to_ai_augmented(self) -> None:
        event = _make_event(operating_mode="completely_unknown_mode")
        assert _extract_operating_mode(event) == _AI_AUGMENTED


# ---------------------------------------------------------------------------
# Static-Allow-Rule-Match -> allow
# ---------------------------------------------------------------------------


class TestStaticAllowRule:
    def test_allow_decision_for_matching_rule(self, tmp_path: Path) -> None:
        rules_dir = tmp_path / "rules"
        _write_rules(
            rules_dir,
            "global.yaml",
            [{"id": "allow-git", "tool": "Bash", "allow_pattern": r"^git\s"}],
        )
        runtime = CcagPermissionRuntime(rules_dir=rules_dir)
        event = _make_event(command="git push origin main")
        decision = runtime.evaluate(event)
        assert decision.kind == CcagDecisionKind.ALLOW
        assert decision.matched_rule_id == "allow-git"

    def test_allow_decision_for_read_tool(self, tmp_path: Path) -> None:
        rules_dir = tmp_path / "rules"
        _write_rules(
            rules_dir,
            "global.yaml",
            [{"id": "allow-read", "tool": "Read|Glob|Grep", "allow_pattern": ".*"}],
        )
        runtime = CcagPermissionRuntime(rules_dir=rules_dir)
        event = HookEvent(
            operation="file_read",
            operation_args={"tool_name": "Read", "file_path": "/project/foo.py"},
            freshness_class="baseline_read",
            cwd=".",
            principal_kind="main",
        )
        decision = runtime.evaluate(event)
        assert decision.kind == CcagDecisionKind.ALLOW


# ---------------------------------------------------------------------------
# Block-Rule-Match -> block_by_rule
# ---------------------------------------------------------------------------


class TestBlockRule:
    def test_block_decision_for_matching_rule(self, tmp_path: Path) -> None:
        rules_dir = tmp_path / "rules"
        _write_rules(
            rules_dir,
            "global.yaml",
            [{"id": "deny-rm", "tool": "Bash", "block_pattern": r"rm\s+-rf"}],
        )
        runtime = CcagPermissionRuntime(rules_dir=rules_dir)
        event = _make_event(command="rm -rf /tmp")
        decision = runtime.evaluate(event)
        assert decision.kind == CcagDecisionKind.BLOCK_BY_RULE
        assert decision.matched_rule_id == "deny-rm"

    def test_block_takes_priority_over_allow(self, tmp_path: Path) -> None:
        rules_dir = tmp_path / "rules"
        _write_rules(
            rules_dir,
            "global.yaml",
            [
                {"id": "allow-bash", "tool": "Bash", "allow_pattern": ".*", "priority": 200},
                {"id": "deny-rm", "tool": "Bash", "block_pattern": r"rm\s+-rf", "priority": 10},
            ],
        )
        runtime = CcagPermissionRuntime(rules_dir=rules_dir)
        event = _make_event(command="rm -rf /tmp")
        decision = runtime.evaluate(event)
        assert decision.kind == CcagDecisionKind.BLOCK_BY_RULE
        assert decision.matched_rule_id == "deny-rm"


# ---------------------------------------------------------------------------
# Unknown in story_execution -> unknown_permission + PermissionRequest
# ---------------------------------------------------------------------------


class TestUnknownPermissionStoryExecution:
    def test_unknown_creates_permission_request(self, tmp_path: Path) -> None:
        rules_dir = tmp_path / "rules"
        rules_dir.mkdir()
        db_path = tmp_path / "requests.db"
        request_store = PermissionRequestStore(db_path)
        runtime = CcagPermissionRuntime(
            rules_dir=rules_dir,
            request_store=request_store,
        )
        event = _make_event(
            command="some-unknown-command",
            operating_mode="story_execution",
        )
        decision = runtime.evaluate(event)
        assert decision.kind == CcagDecisionKind.UNKNOWN_PERMISSION
        assert decision.permission_request is not None
        req_id = decision.permission_request.request_id

        # Request appears in state backend
        loaded = request_store.load(req_id)
        assert loaded is not None
        assert loaded.status == "pending"
        assert loaded.tool_name == "Bash"

    def test_unknown_no_request_in_ai_augmented(self, tmp_path: Path) -> None:
        rules_dir = tmp_path / "rules"
        rules_dir.mkdir()
        request_store = PermissionRequestStore(tmp_path / "requests.db")
        runtime = CcagPermissionRuntime(
            rules_dir=rules_dir,
            request_store=request_store,
        )
        event = _make_event(
            command="some-unknown-command",
            operating_mode="ai_augmented",
        )
        decision = runtime.evaluate(event)
        assert decision.kind == CcagDecisionKind.UNKNOWN_PERMISSION
        assert decision.permission_request is None

    def test_unknown_no_request_in_interactive_agent(self, tmp_path: Path) -> None:
        rules_dir = tmp_path / "rules"
        rules_dir.mkdir()
        runtime = CcagPermissionRuntime(rules_dir=rules_dir)
        event = _make_event(
            command="some-unknown-command",
            operating_mode="interactive_agent",
        )
        decision = runtime.evaluate(event)
        assert decision.kind == CcagDecisionKind.UNKNOWN_PERMISSION
        assert decision.permission_request is None

    def test_fail_closed_in_story_execution(self, tmp_path: Path) -> None:
        """Verify FAIL CLOSED: unknown in story_execution is not allowed."""
        rules_dir = tmp_path / "rules"
        rules_dir.mkdir()
        runtime = CcagPermissionRuntime(rules_dir=rules_dir)
        event = _make_event(
            command="dangerous-unknown-op",
            operating_mode="story_execution",
        )
        decision = runtime.evaluate(event)
        # Must NOT be allow — must be unknown_permission
        assert decision.kind != CcagDecisionKind.ALLOW
        assert decision.kind == CcagDecisionKind.UNKNOWN_PERMISSION


# ---------------------------------------------------------------------------
# Mode-path tests: story_execution vs ai_augmented
# ---------------------------------------------------------------------------


class TestModePaths:
    def test_story_execution_mode(self, tmp_path: Path) -> None:
        rules_dir = tmp_path / "rules"
        rules_dir.mkdir()
        runtime = CcagPermissionRuntime(
            rules_dir=rules_dir,
            request_store=PermissionRequestStore(tmp_path / "db.db"),
        )
        event = _make_event(
            command="unknown-cmd",
            operating_mode="story_execution",
        )
        decision = runtime.evaluate(event)
        assert decision.kind == CcagDecisionKind.UNKNOWN_PERMISSION
        assert decision.permission_request is not None  # request created

    def test_ai_augmented_mode(self, tmp_path: Path) -> None:
        rules_dir = tmp_path / "rules"
        rules_dir.mkdir()
        runtime = CcagPermissionRuntime(rules_dir=rules_dir)
        event = _make_event(
            command="unknown-cmd",
            operating_mode="ai_augmented",
        )
        decision = runtime.evaluate(event)
        assert decision.kind == CcagDecisionKind.UNKNOWN_PERMISSION
        assert decision.permission_request is None  # no request

    def test_subagent_vs_main_agent_scope(self, tmp_path: Path) -> None:
        rules_dir = tmp_path / "rules"
        _write_rules(
            rules_dir,
            "subagents.yaml",
            [{"id": "deny-sub-write", "tool": "Write", "block_pattern": ".*", "applies_to": "sub"}],
        )
        _write_rules(
            rules_dir,
            "global.yaml",
            [{"id": "allow-write", "tool": "Write", "allow_pattern": ".*"}],
        )
        runtime = CcagPermissionRuntime(rules_dir=rules_dir)

        # Sub-agent: block rule fires
        sub_event = HookEvent(
            operation="file_write",
            operation_args={"tool_name": "Write", "file_path": "/project/foo.py"},
            freshness_class="mutation",
            cwd=".",
            principal_kind="subagent",
        )
        sub_decision = runtime.evaluate(sub_event)
        assert sub_decision.kind == CcagDecisionKind.BLOCK_BY_RULE

        # Main agent: block rule is scoped to sub, so allow rule fires
        main_event = HookEvent(
            operation="file_write",
            operation_args={"tool_name": "Write", "file_path": "/project/foo.py"},
            freshness_class="mutation",
            cwd=".",
            principal_kind="main",
        )
        main_decision = runtime.evaluate(main_event)
        assert main_decision.kind == CcagDecisionKind.ALLOW


# ---------------------------------------------------------------------------
# Fail-open on unexpected error
# ---------------------------------------------------------------------------


class TestFailOpen:
    def test_fail_open_on_corrupt_rules(self, tmp_path: Path) -> None:
        rules_dir = tmp_path / "rules"
        rules_dir.mkdir()
        # Write invalid YAML to global.yaml
        (rules_dir / "global.yaml").write_text("[broken: {yaml", encoding="utf-8")
        runtime = CcagPermissionRuntime(rules_dir=rules_dir)
        event = _make_event(command="any-command")
        # Corrupt YAML → empty rule set → unknown_permission (not a crash)
        decision = runtime.evaluate(event)
        # Should not raise; will be either allow or unknown_permission
        assert decision.kind in (
            CcagDecisionKind.ALLOW,
            CcagDecisionKind.UNKNOWN_PERMISSION,
        )


# ---------------------------------------------------------------------------
# Empty rules dir
# ---------------------------------------------------------------------------


class TestEmptyRulesDir:
    def test_empty_rules_dir_returns_unknown(self, tmp_path: Path) -> None:
        rules_dir = tmp_path / "rules"
        rules_dir.mkdir()
        runtime = CcagPermissionRuntime(rules_dir=rules_dir)
        event = _make_event(command="ls -la")
        decision = runtime.evaluate(event)
        assert decision.kind == CcagDecisionKind.UNKNOWN_PERMISSION
