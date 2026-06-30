"""Real-filesystem integration tests for level-3 project-detach (AG3-122).

No stub-securing of the removal logic (testing-guardrails §2): a real temp
project with a REAL symlink/junction and a REAL foreign hook block is detached
on the real filesystem. The tests prove the FK-43 §43.4.1.1 footgun protection
(junctions detached via ``unlink``/``rmdir`` after an ``isjunction`` check, never
``rmtree`` through the link), surgical AK3-hook-block removal (foreign hooks
preserved) and the FK-10 §10.2.0 base rule (no canonical state deleted).
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

import pytest

from agentkit.backend.installer.codex_settings import build_codex_config_toml
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
    # The real AK3-generated Codex config (byte-equal -> detach removes it).
    (project_root / ".codex" / "config.toml").write_text(
        build_codex_config_toml(), encoding="utf-8"
    )

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


def test_detach_leaves_pure_foreign_claude_settings_byte_identical(
    tmp_path: Path,
) -> None:
    """B2 surgical regression: a settings.json with ZERO AK3 hooks is NOT rewritten.

    A project-owned ``.claude/settings.json`` that contains only FOREIGN, well-formed
    hooks must survive byte-for-byte — no indent/trailing-newline churn (the prior
    code rewrote it unconditionally once ``hooks`` was a well-formed object).
    """
    project_root = tmp_path / "project"
    (project_root / ".claude").mkdir(parents=True)
    settings_path = project_root / ".claude" / "settings.json"
    # Indent 4 + trailing newline: distinct from the indent-2, no-newline rewrite.
    content = (
        json.dumps(
            {
                "permissions": {"allow": ["Bash"]},
                "hooks": {
                    "PreToolUse": [
                        {"matcher": "Bash", "command": "/opt/foreign/audit-hook.sh"}
                    ]
                },
            },
            indent=4,
        )
        + "\n"
    )
    settings_path.write_text(content, encoding="utf-8")
    before = settings_path.read_bytes()

    result = detach_project(project_root)

    assert settings_path.read_bytes() == before  # byte-for-byte untouched
    assert result.removed_ak3_hooks == ()
    assert "/opt/foreign/audit-hook.sh" in result.preserved_foreign_hooks


def test_detach_leaves_pure_foreign_codex_hooks_byte_identical(tmp_path: Path) -> None:
    """B2 surgical regression (Codex mirror): a hooks.json with ZERO AK3 handlers
    is NOT rewritten and survives byte-for-byte."""
    project_root = tmp_path / "project"
    (project_root / ".codex").mkdir(parents=True)
    hooks_path = project_root / ".codex" / "hooks.json"
    content = (
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Bash",
                            "hooks": [
                                {"type": "command", "command": "/opt/foreign/audit.sh"}
                            ],
                        }
                    ]
                }
            },
            indent=4,
        )
        + "\n"
    )
    hooks_path.write_text(content, encoding="utf-8")
    before = hooks_path.read_bytes()

    result = detach_project(project_root)

    assert hooks_path.read_bytes() == before  # byte-for-byte untouched
    assert result.removed_ak3_hooks == ()


def test_detach_preserves_foreign_sibling_key_in_emptied_codex_group(
    tmp_path: Path,
) -> None:
    """B3 regression: dropping an AK3-only handler list must NOT discard foreign
    sibling keys of the matcher group (e.g. a foreign ``note``)."""
    project_root = tmp_path / "project"
    (project_root / ".codex").mkdir(parents=True)
    hooks_path = project_root / ".codex" / "hooks.json"
    codex = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Bash",
                    "hooks": [
                        {
                            "type": "command",
                            "command": "agentkit-hook-codex pre branch_guard",
                        }
                    ],
                    "note": "foreign-owned annotation",
                }
            ]
        }
    }
    hooks_path.write_text(json.dumps(codex, indent=2), encoding="utf-8")

    result = detach_project(project_root)

    surviving = json.loads(hooks_path.read_text(encoding="utf-8"))
    group = surviving["hooks"]["PreToolUse"][0]
    # Foreign sibling key survives; the emptied AK3 hook list becomes [] (D2: the
    # ``hooks`` key MUST stay present as a list — popping it leaves a schema-invalid
    # group the Codex writer rejects).
    assert group["note"] == "foreign-owned annotation"
    assert group["matcher"] == "Bash"
    assert "hooks" in group
    assert group["hooks"] == []
    assert "agentkit-hook-codex pre branch_guard" in result.removed_ak3_hooks
    # D2: the preserved group must pass the Codex settings-writer validation
    # (a popped ``hooks`` key would fail closed on a later registration/reinstall).
    from agentkit.harness_client.harness_adapters.settings_writer import (
        _coerce_hooks_section,
    )

    coerced = _coerce_hooks_section(surviving["hooks"])
    assert coerced["PreToolUse"][0]["hooks"] == []


def test_detach_drops_pure_ak3_codex_group_without_foreign_keys(
    tmp_path: Path,
) -> None:
    """A matcher group that is purely an AK3 registration (only structural keys) is
    still fully dropped when its handlers are all AK3."""
    project_root = tmp_path / "project"
    (project_root / ".codex").mkdir(parents=True)
    hooks_path = project_root / ".codex" / "hooks.json"
    codex = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Bash",
                    "hooks": [
                        {
                            "type": "command",
                            "command": "agentkit-hook-codex pre branch_guard",
                        }
                    ],
                }
            ]
        }
    }
    hooks_path.write_text(json.dumps(codex, indent=2), encoding="utf-8")

    detach_project(project_root)

    # The AK3-only group emptied the event, leaving the file structurally empty:
    # it is removed (no orphan matcher group left behind).
    assert not hooks_path.exists()


_AK3_PROMPT_BODY = "ak3 prompt body"


def _write_prompt_bundle(prompts_dir: Path, *, relpaths: dict[str, str]) -> None:
    """Materialise an AK3-deployed ``prompts/`` dir (manifest + template files).

    Mirrors ``runner._deploy_prompt_bindings``: the manifest lists ``templates``
    with a ``relpath`` AND the deployed file's ``sha256`` (raw-bytes digest, as
    ``runner._file_digests`` computes it); each template is deployed as
    ``Path(relpath).name`` with that exact content so the digest matches.
    """
    prompts_dir.mkdir(parents=True)
    digest = hashlib.sha256(_AK3_PROMPT_BODY.encode("utf-8")).hexdigest()
    manifest = {
        "bundle_id": "prompts-core",
        "bundle_version": "1",
        "templates": {
            name: {"relpath": relpath, "sha256": digest}
            for name, relpath in relpaths.items()
        },
    }
    (prompts_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    for relpath in relpaths.values():
        (prompts_dir / Path(relpath).name).write_text(_AK3_PROMPT_BODY, encoding="utf-8")


def test_detach_preserves_foreign_prompt_file_and_removes_ak3(tmp_path: Path) -> None:
    """B4 regression: a foreign file in ``prompts/`` SURVIVES detach while the
    AK3-deployed manifest + templates are removed (no wholesale ``rmtree``)."""
    project_root = tmp_path / "project"
    prompts = project_root / "prompts"
    _write_prompt_bundle(prompts, relpaths={"exec": "execute/exec.md", "plan": "plan.md"})
    # A user-owned file dropped into prompts/ (must survive).
    (prompts / "my-own.md").write_text("user content", encoding="utf-8")

    result = detach_project(project_root)

    assert (prompts / "my-own.md").read_text(encoding="utf-8") == "user content"
    assert not (prompts / "exec.md").exists()
    assert not (prompts / "plan.md").exists()
    assert not (prompts / "manifest.json").exists()
    assert prompts.is_dir()  # kept: the foreign file still lives here
    assert str(Path("prompts/exec.md")) in result.removed_bindings
    assert str(Path("prompts/manifest.json")) in result.removed_bindings


def test_detach_removes_prompts_dir_when_only_ak3_content(tmp_path: Path) -> None:
    """The normal AK3-only case still fully cleans up ``prompts/`` (empty -> removed)."""
    project_root = tmp_path / "project"
    prompts = project_root / "prompts"
    _write_prompt_bundle(prompts, relpaths={"plan": "plan.md"})

    detach_project(project_root)

    assert not prompts.exists()


def test_detach_preserves_user_modified_prompt_template(tmp_path: Path) -> None:
    """D3 regression: a user-MODIFIED AK3-named template SURVIVES detach.

    Detach must delete a prompt file only when its content's sha256 still matches
    the manifest digest (proving it is unmodified AK3 content). A user edit changes
    the digest, so the file is preserved byte-for-byte while the unmodified sibling
    is removed.
    """
    project_root = tmp_path / "project"
    prompts = project_root / "prompts"
    _write_prompt_bundle(prompts, relpaths={"exec": "exec.md", "plan": "plan.md"})
    # The user edits one AK3-deployed template -> digest no longer matches.
    modified = "MY OWN EDITS\n" + _AK3_PROMPT_BODY
    (prompts / "plan.md").write_text(modified, encoding="utf-8")

    result = detach_project(project_root)

    # Unmodified template removed; modified template preserved byte-for-byte.
    assert not (prompts / "exec.md").exists()
    assert (prompts / "plan.md").read_text(encoding="utf-8") == modified
    assert prompts.is_dir()  # kept: the modified file still lives here
    assert str(Path("prompts/plan.md")) in result.preserved_foreign_files
    assert str(Path("prompts/plan.md")) not in result.removed_bindings


def test_detach_preserves_foreign_file_colliding_with_ak3_basename(
    tmp_path: Path,
) -> None:
    """D3: a FOREIGN file whose basename collides with an AK3 template but whose
    content differs (digest mismatch) SURVIVES detach."""
    project_root = tmp_path / "project"
    prompts = project_root / "prompts"
    # The manifest claims ``plan.md`` is AK3, but on disk it is foreign content.
    digest = hashlib.sha256(_AK3_PROMPT_BODY.encode("utf-8")).hexdigest()
    prompts.mkdir(parents=True)
    manifest = {
        "bundle_id": "prompts-core",
        "bundle_version": "1",
        "templates": {"plan": {"relpath": "plan.md", "sha256": digest}},
    }
    (prompts / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (prompts / "plan.md").write_text("foreign content, not AK3", encoding="utf-8")

    result = detach_project(project_root)

    assert (prompts / "plan.md").read_text(encoding="utf-8") == "foreign content, not AK3"
    assert str(Path("prompts/plan.md")) in result.preserved_foreign_files
    # The manifest itself is AK3-owned and is removed (its set is accounted for).
    assert not (prompts / "manifest.json").exists()


def test_detach_with_malformed_manifest_removes_nothing(tmp_path: Path) -> None:
    """D4 regression: a malformed/hand-edited ``prompts/manifest.json`` makes detach
    remove NOTHING from ``prompts/`` (fail safe) — manifest and files survive."""
    project_root = tmp_path / "project"
    prompts = project_root / "prompts"
    prompts.mkdir(parents=True)
    # Hand-edited, no longer valid JSON.
    (prompts / "manifest.json").write_text('{"templates": {trunca', encoding="utf-8")
    (prompts / "plan.md").write_text(_AK3_PROMPT_BODY, encoding="utf-8")

    result = detach_project(project_root)

    # Nothing in prompts/ was touched.
    assert (prompts / "manifest.json").read_text(encoding="utf-8") == '{"templates": {trunca'
    assert (prompts / "plan.md").read_text(encoding="utf-8") == _AK3_PROMPT_BODY
    assert prompts.is_dir()
    assert not any(p.startswith("prompts") for p in result.removed_bindings)


@pytest.mark.parametrize(
    "bad_entry",
    [
        pytest.param("not-a-dict", id="entry-not-dict"),
        pytest.param({"sha256": "deadbeef"}, id="missing-relpath"),
        pytest.param({"relpath": "", "sha256": "deadbeef"}, id="empty-relpath"),
        pytest.param({"relpath": "bad.md"}, id="missing-sha256"),
        pytest.param({"relpath": "bad.md", "sha256": ""}, id="empty-sha256"),
    ],
)
def test_detach_entry_level_malformed_manifest_removes_nothing(
    tmp_path: Path, bad_entry: object
) -> None:
    """F2 regression: a manifest with ONE valid + ONE malformed ``templates`` entry
    makes detach remove NOTHING from ``prompts/`` (fail safe, D4).

    A partial digest map previously removed the valid template AND dropped the
    manifest, deleting real content next to a single malformed entry. D4 requires
    "malformed -> remove nothing": the valid template, the colliding entry's file
    AND the manifest must all survive.
    """
    project_root = tmp_path / "project"
    prompts = project_root / "prompts"
    prompts.mkdir(parents=True)
    valid_digest = hashlib.sha256(_AK3_PROMPT_BODY.encode("utf-8")).hexdigest()
    manifest = {
        "bundle_id": "prompts-core",
        "bundle_version": "1",
        "templates": {
            "plan": {"relpath": "plan.md", "sha256": valid_digest},
            "broken": bad_entry,
        },
    }
    (prompts / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (prompts / "plan.md").write_text(_AK3_PROMPT_BODY, encoding="utf-8")

    result = detach_project(project_root)

    # The valid template AND the manifest survive — nothing in prompts/ was touched.
    assert (prompts / "plan.md").read_text(encoding="utf-8") == _AK3_PROMPT_BODY
    assert (prompts / "manifest.json").is_file()
    assert prompts.is_dir()
    assert not any(p.startswith("prompts") for p in result.removed_bindings)
    assert not any(p.startswith("prompts") for p in result.preserved_foreign_files)


def test_detach_removes_byte_equal_ak3_codex_config(tmp_path: Path) -> None:
    """D5: a ``.codex/config.toml`` that byte-equals the AK3 config is removed."""
    project_root = tmp_path / "project"
    (project_root / ".codex").mkdir(parents=True)
    config_path = project_root / ".codex" / "config.toml"
    config_path.write_text(build_codex_config_toml(), encoding="utf-8")

    result = detach_project(project_root)

    assert not config_path.exists()
    assert str(Path(".codex/config.toml")) in result.removed_bindings


def test_detach_preserves_foreign_codex_config(tmp_path: Path) -> None:
    """D5 regression: a ``.codex/config.toml`` carrying foreign config (not byte-equal
    to the AK3 config) SURVIVES detach byte-for-byte instead of being deleted."""
    project_root = tmp_path / "project"
    (project_root / ".codex").mkdir(parents=True)
    config_path = project_root / ".codex" / "config.toml"
    # AK3 config PLUS a foreign user-added section.
    foreign = build_codex_config_toml() + '\n[user.custom]\nkey = "value"\n'
    config_path.write_text(foreign, encoding="utf-8")
    before = config_path.read_bytes()

    result = detach_project(project_root)

    assert config_path.read_bytes() == before  # byte-for-byte preserved
    assert str(Path(".codex/config.toml")) in result.preserved_foreign_files
    assert str(Path(".codex/config.toml")) not in result.removed_bindings


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
