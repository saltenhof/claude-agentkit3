"""Detach may only remove hooks AK3 actually owns (FK-10 §10.2.9).

Detach DELETES what it matches, so a wrong match destroys a foreign project's
own configuration. Ownership was asserted by substring: any command line
mentioning an AK3 name counted as ours. These cases are the counter-examples
that were removed in the field.
"""

from __future__ import annotations

import shlex
from pathlib import Path

import pytest

from agentkit.backend.core_types.mcp_server_registration import (
    STORY_KNOWLEDGE_BASE_SERVER,
)
from agentkit.backend.installer.lifecycle.detach import _is_ak3_hook_command


def _owner_context(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    project_root = tmp_path / "project"
    (project_root / ".agentkit" / "hooks").mkdir(parents=True)
    owner_dir = tmp_path / "ak3-runtime"
    owner_dir.mkdir()
    interpreter = owner_dir / "python.exe"
    claude_wrapper = owner_dir / "agentkit-hook-claude.exe"
    codex_wrapper = owner_dir / "agentkit-hook-codex.exe"
    for path in (interpreter, claude_wrapper, codex_wrapper):
        path.write_text("owner", encoding="utf-8")
    return project_root, {
        STORY_KNOWLEDGE_BASE_SERVER: str(interpreter),
        "agentkit-hook-claude": str(claude_wrapper),
        "agentkit-hook-codex": str(codex_wrapper),
    }


def _classify(command: object, project_root: Path, owners: dict[str, str]) -> bool:
    return _is_ak3_hook_command(
        command,
        project_root=project_root,
        resolved_command_owners=owners,
    )


@pytest.mark.parametrize(
    "command",
    [
        # Foreign hooks that merely MENTION an AK3 name.
        'echo "agentkit-hook-codex" && ./foreign-quality-gate',
        "echo agentkit-hook-claude; ./foreign-gate",
        "./foreign-gate || agentkit-hook-claude",
        # Pre-isolation console-script forms are no longer produced or owned.
        "agentkit-hook-claude pre branch_guard",
        "agentkit-hook-codex post commit",
        # Foreign paths that merely CONTAIN the AK3 directory names.
        "sh /opt/.agentkit/hooks-backup/quality.sh",
        "python /opt/.agentkit/cache/hooks/foreign.sh",
        "python hooks/.agentkit/foreign.py",
        # The AK3 path is MENTIONED or read, not executed as a script.
        "echo .agentkit/hooks/story_guard.py",
        "foreign-tool --config /srv/.agentkit/hooks/config",
        "cat .agentkit/hooks/story_guard.py",
        # `-c` runs the text as code, `-m` treats it as a module name: neither
        # executes the file.
        "python -c .agentkit/hooks/story_guard.py",
        "python -m .agentkit/hooks/story_guard.py",
        # Direct module invocation is not an FK-30/FK-76 wrapper and is foreign.
        (
            "python -m agentkit.harness_client.harness_adapters.claude_code "
            "pre branch_guard"
        ),
        (
            "python -m agentkit.harness_client.harness_adapters.codex.cli "
            "post commit_hook"
        ),
        # `..` walks back out of the directory the path appears to name.
        "python .agentkit/hooks/../foreign.py",
        # Interpreters AK3 never registers a hook script through -- and whose
        # flags mean something else entirely (`-e`, `-Command` take code).
        "node -e .agentkit/hooks/foreign.js",
        "pwsh -Command .agentkit/hooks/foreign.ps1",
        "bash .agentkit/hooks/foreign.sh",
        # The wrapper name as an ARGUMENT, not as the executed command.
        "sh -c agentkit-hook-claude",
        # Not a command at all.
        "",
    ],
)
def test_foreign_hook_commands_are_not_claimed(tmp_path: Path, command: str) -> None:
    project_root, owners = _owner_context(tmp_path)
    if command.startswith("python "):
        command = (
            f"{shlex.quote(owners[STORY_KNOWLEDGE_BASE_SERVER])} {command[7:]}"
        )
    assert _classify(command, project_root, owners) is False


@pytest.mark.parametrize(
    "arguments",
    [
        ".agentkit/hooks/pre_tool_use.py",
        # A value option does not hide the script -- and a boolean switch such
        # as `-O` must not swallow it either.
        "-W ignore .agentkit/hooks/story_guard.py",
        "-O .agentkit/hooks/pre_tool_use.py",
        "-B -u .agentkit/hooks/pre_tool_use.py",
    ],
)
def test_project_hook_script_through_owned_interpreter_is_claimed(
    tmp_path: Path,
    arguments: str,
) -> None:
    project_root, owners = _owner_context(tmp_path)
    command = (
        f"{shlex.quote(owners[STORY_KNOWLEDGE_BASE_SERVER])} {arguments}"
    )
    assert _classify(command, project_root, owners) is True


@pytest.mark.parametrize(
    ("wrapper", "arguments"),
    [
        ("agentkit-hook-claude", "pre branch_guard"),
        ("agentkit-hook-codex", "post commit_hook"),
    ],
)
def test_centrally_owned_hook_wrapper_is_claimed(
    tmp_path: Path,
    wrapper: str,
    arguments: str,
) -> None:
    project_root, owners = _owner_context(tmp_path)
    command = f"{shlex.quote(owners[wrapper])} {arguments}"
    assert _classify(command, project_root, owners) is True


def test_foreign_absolute_wrapper_with_ak3_basename_is_not_claimed(
    tmp_path: Path,
) -> None:
    project_root, owners = _owner_context(tmp_path)
    foreign = tmp_path / "FOREIGN TOOL" / "agentkit-hook-claude.exe"
    foreign.parent.mkdir()
    foreign.write_text("foreign", encoding="utf-8")
    command = shlex.join((str(foreign), "pre", "branch_guard"))

    assert _classify(command, project_root, owners) is False


def test_foreign_project_hook_script_is_not_claimed(tmp_path: Path) -> None:
    project_root, owners = _owner_context(tmp_path)
    foreign_script = tmp_path / "foreign" / ".agentkit" / "hooks" / "audit.py"
    foreign_script.parent.mkdir(parents=True)
    foreign_script.write_text("# foreign", encoding="utf-8")
    command = shlex.join(
        (owners[STORY_KNOWLEDGE_BASE_SERVER], str(foreign_script))
    )

    assert _classify(command, project_root, owners) is False


def test_symlinked_command_owner_is_not_claimed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The narrow seam is required on Windows workers without symlink privilege."""
    project_root, owners = _owner_context(tmp_path)
    owner = Path(owners["agentkit-hook-claude"])
    real_is_symlink = Path.is_symlink
    monkeypatch.setattr(
        Path,
        "is_symlink",
        lambda path: path == owner or real_is_symlink(path),
    )
    command = shlex.join((str(owner), "pre", "branch_guard"))

    assert _classify(command, project_root, owners) is False


def test_symlinked_script_ancestor_before_dotdot_is_not_claimed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lexical cleanup cannot erase a mutable script-path ancestor."""
    project_root, owners = _owner_context(tmp_path)
    pivot = project_root / ".agentkit" / "pivot"
    real_is_symlink = Path.is_symlink
    monkeypatch.setattr(
        Path,
        "is_symlink",
        lambda path: path == pivot or real_is_symlink(path),
    )
    command = shlex.join(
        (
            owners[STORY_KNOWLEDGE_BASE_SERVER],
            ".agentkit/pivot/../hooks/pre_tool_use.py",
        )
    )

    assert _classify(command, project_root, owners) is False


def test_unresolvable_command_owner_is_not_claimed(tmp_path: Path) -> None:
    project_root, owners = _owner_context(tmp_path)
    command = shlex.join(
        (owners["agentkit-hook-codex"], "post", "commit_hook")
    )

    assert _classify(command, project_root, {}) is False


def test_unparsable_shell_is_left_alone(tmp_path: Path) -> None:
    """What cannot be parsed cannot be proven ours -- so it stays."""
    project_root, owners = _owner_context(tmp_path)
    assert (
        _classify('agentkit-hook-claude "unterminated', project_root, owners)
        is False
    )
