"""Integration test: Governance.run_hook(phase='pre', hook_id='ccag_gatekeeper', ...).

Tests the dispatcher path from the Governance top surface through
_run_ccag_hook -> CcagPermissionRuntime.evaluate.

No mocking of core components — uses real SQLite in-memory paths via tmp_path.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import yaml

from agentkit.governance.guard_evaluation import HookEvent
from agentkit.governance.protocols import GuardVerdict
from agentkit.governance.runner import Governance, run_hook

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _make_event(
    tool_name: str = "Bash",
    command: str = "git push",
    operating_mode: str = "ai_augmented",
    is_subagent: bool = False,
) -> HookEvent:
    return HookEvent(
        operation="bash_command",
        operation_args={
            "tool_name": tool_name,
            "command": command,
            "operating_mode": operating_mode,
        },
        freshness_class="mutation",
        cwd=".",
        principal_kind="subagent" if is_subagent else "main",
    )


def _write_rules(rules_dir: Path, filename: str, rules: list[dict[str, object]]) -> None:
    rules_dir.mkdir(parents=True, exist_ok=True)
    (rules_dir / filename).write_text(
        yaml.dump({"rules": rules}, allow_unicode=True),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Dispatcher: valid hook selector dispatches to CCAG
# ---------------------------------------------------------------------------


class TestDispatcherRouting:
    def test_ccag_gatekeeper_returns_guard_verdict_allow(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Allow rule fires -> GuardVerdict.allow('ccag_gatekeeper')."""
        rules_dir = tmp_path / "rules"
        _write_rules(
            rules_dir,
            "global.yaml",
            [{"id": "allow-git", "tool": "Bash", "allow_pattern": r"^git\s"}],
        )

        # Patch CcagPermissionRuntime to use our rules_dir
        from agentkit.governance.ccag.runtime import CcagPermissionRuntime

        original_init = CcagPermissionRuntime.__init__

        def patched_init(self: CcagPermissionRuntime, **kwargs: Any) -> None:
            original_init(self, rules_dir=rules_dir, **kwargs)

        monkeypatch.setattr(CcagPermissionRuntime, "__init__", patched_init)

        event = _make_event(command="git push origin main")
        verdict = run_hook("ccag_gatekeeper", event, phase="pre")
        assert isinstance(verdict, GuardVerdict)
        assert verdict.allowed is True
        assert verdict.guard_name == "ccag_gatekeeper"

    def test_ccag_gatekeeper_returns_guard_verdict_block(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Block rule fires -> GuardVerdict.block('ccag_gatekeeper')."""
        rules_dir = tmp_path / "rules"
        _write_rules(
            rules_dir,
            "global.yaml",
            [{"id": "deny-rm", "tool": "Bash", "block_pattern": r"rm\s+-rf"}],
        )

        from agentkit.governance.ccag.runtime import CcagPermissionRuntime

        original_init = CcagPermissionRuntime.__init__

        def patched_init(self: CcagPermissionRuntime, **kwargs: Any) -> None:
            original_init(self, rules_dir=rules_dir, **kwargs)

        monkeypatch.setattr(CcagPermissionRuntime, "__init__", patched_init)

        event = _make_event(command="rm -rf /tmp")
        verdict = run_hook("ccag_gatekeeper", event, phase="pre")
        assert isinstance(verdict, GuardVerdict)
        assert verdict.allowed is False
        assert verdict.guard_name == "ccag_gatekeeper"

    def test_unknown_hook_id_is_rejected(self) -> None:
        """Unknown hook_id -> fail-closed GuardVerdict.block."""
        event = _make_event()
        verdict = run_hook("nonexistent_hook_xyz", event, phase="pre")
        assert verdict.allowed is False

    def test_post_phase_always_allows(self) -> None:
        """Post-hooks always allow (no post-CCAG implemented yet)."""
        event = _make_event()
        verdict = run_hook("telemetry", event, phase="post")
        assert verdict.allowed is True

    def test_governance_class_delegates_to_run_hook(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Governance.run_hook() calls the same dispatcher as run_hook()."""
        rules_dir = tmp_path / "rules"
        _write_rules(
            rules_dir,
            "global.yaml",
            [{"id": "allow-all", "tool": "Bash", "allow_pattern": ".*"}],
        )

        from agentkit.governance.ccag.runtime import CcagPermissionRuntime

        original_init = CcagPermissionRuntime.__init__

        def patched_init(self: CcagPermissionRuntime, **kwargs: Any) -> None:
            original_init(self, rules_dir=rules_dir, **kwargs)

        monkeypatch.setattr(CcagPermissionRuntime, "__init__", patched_init)

        event = _make_event(command="git status")
        verdict = Governance.run_hook("ccag_gatekeeper", event, phase="pre")
        assert verdict.allowed is True


# ---------------------------------------------------------------------------
# Unknown permission in story_execution -> CCAG creates request, verdict=allow
# (The harness adapter exits 2; the GuardVerdict level allows to let CCAG
#  handle the blocking semantics independently)
# ---------------------------------------------------------------------------


class TestUnknownPermissionDispatch:
    def test_unknown_in_story_execution_verdict_is_allow_at_guard_level(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """unknown_permission is translated to GuardVerdict.allow at the runner level.

        The CcagPermissionRuntime creates a PermissionRequest and returns
        unknown_permission. The runner maps this to allow so the harness
        adapter can inspect the CcagDecision separately and exit 2 via its
        own logic (standalone CLI / ccag_settings pattern).
        """
        rules_dir = tmp_path / "rules"
        rules_dir.mkdir()
        from agentkit.governance.ccag.requests import PermissionRequestStore
        from agentkit.governance.ccag.runtime import CcagPermissionRuntime

        request_store = PermissionRequestStore(tmp_path / "req.db")
        original_init = CcagPermissionRuntime.__init__

        def patched_init(self: CcagPermissionRuntime, **kwargs: Any) -> None:
            original_init(
                self,
                rules_dir=rules_dir,
                request_store=request_store,
                **kwargs,
            )

        monkeypatch.setattr(CcagPermissionRuntime, "__init__", patched_init)

        event = HookEvent(
            operation="bash_command",
            operation_args={
                "tool_name": "Bash",
                "command": "some-completely-unknown-tool",
                "operating_mode": "story_execution",
            },
            freshness_class="mutation",
            cwd=".",
            principal_kind="main",
        )
        verdict = run_hook("ccag_gatekeeper", event, phase="pre")
        # GuardVerdict is allow (CCAG handles block semantics at CLI level)
        assert verdict.allowed is True
        assert verdict.guard_name == "ccag_gatekeeper"

        # But the PermissionRequest was created in the state-backend
        pending = request_store.list_pending()
        assert len(pending) == 1
        assert pending[0].tool_name == "Bash"
