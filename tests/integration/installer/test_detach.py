"""Real-filesystem integration tests for level-3 project-detach (AG3-122).

No stub-securing of the removal logic (testing-guardrails §2): a real temp
project with a REAL symlink/junction and a REAL foreign hook block is detached
on the real filesystem. The tests prove the FK-43 §43.4.1.1 footgun protection
(junctions detached via ``unlink``/``rmdir`` after an ``isjunction`` check, never
``rmtree`` through the link), surgical AK3-hook-block removal (foreign hooks
preserved) and the FK-10 §10.2.0 base rule (no canonical state deleted).
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from agentkit.backend.installer.lifecycle.detach import detach_project
from agentkit.backend.skills import create_directory_link, is_directory_link


def _directory_links_supported() -> bool:
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "src"
        src.mkdir()
        try:
            create_directory_link(Path(d) / "link", src)
            return True
        except OSError:
            return False


_LINKS_AVAILABLE = _directory_links_supported()

pytestmark = pytest.mark.skipif(
    not _LINKS_AVAILABLE,
    reason="Filesystem supports neither symlinks nor directory junctions",
)


def _build_project_with_bindings(tmp_path: Path) -> tuple[Path, Path]:
    """Materialise a real project with AK3 bindings + foreign content.

    Returns ``(project_root, bundle_target)`` where ``bundle_target`` is the
    CENTRAL bundle-store directory the skill junction points at.
    """
    project_root = tmp_path / "project"
    project_root.mkdir()

    # Central bundle store (a HIGHER-level artifact); its content must survive.
    bundle_store = tmp_path / "central-bundle-store"
    bundle_target = bundle_store / "skill-a"
    bundle_target.mkdir(parents=True)
    (bundle_target / "SKILL.md").write_text("central skill body", encoding="utf-8")

    # Real skill junctions/symlinks into the central store.
    for harness in (".claude", ".codex"):
        skills_dir = project_root / harness / "skills"
        skills_dir.mkdir(parents=True)
        create_directory_link(skills_dir / "skill-a", bundle_target)

    # .claude/settings.json: one AK3 hook block + one FOREIGN hook block + a
    # foreign top-level key.
    claude_settings = {
        "permissions": {"allow": ["Bash"]},  # foreign top-level key
        "hooks": {
            "PreToolUse": [
                {"matcher": "Bash", "command": "agentkit-hook-claude pre branch_guard"},
                {"matcher": "Bash", "command": "/opt/foreign/audit-hook.sh"},
            ]
        },
    }
    (project_root / ".claude" / "settings.json").write_text(
        json.dumps(claude_settings, indent=2), encoding="utf-8"
    )

    # .codex/hooks.json: AK3 handler + foreign handler in the same matcher group.
    codex_hooks = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Bash",
                    "hooks": [
                        {"type": "command", "command": "agentkit-hook-codex pre branch_guard"},
                        {"type": "command", "command": "/opt/foreign/codex-audit.sh"},
                    ],
                }
            ]
        }
    }
    (project_root / ".codex" / "hooks.json").write_text(
        json.dumps(codex_hooks, indent=2), encoding="utf-8"
    )
    (project_root / ".codex" / "config.toml").write_text("# ak3", encoding="utf-8")

    # AK3 bindings + edge launcher.
    (project_root / ".agentkit" / "config").mkdir(parents=True)
    (project_root / ".agentkit" / "config" / "project.yaml").write_text("k: v", encoding="utf-8")
    (project_root / "tools" / "agentkit").mkdir(parents=True)
    (project_root / "tools" / "agentkit" / "projectedge.py").write_text("# edge", encoding="utf-8")

    # Project code (must survive).
    (project_root / "src").mkdir()
    (project_root / "src" / "app.py").write_text("print('hi')", encoding="utf-8")
    return project_root, bundle_target


def test_detach_uses_safe_junction_removal_and_central_store_survives(
    tmp_path: Path,
) -> None:
    project_root, bundle_target = _build_project_with_bindings(tmp_path)
    claude_link = project_root / ".claude" / "skills" / "skill-a"
    assert is_directory_link(claude_link)

    result = detach_project(project_root)

    # The junctions are detached (unlink/rmdir after isjunction), not present.
    assert not claude_link.exists()
    assert not (project_root / ".codex" / "skills" / "skill-a").exists()
    assert str(Path(".claude/skills/skill-a")) in result.detached_junctions
    # FK-43 footgun: the CENTRAL bundle target content SURVIVES (no rmtree through
    # the junction).
    assert bundle_target.is_dir()
    assert (bundle_target / "SKILL.md").read_text(encoding="utf-8") == "central skill body"


def test_detach_removes_only_ak3_hook_blocks_and_preserves_foreign(
    tmp_path: Path,
) -> None:
    project_root, _ = _build_project_with_bindings(tmp_path)

    result = detach_project(project_root)

    # .claude/settings.json survives (it carries a foreign hook + foreign key).
    settings_path = project_root / ".claude" / "settings.json"
    assert settings_path.is_file()
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    pre = settings["hooks"]["PreToolUse"]
    commands = [entry["command"] for entry in pre]
    assert "/opt/foreign/audit-hook.sh" in commands  # foreign preserved
    assert all(not c.startswith("agentkit-hook-claude") for c in commands)  # AK3 gone
    assert settings["permissions"] == {"allow": ["Bash"]}  # foreign key preserved

    # .codex/hooks.json survives with only the foreign handler.
    codex = json.loads((project_root / ".codex" / "hooks.json").read_text(encoding="utf-8"))
    handlers = codex["hooks"]["PreToolUse"][0]["hooks"]
    codex_commands = [h["command"] for h in handlers]
    assert codex_commands == ["/opt/foreign/codex-audit.sh"]

    assert "agentkit-hook-claude pre branch_guard" in result.removed_ak3_hooks
    assert "/opt/foreign/audit-hook.sh" in result.preserved_foreign_hooks


def test_detach_removes_ak3_bindings_and_launcher(tmp_path: Path) -> None:
    project_root, _ = _build_project_with_bindings(tmp_path)

    detach_project(project_root)

    assert not (project_root / ".agentkit").exists()
    assert not (project_root / "tools" / "agentkit").exists()
    assert not (project_root / ".codex" / "config.toml").exists()


def test_detach_deletes_no_canonical_state_or_project_code(tmp_path: Path) -> None:
    """Negative path: a lower level never deletes higher-level canonical state.

    Detach is filesystem-only and never touches the project's central (state
    backend) state nor the project's own code.
    """
    project_root, bundle_target = _build_project_with_bindings(tmp_path)
    # A stand-in for the project's CENTRAL canonical state, outside the project.
    central_state = tmp_path / "central-state" / "audit.db"
    central_state.parent.mkdir(parents=True)
    central_state.write_text("canonical", encoding="utf-8")

    detach_project(project_root)

    # Project code untouched.
    assert (project_root / "src" / "app.py").read_text(encoding="utf-8") == "print('hi')"
    # Central state (higher level) untouched.
    assert central_state.read_text(encoding="utf-8") == "canonical"
    # Central bundle store (higher level) untouched.
    assert bundle_target.is_dir()


def test_detach_preserves_foreign_hook_in_unexpected_shape(tmp_path: Path) -> None:
    """Fail-closed: a foreign hook in an UNEXPECTED shape SURVIVES detach.

    A malformed/unexpected hook structure must NOT be coerced (coercing would
    delete foreign hooks), mirroring the fail-closed harness settings-writer
    contract. Only recognised AK3 blocks in well-formed lists are stripped.
    """
    project_root = tmp_path / "project"
    (project_root / ".claude").mkdir(parents=True)
    settings_path = project_root / ".claude" / "settings.json"
    settings = {
        "permissions": {"allow": ["Bash"]},  # foreign top-level key
        "hooks": {
            # Well-formed event: AK3 block + foreign block.
            "PreToolUse": [
                {"matcher": "Bash", "command": "agentkit-hook-claude pre branch_guard"},
                {"matcher": "Bash", "command": "/opt/foreign/audit-hook.sh"},
            ],
            # UNEXPECTED shape (a string, not a list-of-blocks): a foreign hook
            # registration AK3 does not own — it must survive verbatim.
            "Stop": "/opt/foreign/stop-hook.sh",
            # UNEXPECTED shape (a dict, not a list): also foreign, also survives.
            "SessionStart": {"command": "/opt/foreign/session-hook.sh"},
        },
    }
    settings_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")

    result = detach_project(project_root)

    surviving = json.loads(settings_path.read_text(encoding="utf-8"))
    hooks = surviving["hooks"]
    # The malformed/unexpected foreign shapes are preserved verbatim.
    assert hooks["Stop"] == "/opt/foreign/stop-hook.sh"
    assert hooks["SessionStart"] == {"command": "/opt/foreign/session-hook.sh"}
    # The well-formed event still strips AK3 and keeps the foreign block.
    pre_commands = [entry["command"] for entry in hooks["PreToolUse"]]
    assert pre_commands == ["/opt/foreign/audit-hook.sh"]
    assert surviving["permissions"] == {"allow": ["Bash"]}
    assert "agentkit-hook-claude pre branch_guard" in result.removed_ak3_hooks


def test_detach_preserves_settings_with_malformed_top_level_hooks(
    tmp_path: Path,
) -> None:
    """A present-but-malformed top-level ``hooks`` value is preserved verbatim.

    ``hooks`` as a list (not an object) is an unexpected shape: detach must NOT
    pop/rewrite it (that would delete the foreign config), it leaves the file
    untouched (fail-closed).
    """
    project_root = tmp_path / "project"
    (project_root / ".claude").mkdir(parents=True)
    settings_path = project_root / ".claude" / "settings.json"
    foreign = {"hooks": [{"command": "/opt/foreign/weird-hook.sh"}]}
    settings_path.write_text(json.dumps(foreign, indent=2), encoding="utf-8")

    detach_project(project_root)

    # The foreign settings file survives byte-for-byte semantically (no coercion).
    assert json.loads(settings_path.read_text(encoding="utf-8")) == foreign


def test_detach_preserves_foreign_codex_group_in_unexpected_shape(
    tmp_path: Path,
) -> None:
    """A Codex matcher group with a malformed handler list survives verbatim."""
    project_root = tmp_path / "project"
    (project_root / ".codex").mkdir(parents=True)
    hooks_path = project_root / ".codex" / "hooks.json"
    codex = {
        "hooks": {
            "PreToolUse": [
                # Well-formed group: AK3 handler + foreign handler.
                {
                    "matcher": "Bash",
                    "hooks": [
                        {"type": "command", "command": "agentkit-hook-codex pre branch_guard"},
                        {"type": "command", "command": "/opt/foreign/codex-audit.sh"},
                    ],
                },
                # UNEXPECTED shape (``hooks`` is a string, not a list): foreign,
                # must survive verbatim — never coerced/dropped.
                {"matcher": "Stop", "hooks": "/opt/foreign/codex-stop.sh"},
            ]
        }
    }
    hooks_path.write_text(json.dumps(codex, indent=2), encoding="utf-8")

    detach_project(project_root)

    surviving = json.loads(hooks_path.read_text(encoding="utf-8"))
    groups = surviving["hooks"]["PreToolUse"]
    # The malformed foreign group is preserved verbatim.
    assert {"matcher": "Stop", "hooks": "/opt/foreign/codex-stop.sh"} in groups
    # The well-formed group keeps only the foreign handler.
    well_formed = next(g for g in groups if g["matcher"] == "Bash")
    assert [h["command"] for h in well_formed["hooks"]] == ["/opt/foreign/codex-audit.sh"]


def test_detach_missing_project_root_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        detach_project(tmp_path / "does-not-exist")


def test_detach_junction_removal_path_is_unlink_or_rmdir(tmp_path: Path) -> None:
    """Guard the FK-43 footgun directly: removal goes via unlink/rmdir, the link
    target keeps its inode/content (never recursed through)."""
    project_root, bundle_target = _build_project_with_bindings(tmp_path)
    link = project_root / ".claude" / "skills" / "skill-a"
    # The link is recognised as a junction/symlink (the isjunction-aware check).
    assert link.is_symlink() or os.path.isjunction(link)

    detach_project(project_root)

    assert not os.path.lexists(link)
    assert (bundle_target / "SKILL.md").is_file()
