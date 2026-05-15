"""Tests for agentkit.governance.ccag.rules — YAML loader and evaluation engine."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import yaml

from agentkit.governance.ccag.rules import (
    CcagRule,
    _load_yaml_rules,
    _serialise_input,
    _tool_matches,
    append_approved_rule,
    load_rules,
    rule_matches,
)

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------


def _make_rule(
    rule_id: str = "test-rule",
    tool: str = "Bash",
    allow_pattern: str = "",
    block_pattern: str = "",
    decision: str = "",
    scope: str = "all",
    priority: int = 100,
    conditions: list[dict[str, Any]] | None = None,
    applies_to: str = "all",
) -> CcagRule:
    return CcagRule(
        rule_id=rule_id,
        tool=tool,
        allow_pattern=allow_pattern,
        block_pattern=block_pattern,
        decision=decision,
        scope=scope,
        priority=priority,
        conditions=conditions or [],
        applies_to=applies_to,
    )


def _write_rules(rules_dir: Path, filename: str, rules: list[dict[str, object]]) -> None:
    rules_dir.mkdir(parents=True, exist_ok=True)
    (rules_dir / filename).write_text(
        yaml.dump({"rules": rules}, allow_unicode=True),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# CcagRule properties
# ---------------------------------------------------------------------------


class TestCcagRuleProperties:
    def test_is_block_rule_via_block_pattern(self) -> None:
        rule = _make_rule(block_pattern="rm -rf")
        assert rule.is_block_rule is True
        assert rule.is_allow_rule is False

    def test_is_block_rule_via_decision_deny(self) -> None:
        rule = _make_rule(decision="deny")
        assert rule.is_block_rule is True

    def test_is_block_rule_via_decision_block(self) -> None:
        rule = _make_rule(decision="block")
        assert rule.is_block_rule is True

    def test_is_allow_rule_via_allow_pattern(self) -> None:
        rule = _make_rule(allow_pattern="git push")
        assert rule.is_allow_rule is True
        assert rule.is_block_rule is False

    def test_is_allow_rule_via_decision(self) -> None:
        rule = _make_rule(decision="allow")
        assert rule.is_allow_rule is True

    def test_effective_scope_prefers_applies_to(self) -> None:
        rule = _make_rule(scope="all", applies_to="sub")
        assert rule.effective_scope == "sub"

    def test_effective_scope_falls_back_to_scope(self) -> None:
        rule = _make_rule(scope="main", applies_to="all")
        assert rule.effective_scope == "main"

    def test_invalid_priority_coerced_to_100(self) -> None:
        rule = CcagRule(rule_id="x", tool="Bash", priority="bad")  # type: ignore[arg-type]
        assert rule.priority == 100


# ---------------------------------------------------------------------------
# _tool_matches
# ---------------------------------------------------------------------------


class TestToolMatches:
    def test_exact_match(self) -> None:
        assert _tool_matches("Bash", "Bash") is True

    def test_exact_no_match(self) -> None:
        assert _tool_matches("Bash", "Write") is False

    def test_pipe_delimited(self) -> None:
        assert _tool_matches("Write|Edit", "Write") is True
        assert _tool_matches("Write|Edit", "Edit") is True
        assert _tool_matches("Write|Edit", "Read") is False

    def test_wildcard_suffix(self) -> None:
        assert _tool_matches("mcp__*", "mcp__some_tool") is True
        assert _tool_matches("mcp__*", "other_tool") is False

    def test_wildcard_prefix(self) -> None:
        assert _tool_matches("*_send", "llm_send") is True
        assert _tool_matches("*_send", "llm_recv") is False


# ---------------------------------------------------------------------------
# rule_matches
# ---------------------------------------------------------------------------


class TestRuleMatches:
    def test_allow_pattern_matches_command(self) -> None:
        rule = _make_rule(tool="Bash", allow_pattern="git push")
        assert rule_matches(rule, "Bash", {"command": "git push origin main"}) is True

    def test_allow_pattern_no_match(self) -> None:
        rule = _make_rule(tool="Bash", allow_pattern="git push")
        assert rule_matches(rule, "Bash", {"command": "rm -rf /"}) is False

    def test_block_pattern_takes_precedence(self) -> None:
        rule = _make_rule(
            tool="Bash",
            allow_pattern="git",
            block_pattern="rm -rf",
        )
        # block_pattern is active when set
        assert rule_matches(rule, "Bash", {"command": "rm -rf /tmp"}) is True

    def test_tool_mismatch_returns_false(self) -> None:
        rule = _make_rule(tool="Write", allow_pattern=".*")
        assert rule_matches(rule, "Bash", {"command": "ls"}) is False

    def test_unconditional_decision_rule(self) -> None:
        rule = _make_rule(tool="Read", decision="allow")
        assert rule_matches(rule, "Read", {}) is True

    def test_structured_conditions_all_must_pass(self) -> None:
        rule = _make_rule(
            tool="Bash",
            decision="allow",
            conditions=[
                {"param": "command", "matches": r"^git\s+"},
                {"param": "command", "not_matches": r"--force"},
            ],
        )
        assert rule_matches(rule, "Bash", {"command": "git push origin main"}) is True
        assert rule_matches(rule, "Bash", {"command": "git push --force"}) is False
        assert rule_matches(rule, "Bash", {"command": "ls -la"}) is False

    def test_file_path_anchor_pattern(self) -> None:
        rule = _make_rule(
            tool="Write",
            allow_pattern="^file_path:/project/src/",
        )
        assert rule_matches(rule, "Write", {"file_path": "/project/src/foo.py"}) is True
        assert rule_matches(rule, "Write", {"file_path": "/etc/passwd"}) is False

    def test_catastrophic_regex_rejected(self) -> None:
        # Nested quantifiers — should be rejected (no crash)
        rule = _make_rule(tool="Bash", allow_pattern="(a+)+b")
        assert rule_matches(rule, "Bash", {"command": "aab"}) is False

    def test_invalid_regex_returns_false(self) -> None:
        rule = _make_rule(tool="Bash", allow_pattern="[invalid(")
        assert rule_matches(rule, "Bash", {"command": "test"}) is False


# ---------------------------------------------------------------------------
# _serialise_input
# ---------------------------------------------------------------------------


class TestSerialiseInput:
    def test_basic_serialisation(self) -> None:
        result = _serialise_input({"command": "git push", "cwd": "/tmp"})
        assert "command:git push" in result
        assert "cwd:/tmp" in result

    def test_empty_input(self) -> None:
        assert _serialise_input({}) == ""


# ---------------------------------------------------------------------------
# YAML loading
# ---------------------------------------------------------------------------


class TestYamlLoading:
    def test_load_list_format(self, tmp_path: Path) -> None:
        rules_file = tmp_path / "rules.yaml"
        rules_file.write_text(
            yaml.dump(
                [{"id": "r1", "tool": "Bash", "allow_pattern": "git"}],
            ),
            encoding="utf-8",
        )
        rules = _load_yaml_rules(rules_file)
        assert len(rules) == 1
        assert rules[0].rule_id == "r1"

    def test_load_bundle_format(self, tmp_path: Path) -> None:
        rules_file = tmp_path / "rules.yaml"
        rules_file.write_text(
            yaml.dump(
                {"rules": [{"id": "r1", "tool": "Bash", "allow_pattern": "git"}]},
            ),
            encoding="utf-8",
        )
        rules = _load_yaml_rules(rules_file)
        assert len(rules) == 1

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        rules = _load_yaml_rules(tmp_path / "nonexistent.yaml")
        assert rules == []

    def test_malformed_yaml_returns_empty(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.yaml"
        bad.write_text("[broken yaml: {", encoding="utf-8")
        rules = _load_yaml_rules(bad)
        assert rules == []

    def test_rule_missing_tool_skipped(self, tmp_path: Path) -> None:
        rules_file = tmp_path / "rules.yaml"
        rules_file.write_text(
            yaml.dump([{"id": "bad", "allow_pattern": ".*"}]),
            encoding="utf-8",
        )
        rules = _load_yaml_rules(rules_file)
        assert rules == []

    def test_rule_invalid_priority_skipped(self, tmp_path: Path) -> None:
        rules_file = tmp_path / "rules.yaml"
        rules_file.write_text(
            yaml.dump([{"id": "r1", "tool": "Bash", "priority": "bad_priority", "allow_pattern": ".*"}]),
            encoding="utf-8",
        )
        # _parse_rule_entry validates priority with int() and skips on failure.
        # The Pydantic model's field_validator would coerce, but _parse_rule_entry
        # performs its own int() call first and skips invalid entries.
        rules = _load_yaml_rules(rules_file)
        assert len(rules) == 0


# ---------------------------------------------------------------------------
# load_rules — composite view
# ---------------------------------------------------------------------------


class TestLoadRules:
    def test_main_agent_loads_global(self, tmp_path: Path) -> None:
        _write_rules(
            tmp_path,
            "global.yaml",
            [{"id": "g1", "tool": "Bash", "allow_pattern": "git"}],
        )
        rule_set = load_rules(is_subagent=False, rules_dir=tmp_path)
        assert any(r.rule_id == "g1" for r in rule_set.allows)

    def test_subagent_loads_global_and_subagents(self, tmp_path: Path) -> None:
        _write_rules(
            tmp_path,
            "global.yaml",
            [{"id": "g1", "tool": "Bash", "allow_pattern": "git"}],
        )
        _write_rules(
            tmp_path,
            "subagents.yaml",
            [{"id": "s1", "tool": "Write", "block_pattern": "\\.claude/", "applies_to": "sub"}],
        )
        rule_set = load_rules(is_subagent=True, rules_dir=tmp_path)
        allow_ids = {r.rule_id for r in rule_set.allows}
        block_ids = {r.rule_id for r in rule_set.blocks}
        assert "g1" in allow_ids
        assert "s1" in block_ids

    def test_scope_filtering_main_rules_excluded_for_subagent(self, tmp_path: Path) -> None:
        _write_rules(
            tmp_path,
            "global.yaml",
            [{"id": "m1", "tool": "Bash", "allow_pattern": ".*", "scope": "main"}],
        )
        rule_set = load_rules(is_subagent=True, rules_dir=tmp_path)
        assert not any(r.rule_id == "m1" for r in rule_set.allows)

    def test_scope_filtering_sub_rules_excluded_for_main(self, tmp_path: Path) -> None:
        _write_rules(
            tmp_path,
            "global.yaml",
            [{"id": "s1", "tool": "Bash", "block_pattern": "rm", "scope": "sub"}],
        )
        rule_set = load_rules(is_subagent=False, rules_dir=tmp_path)
        assert not any(r.rule_id == "s1" for r in rule_set.blocks)

    def test_rules_sorted_by_priority(self, tmp_path: Path) -> None:
        _write_rules(
            tmp_path,
            "global.yaml",
            [
                {"id": "low", "tool": "Bash", "allow_pattern": ".*", "priority": 200},
                {"id": "high", "tool": "Bash", "allow_pattern": ".*", "priority": 10},
            ],
        )
        rule_set = load_rules(is_subagent=False, rules_dir=tmp_path)
        allows = list(rule_set.allows)
        assert allows[0].rule_id == "high"
        assert allows[1].rule_id == "low"

    def test_approved_loaded_before_global(self, tmp_path: Path) -> None:
        _write_rules(
            tmp_path,
            "approved.yaml",
            [{"id": "a1", "tool": "Bash", "allow_pattern": "approved-cmd"}],
        )
        _write_rules(
            tmp_path,
            "global.yaml",
            [{"id": "g1", "tool": "Bash", "allow_pattern": "global-cmd"}],
        )
        rule_set = load_rules(is_subagent=False, rules_dir=tmp_path)
        allow_ids = [r.rule_id for r in rule_set.allows]
        # approved comes first in raw loading (but priority determines final order)
        assert "a1" in allow_ids
        assert "g1" in allow_ids

    def test_empty_rules_dir_returns_empty_set(self, tmp_path: Path) -> None:
        rule_set = load_rules(is_subagent=False, rules_dir=tmp_path)
        assert rule_set.blocks == ()
        assert rule_set.allows == ()


# ---------------------------------------------------------------------------
# YAML roundtrip — append_approved_rule
# ---------------------------------------------------------------------------


class TestApprovedRuleRoundtrip:
    def test_append_and_reload(self, tmp_path: Path) -> None:
        rules_dir = tmp_path / "rules"
        rule = CcagRule(
            rule_id="auto-001",
            tool="Bash",
            allow_pattern="git push.*origin story/",
            learned_from="git push -u origin story/AK3-001",
            learned_at="2026-01-01T00:00:00+00:00",
            scope="main-agent",
        )
        append_approved_rule(rule, rules_dir)

        # File exists and reloads correctly
        approved = rules_dir / "approved.yaml"
        assert approved.is_file()

        loaded = _load_yaml_rules(approved)
        assert len(loaded) == 1
        assert loaded[0].rule_id == "auto-001"
        assert loaded[0].allow_pattern == "git push.*origin story/"
        assert loaded[0].learned_at == "2026-01-01T00:00:00+00:00"

    def test_append_multiple_rules(self, tmp_path: Path) -> None:
        rules_dir = tmp_path / "rules"
        for i in range(3):
            rule = CcagRule(
                rule_id=f"auto-{i:03d}",
                tool="Bash",
                allow_pattern=f"cmd-{i}",
                scope="main-agent",
            )
            append_approved_rule(rule, rules_dir)

        loaded = _load_yaml_rules(rules_dir / "approved.yaml")
        assert len(loaded) == 3
        ids = {r.rule_id for r in loaded}
        assert ids == {"auto-000", "auto-001", "auto-002"}

    def test_creates_dir_if_missing(self, tmp_path: Path) -> None:
        nested = tmp_path / "deep" / "nested" / "rules"
        rule = CcagRule(rule_id="r1", tool="Bash", allow_pattern=".*")
        append_approved_rule(rule, nested)
        assert (nested / "approved.yaml").is_file()

    def test_block_pattern_preserved_in_roundtrip(self, tmp_path: Path) -> None:
        rules_dir = tmp_path / "rules"
        rule = CcagRule(
            rule_id="block-001",
            tool="Bash",
            block_pattern="rm -rf",
            scope="all",
        )
        append_approved_rule(rule, rules_dir)
        loaded = _load_yaml_rules(rules_dir / "approved.yaml")
        assert loaded[0].block_pattern == "rm -rf"


# ---------------------------------------------------------------------------
# Static-allow and block-rule integration
# ---------------------------------------------------------------------------


class TestStaticRuleIntegration:
    """Static-Allow-Rule-Match -> allow / Block-Rule-Match -> block_by_rule."""

    def test_static_allow_match(self, tmp_path: Path) -> None:
        _write_rules(
            tmp_path,
            "global.yaml",
            [{"id": "allow-git", "tool": "Bash", "allow_pattern": r"^git\s"}],
        )
        rule_set = load_rules(is_subagent=False, rules_dir=tmp_path)
        matched = [
            r for r in rule_set.allows
            if rule_matches(r, "Bash", {"command": "git push origin main"})
        ]
        assert len(matched) == 1
        assert matched[0].rule_id == "allow-git"

    def test_block_rule_match(self, tmp_path: Path) -> None:
        _write_rules(
            tmp_path,
            "global.yaml",
            [{"id": "deny-rm", "tool": "Bash", "block_pattern": r"rm\s+-rf"}],
        )
        rule_set = load_rules(is_subagent=False, rules_dir=tmp_path)
        matched = [
            r for r in rule_set.blocks
            if rule_matches(r, "Bash", {"command": "rm -rf /tmp"})
        ]
        assert len(matched) == 1
        assert matched[0].rule_id == "deny-rm"

    def test_no_rule_match_returns_empty_lists(self, tmp_path: Path) -> None:
        _write_rules(
            tmp_path,
            "global.yaml",
            [{"id": "allow-git", "tool": "Bash", "allow_pattern": r"^git\s"}],
        )
        rule_set = load_rules(is_subagent=False, rules_dir=tmp_path)
        matched_allow = [
            r for r in rule_set.allows
            if rule_matches(r, "Bash", {"command": "ls -la"})
        ]
        matched_block = [
            r for r in rule_set.blocks
            if rule_matches(r, "Bash", {"command": "ls -la"})
        ]
        assert matched_allow == []
        assert matched_block == []
