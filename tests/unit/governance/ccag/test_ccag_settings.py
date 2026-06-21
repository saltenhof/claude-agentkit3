"""Tests for agentkit.backend.installer.ccag_settings — deploy and remove."""

from __future__ import annotations

from typing import TYPE_CHECKING

import yaml

from agentkit.backend.installer.ccag_settings import (
    CCAG_RULES_SUBDIR,
    build_claude_hook_entry,
    build_claude_settings_snippet,
    ccag_rules_dir,
    deploy_ccag_rules,
    remove_ccag_rules,
)

if TYPE_CHECKING:
    from pathlib import Path


class TestDeployCcagRules:
    def test_deploy_creates_all_three_files(self, tmp_path: Path) -> None:
        written = deploy_ccag_rules(tmp_path)
        assert len(written) == 3
        rules_dir = ccag_rules_dir(tmp_path)
        assert (rules_dir / "global.yaml").is_file()
        assert (rules_dir / "subagents.yaml").is_file()
        assert (rules_dir / "approved.yaml").is_file()

    def test_deploy_idempotent_second_call_writes_nothing(
        self, tmp_path: Path
    ) -> None:
        deploy_ccag_rules(tmp_path)
        written_second = deploy_ccag_rules(tmp_path)
        assert written_second == []

    def test_deploy_does_not_overwrite_customised_file(
        self, tmp_path: Path
    ) -> None:
        deploy_ccag_rules(tmp_path)
        global_yaml = ccag_rules_dir(tmp_path) / "global.yaml"
        original_content = global_yaml.read_text(encoding="utf-8")
        customised = original_content + "\n# custom addition\n"
        global_yaml.write_text(customised, encoding="utf-8")

        deploy_ccag_rules(tmp_path)  # second deploy
        assert global_yaml.read_text(encoding="utf-8") == customised

    def test_deploy_global_yaml_is_valid_yaml(self, tmp_path: Path) -> None:
        deploy_ccag_rules(tmp_path)
        global_yaml = ccag_rules_dir(tmp_path) / "global.yaml"
        parsed = yaml.safe_load(global_yaml.read_text(encoding="utf-8"))
        assert "rules" in parsed
        assert isinstance(parsed["rules"], list)

    def test_deploy_subagents_yaml_is_valid_yaml(self, tmp_path: Path) -> None:
        deploy_ccag_rules(tmp_path)
        subagents_yaml = ccag_rules_dir(tmp_path) / "subagents.yaml"
        parsed = yaml.safe_load(subagents_yaml.read_text(encoding="utf-8"))
        assert "rules" in parsed

    def test_ccag_rules_dir_path(self, tmp_path: Path) -> None:
        expected = tmp_path / CCAG_RULES_SUBDIR
        assert ccag_rules_dir(tmp_path) == expected


class TestHookRegistration:
    def test_claude_hook_entry_has_required_keys(self) -> None:
        entry = build_claude_hook_entry()
        assert "matcher" in entry
        assert "command" in entry
        assert "ccag_gatekeeper" in entry["command"]

    def test_claude_settings_snippet_is_valid_json(self) -> None:
        import json

        snippet = build_claude_settings_snippet()
        parsed = json.loads(snippet)
        assert "hooks" in parsed
        assert "PreToolUse" in parsed["hooks"]


class TestRemoveCcagRules:
    def test_remove_deployed_files(self, tmp_path: Path) -> None:
        deploy_ccag_rules(tmp_path)
        # approved.yaml is empty (header only) → removed
        removed = remove_ccag_rules(tmp_path)
        # At minimum global.yaml and subagents.yaml removed
        assert any("global.yaml" in r for r in removed)
        assert any("subagents.yaml" in r for r in removed)

    def test_remove_preserves_approved_with_user_rules(
        self, tmp_path: Path
    ) -> None:
        deploy_ccag_rules(tmp_path)
        approved = ccag_rules_dir(tmp_path) / "approved.yaml"
        # Add a user rule
        approved.write_text(
            yaml.dump([{"id": "u1", "tool": "Bash", "allow_pattern": "git"}]),
            encoding="utf-8",
        )
        remove_ccag_rules(tmp_path)
        # approved.yaml should still be there (has user rules)
        assert approved.is_file()
