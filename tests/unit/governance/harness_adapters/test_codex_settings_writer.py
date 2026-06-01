"""Unit tests for the productive CodexSettingsWriter (AG3-049).

Covers FK-76 §76.5.2 (three-level ``.codex/hooks.json`` shape), the
token-wise matcher mapping (§2.1.2), command parse/validate (§2.1.1),
merge/idempotency with identity (event, matcher, command) (§2.1.4), and
fail-closed handling of a broken existing file.

Verified 2026-06-01 against ``developers.openai.com/codex/hooks``:
- File ``.codex/hooks.json``; shape ``hooks`` -> event -> matcher-group
  ``{matcher, hooks:[{type:"command", command}]}``.
- Matcher is a regex; ``Bash``, ``apply_patch`` (covers Edit/Write) and MCP
  tool names (e.g. ``mcp__filesystem__.*``) are matchable.  Read/Grep/Glob/
  WebSearch/WebFetch and Agent-spawn are not interceptable.
- ``*_send`` (FK-30 §30.3.2: MCP pool-send tools) therefore maps to the MCP
  matcher regex ``^mcp__.*_send$`` (anchored) — pinned by ``test_send_token_maps_to_mcp_regex``.

No mocks/stubs: real writer, real filesystem (tmp_path), real JSON parse-back.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from agentkit.governance.errors import HookRegistrationError
from agentkit.governance.harness_adapters.settings_writer import (
    CodexSettingsWriter,
    map_claude_matcher,
    remap_command,
)
from agentkit.governance.hook_registration import HookDefinition, HookEventName

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pre(matcher: str, hook_id: str) -> HookDefinition:
    return HookDefinition(
        hook_event_name=HookEventName.PRE_TOOL_USE,
        matcher=matcher,
        command=f"agentkit-hook-claude pre {hook_id}",
    )


def _post(matcher: str, hook_id: str) -> HookDefinition:
    return HookDefinition(
        hook_event_name=HookEventName.POST_TOOL_USE,
        matcher=matcher,
        command=f"agentkit-hook-claude post {hook_id}",
    )


def _read_hooks(tmp_path: Path) -> dict[str, object]:
    path = tmp_path / ".codex" / "hooks.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _groups(data: dict[str, object], event: str) -> list[dict[str, object]]:
    hooks = data["hooks"]
    assert isinstance(hooks, dict)
    groups = hooks[event]
    assert isinstance(groups, list)
    return groups


def _commands_for_matcher(
    data: dict[str, object], event: str, matcher: str
) -> list[str]:
    commands: list[str] = []
    for group in _groups(data, event):
        if group.get("matcher") != matcher:
            continue
        handlers = group.get("hooks")
        assert isinstance(handlers, list)
        for handler in handlers:
            assert isinstance(handler, dict)
            commands.append(str(handler.get("command")))
    return commands


# ---------------------------------------------------------------------------
# Command parse/validate (§2.1.1, Auflage 5, AC1)
# ---------------------------------------------------------------------------


class TestCommandRemap:
    def test_valid_command_remapped(self) -> None:
        assert (
            remap_command("agentkit-hook-claude pre branch_guard")
            == "agentkit-hook-codex pre branch_guard"
        )

    def test_valid_post_command_remapped(self) -> None:
        assert (
            remap_command("agentkit-hook-claude post telemetry")
            == "agentkit-hook-codex post telemetry"
        )

    @pytest.mark.parametrize(
        "command",
        [
            "agentkit-hook-codex pre branch_guard",  # already codex
            "agentkit-hook-claude pre",  # missing hook_id
            "agentkit-hook-claude pre branch_guard extra",  # extra arg
            "python -m agentkit.hooks pre branch_guard",  # foreign form
            "",  # empty
        ],
    )
    def test_invalid_command_raises(self, command: str) -> None:
        with pytest.raises(HookRegistrationError):
            remap_command(command)

    def test_write_emits_codex_command(self, tmp_path: Path) -> None:
        CodexSettingsWriter(tmp_path).write([_pre("Bash", "branch_guard")])
        data = _read_hooks(tmp_path)
        assert _commands_for_matcher(data, "PreToolUse", "Bash") == [
            "agentkit-hook-codex pre branch_guard"
        ]

    def test_write_with_invalid_command_raises(self, tmp_path: Path) -> None:
        bad = HookDefinition(
            hook_event_name=HookEventName.PRE_TOOL_USE,
            matcher="Bash",
            command="agentkit-hook-codex pre branch_guard",  # not claude-form
        )
        with pytest.raises(HookRegistrationError):
            CodexSettingsWriter(tmp_path).write([bad])

    @pytest.mark.parametrize(
        "command",
        [
            "agentkit-hook-claude later branch_guard",  # regex-valid, bad phase
            "agentkit-hook-claude pre frobnicate_guard",  # regex-valid, bad hook_id
            "agentkit-hook-claude pre telemetry",  # telemetry is a POST hook, not PRE
        ],
    )
    def test_regex_valid_but_invalid_selector_raises(self, command: str) -> None:
        """Codex-r1 ERROR 3: shape alone is not enough — an unknown phase/hook_id
        (or phase/hook_id mismatch) is fail-closed at the registration boundary,
        not silently emitted as a command the wrapper later rejects.
        """
        with pytest.raises(HookRegistrationError):
            remap_command(command)


# ---------------------------------------------------------------------------
# Matcher-mapping matrix (§2.1.2, Auflage 2+3, AC2)
# ---------------------------------------------------------------------------


class TestMatcherMapping:
    def test_bash_maps_to_bash(self) -> None:
        result = map_claude_matcher("Bash")
        assert result.codex_matcher == "Bash"
        assert result.dropped_tokens == []

    def test_write_and_edit_dedupe_to_single_apply_patch(self) -> None:
        result = map_claude_matcher("Write|Edit")
        assert result.codex_matcher == "apply_patch"
        assert result.dropped_tokens == []

    def test_read_token_drops_with_diagnostic(self) -> None:
        result = map_claude_matcher("Read")
        assert result.codex_matcher is None
        assert result.dropped_tokens == ["Read"]

    @pytest.mark.parametrize("token", ["Grep", "Glob", "Agent"])
    def test_other_known_unrepresentable_tokens_drop(self, token: str) -> None:
        result = map_claude_matcher(token)
        assert result.codex_matcher is None
        assert result.dropped_tokens == [token]

    @pytest.mark.parametrize("token", ["WebSearch", "WebFetch"])
    def test_web_token_drops(self, token: str) -> None:
        result = map_claude_matcher(token)
        assert result.codex_matcher is None
        assert result.dropped_tokens == [token]

    def test_send_token_maps_to_mcp_regex(self) -> None:
        """``*_send`` (MCP pool-send tools, FK-30 §30.3.2) -> ``^mcp__.*_send$``.

        Pinned decision: the live Codex doc confirms MCP tools are matchable
        via regex; the pool-send tools are exposed as MCP tools, so the
        matcher maps rather than dropping.
        """
        result = map_claude_matcher("*_send")
        assert result.codex_matcher == "^mcp__.*_send$"
        assert result.dropped_tokens == []

    def test_partial_drop_keeps_representable_tokens(self) -> None:
        """``Bash|Write|Edit|Read|Grep|Glob|Agent`` -> ``Bash|apply_patch``."""
        result = map_claude_matcher("Bash|Write|Edit|Read|Grep|Glob|Agent")
        assert result.codex_matcher == "Bash|apply_patch"
        assert result.dropped_tokens == ["Read", "Grep", "Glob", "Agent"]

    def test_mixed_send_and_bash(self) -> None:
        result = map_claude_matcher("Agent|Bash|*_send")
        assert result.codex_matcher == "Bash|^mcp__.*_send$"
        assert result.dropped_tokens == ["Agent"]

    def test_unknown_token_raises(self) -> None:
        with pytest.raises(HookRegistrationError, match="Frobnicate"):
            map_claude_matcher("Frobnicate")

    def test_unknown_token_among_known_raises(self) -> None:
        with pytest.raises(HookRegistrationError):
            map_claude_matcher("Bash|Frobnicate")


# ---------------------------------------------------------------------------
# Empty-after-drop -> documented non-applicability (§2.1.2, AC3)
# ---------------------------------------------------------------------------


class TestEmptyMatcherNonApplicability:
    def test_empty_matcher_writes_no_hook(self, tmp_path: Path) -> None:
        writer = CodexSettingsWriter(tmp_path)
        writer.write([_post("WebSearch|WebFetch", "budget")])
        data = _read_hooks(tmp_path)
        hooks = data["hooks"]
        assert isinstance(hooks, dict)
        # No matcher group survives — no event key (or an empty list) is written.
        assert hooks.get("PostToolUse", []) == []

    def test_empty_matcher_records_diagnostic(self, tmp_path: Path) -> None:
        writer = CodexSettingsWriter(tmp_path)
        writer.write([_post("WebSearch|WebFetch", "budget")])
        assert any("not applicable to" in d for d in writer.diagnostics)

    def test_partial_drop_records_diagnostic(self, tmp_path: Path) -> None:
        writer = CodexSettingsWriter(tmp_path)
        writer.write([_pre("Bash|Read", "orchestrator_guard")])
        assert any("dropped" in d and "Read" in d for d in writer.diagnostics)


# ---------------------------------------------------------------------------
# Three-level shape parse-back (§2.1.3, AC4)
# ---------------------------------------------------------------------------


class TestThreeLevelShape:
    def test_shape_is_three_level(self, tmp_path: Path) -> None:
        CodexSettingsWriter(tmp_path).write([_pre("Bash", "branch_guard")])
        data = _read_hooks(tmp_path)
        assert set(data.keys()) == {"hooks"}
        group = _groups(data, "PreToolUse")[0]
        assert group["matcher"] == "Bash"
        handlers = group["hooks"]
        assert isinstance(handlers, list)
        assert handlers == [
            {"type": "command", "command": "agentkit-hook-codex pre branch_guard"}
        ]

    def test_handler_has_command_type(self, tmp_path: Path) -> None:
        CodexSettingsWriter(tmp_path).write([_pre("Write|Edit", "qa_agent_guard")])
        data = _read_hooks(tmp_path)
        group = _groups(data, "PreToolUse")[0]
        assert group["matcher"] == "apply_patch"
        handlers = group["hooks"]
        assert isinstance(handlers, list)
        for handler in handlers:
            assert isinstance(handler, dict)
            assert handler["type"] == "command"
            assert "command" in handler

    def test_settings_path_is_codex_hooks_json(self, tmp_path: Path) -> None:
        writer = CodexSettingsWriter(tmp_path)
        assert writer.settings_path == tmp_path / ".codex" / "hooks.json"


# ---------------------------------------------------------------------------
# Merge / idempotency, identity (event, matcher, command) (§2.1.4, Auflage 4, AC5)
# ---------------------------------------------------------------------------


class TestMergeIdempotency:
    def test_two_handlers_same_matcher_both_preserved(self, tmp_path: Path) -> None:
        """Two distinct guards under ``Bash`` -> two handlers in one group."""
        writer = CodexSettingsWriter(tmp_path)
        writer.write(
            [
                _pre("Bash", "branch_guard"),
                _pre("Bash", "story_creation_guard"),
            ]
        )
        data = _read_hooks(tmp_path)
        groups = [g for g in _groups(data, "PreToolUse") if g.get("matcher") == "Bash"]
        assert len(groups) == 1, "shared matcher must collapse into one group"
        commands = _commands_for_matcher(data, "PreToolUse", "Bash")
        assert sorted(commands) == [
            "agentkit-hook-codex pre branch_guard",
            "agentkit-hook-codex pre story_creation_guard",
        ]

    def test_idempotent_rewrite(self, tmp_path: Path) -> None:
        defs = [_pre("Bash", "branch_guard"), _pre("Bash", "story_creation_guard")]
        CodexSettingsWriter(tmp_path).write(defs)
        CodexSettingsWriter(tmp_path).write(defs)  # second pass, fresh writer
        data = _read_hooks(tmp_path)
        commands = _commands_for_matcher(data, "PreToolUse", "Bash")
        assert sorted(commands) == [
            "agentkit-hook-codex pre branch_guard",
            "agentkit-hook-codex pre story_creation_guard",
        ], "re-registering an identical handler must be idempotent"

    def test_distinct_command_same_matcher_separate_entry(self, tmp_path: Path) -> None:
        CodexSettingsWriter(tmp_path).write([_pre("Bash", "branch_guard")])
        CodexSettingsWriter(tmp_path).write([_pre("Bash", "story_creation_guard")])
        data = _read_hooks(tmp_path)
        commands = _commands_for_matcher(data, "PreToolUse", "Bash")
        assert sorted(commands) == [
            "agentkit-hook-codex pre branch_guard",
            "agentkit-hook-codex pre story_creation_guard",
        ]

    def test_foreign_hook_preserved(self, tmp_path: Path) -> None:
        path = tmp_path / ".codex" / "hooks.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "hooks": {
                        "PreToolUse": [
                            {
                                "matcher": "Bash",
                                "hooks": [
                                    {"type": "command", "command": "third-party-tool run"}
                                ],
                            }
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )
        CodexSettingsWriter(tmp_path).write([_pre("Bash", "branch_guard")])
        data = _read_hooks(tmp_path)
        commands = _commands_for_matcher(data, "PreToolUse", "Bash")
        assert "third-party-tool run" in commands
        assert "agentkit-hook-codex pre branch_guard" in commands

    def test_foreign_event_preserved(self, tmp_path: Path) -> None:
        path = tmp_path / ".codex" / "hooks.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "hooks": {
                        "SessionStart": [
                            {
                                "matcher": "*",
                                "hooks": [{"type": "command", "command": "boot.sh"}],
                            }
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )
        CodexSettingsWriter(tmp_path).write([_pre("Bash", "branch_guard")])
        data = _read_hooks(tmp_path)
        assert _commands_for_matcher(data, "SessionStart", "*") == ["boot.sh"]
        assert _commands_for_matcher(data, "PreToolUse", "Bash") == [
            "agentkit-hook-codex pre branch_guard"
        ]

    def test_foreign_group_without_matcher_preserved_verbatim(
        self, tmp_path: Path
    ) -> None:
        """Codex-r1 ERROR 1: a foreign group with NO ``matcher`` (e.g. ``Stop``/
        ``UserPromptSubmit``) must stay verbatim — no ``"matcher": null`` synthesis.
        """
        path = tmp_path / ".codex" / "hooks.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "hooks": {
                        "Stop": [
                            {"hooks": [{"type": "command", "command": "cleanup.sh"}]}
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )
        CodexSettingsWriter(tmp_path).write([_pre("Bash", "branch_guard")])
        data = _read_hooks(tmp_path)
        stop_group = data["hooks"]["Stop"][0]
        assert "matcher" not in stop_group  # NOT rewritten to {"matcher": null}
        assert stop_group["hooks"] == [{"type": "command", "command": "cleanup.sh"}]


# ---------------------------------------------------------------------------
# Fail-closed on broken existing file (§2.1.4, AC5)
# ---------------------------------------------------------------------------


class TestFailClosed:
    def test_broken_json_raises(self, tmp_path: Path) -> None:
        path = tmp_path / ".codex" / "hooks.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{ not json {{", encoding="utf-8")
        with pytest.raises(ValueError, match="Invalid JSON|broken"):
            CodexSettingsWriter(tmp_path).write([_pre("Bash", "branch_guard")])

    def test_non_object_top_level_raises(self, tmp_path: Path) -> None:
        path = tmp_path / ".codex" / "hooks.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("[1, 2, 3]", encoding="utf-8")
        with pytest.raises(ValueError):
            CodexSettingsWriter(tmp_path).write([_pre("Bash", "branch_guard")])

    @pytest.mark.parametrize(
        "payload",
        [
            '{"hooks": []}',  # hooks present but not an object
            '{"hooks": {"PreToolUse": {}}}',  # event value not a list
            '{"hooks": {"PreToolUse": [123]}}',  # group not an object
            '{"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": "x"}]}}',  # nested hooks not a list
            '{"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [1]}]}}',  # handler not an object
            '{"hooks": {"Stop": [{}]}}',  # group missing required 'hooks' list (Codex-r2)
            '{"hooks": {"PreToolUse": [{"matcher": "Bash"}]}}',  # matching group missing 'hooks' (would KeyError, Codex-r2)
        ],
    )
    def test_malformed_hooks_shape_raises(
        self, tmp_path: Path, payload: str
    ) -> None:
        """Codex-r1 ERROR 2: a present-but-malformed ``hooks`` structure is
        fail-closed (ValueError), not silently coerced to empty/partial — silent
        coercion would delete existing governance/foreign hooks on the next write.
        """
        path = tmp_path / ".codex" / "hooks.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")
        with pytest.raises(ValueError):
            CodexSettingsWriter(tmp_path).write([_pre("Bash", "branch_guard")])


# ---------------------------------------------------------------------------
# Contract: register_hooks materialises Codex settings (§2.1.5, AC4)
# ---------------------------------------------------------------------------


class TestRegisterHooksWritesCodex:
    @staticmethod
    def _make_governance(tmp_path: Path) -> object:
        from agentkit.governance.hook_registration import RegistrationResult
        from agentkit.governance.runner import Governance

        class _RecordingHookRepo:
            def register(
                self, project_key: str, hook_definitions: list[HookDefinition]
            ) -> RegistrationResult:
                return RegistrationResult(
                    registered=[d.matcher for d in hook_definitions],
                    skipped=[],
                    errors=[],
                )

            def list_for_project(self, project_key: str) -> list[HookDefinition]:
                return []

            def clear_for_project(self, project_key: str) -> None:
                return None

        class _RecordingLockRepo:
            def deactivate_locks_for_story(self, story_id: str) -> list:
                return []

        class _StubWorktreeRepo:
            def list_worktree_paths(self, story_id: str) -> list:
                return []

        return Governance(
            hook_repo=_RecordingHookRepo(),  # type: ignore[arg-type]
            lock_repo=_RecordingLockRepo(),  # type: ignore[arg-type]
            project_key="test-project",
            project_root=tmp_path,
            worktree_repo=_StubWorktreeRepo(),  # type: ignore[arg-type]
        )

    def test_register_hooks_writes_codex_shape_and_commands(
        self, tmp_path: Path
    ) -> None:
        gov = self._make_governance(tmp_path)
        gov.register_hooks(  # type: ignore[union-attr]
            [
                _pre("Bash", "branch_guard"),
                _post("Agent|Bash|*_send", "telemetry"),
            ]
        )
        data = _read_hooks(tmp_path)
        # PreToolUse Bash -> Bash, codex command.
        assert _commands_for_matcher(data, "PreToolUse", "Bash") == [
            "agentkit-hook-codex pre branch_guard"
        ]
        # PostToolUse Agent|Bash|*_send -> Bash|^mcp__.*_send$ (Agent dropped).
        assert _commands_for_matcher(
            data, "PostToolUse", "Bash|^mcp__.*_send$"
        ) == ["agentkit-hook-codex post telemetry"]

    def test_register_hooks_also_writes_claude(self, tmp_path: Path) -> None:
        gov = self._make_governance(tmp_path)
        gov.register_hooks([_pre("Bash", "branch_guard")])  # type: ignore[union-attr]
        assert (tmp_path / ".claude" / "settings.json").exists()
        assert (tmp_path / ".codex" / "hooks.json").exists()
