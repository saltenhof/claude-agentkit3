"""Tests for the retained CCAG registration and obsolete-rule cleanup."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from agentkit.backend.boundary.filesystem import FilesystemContainmentError
from agentkit.backend.installer.ccag_settings import (
    CCAG_HOOK_MATCHER,
    build_ccag_hook_definition,
    remove_obsolete_permission_rule_files,
)
from agentkit.backend.skills import create_directory_link

if TYPE_CHECKING:
    from pathlib import Path


def test_ccag_matcher_and_hook_registration_survive() -> None:
    definition = build_ccag_hook_definition()

    assert CCAG_HOOK_MATCHER == "Bash|Write|Edit|Read|Grep|Glob|Agent"
    assert definition.matcher == CCAG_HOOK_MATCHER
    assert definition.command == "agentkit-hook-claude pre ccag_gatekeeper"


def test_upgrade_preserves_unrelated_files_in_ccag_directory(tmp_path: Path) -> None:
    rules_dir = tmp_path / ".agentkit" / "ccag" / "rules"
    rules_dir.mkdir(parents=True)
    retained = rules_dir / "operator-note.txt"
    retained.write_text("not a permission rule", encoding="utf-8")
    (rules_dir / "approved.yaml").write_text("rules: []\n", encoding="utf-8")

    removed = remove_obsolete_permission_rule_files(tmp_path)

    assert removed == [".agentkit/ccag/rules/approved.yaml"]
    assert retained.read_text(encoding="utf-8") == "not a permission rule"


def test_upgrade_cleanup_rejects_linked_rules_directory(tmp_path: Path) -> None:
    """Cleanup must not unlink a retired filename outside the project root."""
    project_root = tmp_path / "project"
    link_parent = project_root / ".agentkit" / "ccag"
    link_parent.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    protected = outside / "approved.yaml"
    protected.write_text("rules: []\n", encoding="utf-8")
    try:
        create_directory_link(link_parent / "rules", outside)
    except OSError as exc:
        pytest.skip(f"directory links unavailable: {exc}")

    with pytest.raises(FilesystemContainmentError):
        remove_obsolete_permission_rule_files(project_root)

    assert protected.read_text(encoding="utf-8") == "rules: []\n"


def test_upgrade_cleanup_validates_all_targets_before_deleting(tmp_path: Path) -> None:
    """A link at the last retired filename preserves the earlier files too."""
    project_root = tmp_path / "project"
    rules_dir = project_root / ".agentkit" / "ccag" / "rules"
    rules_dir.mkdir(parents=True)
    global_rule = rules_dir / "global.yaml"
    subagent_rule = rules_dir / "subagents.yaml"
    global_rule.write_text("rules: []\n", encoding="utf-8")
    subagent_rule.write_text("rules: []\n", encoding="utf-8")
    outside = tmp_path / "outside-approved.yaml"
    outside.write_text("rules: []\n", encoding="utf-8")
    try:
        (rules_dir / "approved.yaml").symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"file symlinks unavailable: {exc}")

    with pytest.raises(FilesystemContainmentError):
        remove_obsolete_permission_rule_files(project_root)

    assert global_rule.is_file()
    assert subagent_rule.is_file()
    assert outside.read_text(encoding="utf-8") == "rules: []\n"
