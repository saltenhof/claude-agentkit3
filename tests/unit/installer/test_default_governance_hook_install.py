"""Default-install governance hook wiring through the REAL installer path.

AG3-086 (FIX B): assert a DEFAULT install drives the production installer path
``CP9 -> _register_default_governance_hooks -> register_hooks(
build_default_hook_definitions())`` and that the four AG3-086 hooks actually LAND
in the produced ``.claude/settings.json`` CONTENT — not merely that the file
exists. The Governance-level ``register_hooks`` wiring is covered separately
(``tests/unit/governance/test_register_hooks.py``); THIS test exercises the
installer's own ``_register_default_governance_hooks`` orchestration so the full
default-install path is proven end-to-end over the REAL state backend (no mocks).

FK-31 §31.7 / FK-30 §30.5.1a / FK-43 §43.6.2: the four AG3-086 hooks are
- PreToolUse ``budget`` (WebCallBudgetGuard) on ``WebFetch|WebSearch``,
- PostToolUse ``budget`` (observational web_call emitter) on ``WebFetch|WebSearch``,
- PreToolUse ``skill_usage_check`` on ``Bash``,
- PreToolUse ``prompt_integrity`` on every ``Agent`` sub-agent spawn,
- PreToolUse/PostToolUse/PostToolUseFailure ``commit_hook`` on ``Bash`` for
  mechanical HEAD-delta commit telemetry.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.installer.runner import InstallConfig, _register_default_governance_hooks
from agentkit.backend.state_backend.persistence_test_support import reset_backend_cache_for_tests

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path


@pytest.fixture(autouse=True)
def _sqlite_backend(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    monkeypatch.delenv("AGENTKIT_STATE_DATABASE_URL", raising=False)
    reset_backend_cache_for_tests()
    yield
    reset_backend_cache_for_tests()


def _config(root: Path) -> InstallConfig:
    return InstallConfig(
        project_key="demo",
        project_name="Demo",
        project_root=root,
    )


def _claude_commands_for_event(
    settings: dict[str, object], event_key: str
) -> set[tuple[str | None, str]]:
    hooks = settings["hooks"]  # type: ignore[index]
    groups = hooks[event_key]  # type: ignore[index]
    return {
        (group.get("matcher"), handler["command"])
        for group in groups
        for handler in group["hooks"]
    }


def test_default_install_lands_ag3_086_hooks_in_settings(tmp_path: Path) -> None:
    """The real installer path materializes all four AG3-086 hooks into settings."""
    changed = _register_default_governance_hooks(_config(tmp_path), tmp_path)

    # The installer reports the touched settings files (content actually changed).
    assert ".claude/settings.json" in {path.replace("\\", "/") for path in changed}

    settings_path = tmp_path / ".claude" / "settings.json"
    assert settings_path.is_file()
    claude = json.loads(settings_path.read_text(encoding="utf-8"))

    pre = _claude_commands_for_event(claude, "PreToolUse")
    post = _claude_commands_for_event(claude, "PostToolUse")

    # FK-30 §30.5.1a: the single blocking web-call budget owner (PreToolUse).
    assert ("WebFetch|WebSearch", "agentkit-hook-claude pre budget") in pre
    # FK-30 §30.5.2: the observational web_call emitter (PostToolUse, never blocks).
    assert ("WebFetch|WebSearch", "agentkit-hook-claude post budget") in post
    # FK-43 §43.6.2: the ad-hoc methodology guard (PreToolUse on Bash).
    assert ("Bash", "agentkit-hook-claude pre skill_usage_check") in pre
    # AG3-147: mechanical commit invalidation observes HEAD across Bash commands.
    assert ("Bash", "agentkit-hook-claude pre commit_hook") in pre
    assert ("Bash", "agentkit-hook-claude post commit_hook") in post
    # FK-31 §31.7: the permanently-active prompt-integrity guard (PreToolUse Agent).
    assert ("Agent", "agentkit-hook-claude pre prompt_integrity") in pre


def test_default_install_is_idempotent_on_second_run(tmp_path: Path) -> None:
    """A second default-install run re-materializes the same four hooks (no drift)."""
    _register_default_governance_hooks(_config(tmp_path), tmp_path)
    # Second run with the post-first-run digests as the baseline: nothing changes.
    settings_path = tmp_path / ".claude" / "settings.json"
    first_content = json.loads(settings_path.read_text(encoding="utf-8"))

    _register_default_governance_hooks(_config(tmp_path), tmp_path)
    second_content = json.loads(settings_path.read_text(encoding="utf-8"))

    def _pre(content: dict[str, object]) -> set[tuple[str, str]]:
        return {
            (matcher or "", command)
            for matcher, command in _claude_commands_for_event(content, "PreToolUse")
        }

    # The four AG3-086 hooks remain present and stable across re-install.
    assert ("Agent", "agentkit-hook-claude pre prompt_integrity") in _pre(
        first_content
    )
    assert ("Bash", "agentkit-hook-claude pre commit_hook") in _pre(first_content)
    assert _pre(first_content) == _pre(second_content)
