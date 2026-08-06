"""Dispatcher proofs for the retained matcher-only CCAG hook."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.governance.guard_evaluation import HookEvent
from agentkit.backend.governance.protocols import GuardVerdict
from agentkit.backend.governance.runner import Governance, _run_ccag_hook, run_hook

if TYPE_CHECKING:
    from pathlib import Path


def _event(command: str = "curl https://example.test") -> HookEvent:
    return HookEvent(
        operation="bash_command",
        operation_args={"tool_name": "Bash", "command": command},
        freshness_class="mutation",
        cwd=".",
        principal_kind="main",
    )


def test_rule_that_previously_blocked_no_longer_has_authority(tmp_path: Path) -> None:
    rules_dir = tmp_path / ".agentkit" / "ccag" / "rules"
    rules_dir.mkdir(parents=True)
    (rules_dir / "global.yaml").write_text(
        "rules:\n  - id: deny-curl\n    tool: Bash\n    block_pattern: 'curl.*'\n",
        encoding="utf-8",
    )

    verdict = _run_ccag_hook(_event(), project_root=tmp_path)

    assert verdict == GuardVerdict.allow("ccag_gatekeeper")
    assert (rules_dir / "global.yaml").is_file()


def test_ccag_hook_does_not_materialize_state(tmp_path: Path) -> None:
    verdict = _run_ccag_hook(_event(), project_root=tmp_path)

    assert verdict.allowed is True
    assert list(tmp_path.iterdir()) == []


def test_registered_dispatcher_returns_named_allow(tmp_path: Path) -> None:
    verdict = run_hook(
        "ccag_gatekeeper",
        _event(command="git status"),
        phase="pre",
        project_root=tmp_path,
    )

    assert isinstance(verdict, GuardVerdict)
    assert verdict.allowed is True
    assert verdict.guard_name == "ccag_gatekeeper"


def test_governance_surface_uses_same_matcher_only_dispatch(tmp_path: Path) -> None:
    verdict = Governance.run_hook(
        "ccag_gatekeeper",
        _event(command="git status"),
        phase="pre",
        project_root=tmp_path,
    )

    assert verdict == GuardVerdict.allow("ccag_gatekeeper")


def test_unknown_hook_id_remains_fail_closed(tmp_path: Path) -> None:
    verdict = run_hook(
        "nonexistent_hook_xyz",
        _event(),
        phase="pre",
        project_root=tmp_path,
    )

    assert verdict.allowed is False
