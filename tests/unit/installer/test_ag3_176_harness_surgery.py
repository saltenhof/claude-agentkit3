"""Value-preserving harness config surgery for AG3-176 install/uninstall."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from agentkit.backend.core_types.mcp_server_registration import (
    AK3_SERVER_SHAPES,
    ARE_MCP_SERVER,
    CODEX_HOOK_WRAPPER_NAME,
    REGISTERED_ENV_KEYS,
    STORY_KNOWLEDGE_BASE_SERVER,
)
from agentkit.backend.installer.mcp_registration import (
    STORY_KNOWLEDGE_BASE_ARGS,
    render_mcp_json_without_ak3,
    resolve_story_knowledge_base_command,
)
from agentkit.harness_client.harness_adapters.codex_config_toml import (
    load_codex_config,
    render_without_ak3,
)


def test_mcp_json_detach_removes_only_owned_fields_and_preserves_foreign_values(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    original = {
        "foreignTop": {"enabled": True, "threshold": 3},
        "mcpServers": {
            "foreign": {
                "command": "foreign-server",
                "args": ["--keep", "exactly"],
                "env": {"TOKEN": "foreign"},
            },
            "story-knowledge-base": {
                "type": "stdio",
                "command": resolve_story_knowledge_base_command(),
                "args": list(STORY_KNOWLEDGE_BASE_ARGS),
                "cwd": str(project_root),
                "env": dict.fromkeys(REGISTERED_ENV_KEYS, "value"),
                "foreignExtension": {"keep": [1, 2, 3]},
            },
        },
    }

    rendered = render_mcp_json_without_ak3(
        (json.dumps(original) + "\n").encode("utf-8"),
        project_root=project_root,
        resolved_command_owners={
            STORY_KNOWLEDGE_BASE_SERVER: resolve_story_knowledge_base_command()
        },
    )
    detached = json.loads(rendered)

    assert detached["foreignTop"] == original["foreignTop"]
    assert detached["mcpServers"]["foreign"] == original["mcpServers"]["foreign"]
    assert detached["mcpServers"]["story-knowledge-base"] == {"foreignExtension": {"keep": [1, 2, 3]}}


def test_mcp_json_detach_preserves_reserved_server_with_foreign_owned_value(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    entry = {
        "type": "foreign-transport",
        "command": resolve_story_knowledge_base_command(),
        "args": list(STORY_KNOWLEDGE_BASE_ARGS),
        "cwd": str(project_root),
        "env": dict.fromkeys(REGISTERED_ENV_KEYS, "value"),
    }
    original = {"mcpServers": {"story-knowledge-base": entry}}

    rendered = render_mcp_json_without_ak3(
        (json.dumps(original) + "\n").encode("utf-8"),
        project_root=project_root,
        resolved_command_owners={
            STORY_KNOWLEDGE_BASE_SERVER: resolve_story_knowledge_base_command()
        },
    )

    assert json.loads(rendered) == original


@pytest.mark.parametrize(
    "raw",
    [
        b'{"mcpServers":{}}',
        b'{ "mcpServers": {"foreign": {"command": "keep"}}, "x": 1 }',
    ],
)
def test_mcp_json_detach_is_byte_stable_without_an_owned_removal(
    raw: bytes,
    tmp_path: Path,
) -> None:
    """Empty and wholly foreign JSON cannot be normalized or deleted."""
    rendered = render_mcp_json_without_ak3(
        raw,
        project_root=tmp_path / "project",
        resolved_command_owners={},
    )

    assert rendered.encode("utf-8") == raw


def test_mcp_json_detach_is_byte_stable_when_interpreter_owner_is_missing(
    tmp_path: Path,
) -> None:
    """An AK3-shaped entry without its snapshot proof is not a mutation target."""
    project_root = tmp_path / "project"
    raw = json.dumps(
        {
            "mcpServers": {
                STORY_KNOWLEDGE_BASE_SERVER: {
                    "type": "stdio",
                    "command": resolve_story_knowledge_base_command(),
                    "args": list(STORY_KNOWLEDGE_BASE_ARGS),
                    "cwd": str(project_root),
                    "env": dict.fromkeys(REGISTERED_ENV_KEYS, "value"),
                }
            }
        },
        separators=(",", ":"),
    ).encode("utf-8")

    rendered = render_mcp_json_without_ak3(
        raw,
        project_root=project_root,
        resolved_command_owners={},
    )

    assert rendered.encode("utf-8") == raw


def test_mcp_json_detach_preserves_server_when_cwd_cannot_resolve(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A symlink-loop-style resolution failure must fail closed."""
    project_root = tmp_path / "project"
    entry = {
        "type": "stdio",
        "command": resolve_story_knowledge_base_command(),
        "args": list(STORY_KNOWLEDGE_BASE_ARGS),
        "cwd": str(project_root),
        "env": dict.fromkeys(REGISTERED_ENV_KEYS, "value"),
    }
    original = {"mcpServers": {"story-knowledge-base": entry}}

    import agentkit.backend.boundary.filesystem.path_identity as path_identity

    real_abspath = path_identity.os.path.abspath

    def _unresolvable(path: str) -> str:
        if path == str(project_root):
            raise RuntimeError("symlink loop")
        return real_abspath(path)

    monkeypatch.setattr(path_identity.os.path, "abspath", _unresolvable)
    rendered = render_mcp_json_without_ak3(
        (json.dumps(original) + "\n").encode("utf-8"),
        project_root=project_root,
        resolved_command_owners={
            STORY_KNOWLEDGE_BASE_SERVER: resolve_story_knowledge_base_command()
        },
    )

    assert json.loads(rendered) == original


def test_mcp_json_detach_uses_resolved_owner_for_are_wrapper(
    tmp_path: Path,
) -> None:
    """The JSON projection uses the same real ARE-owner proof as Codex TOML."""
    project_root = tmp_path / "project"
    project_root.mkdir()
    owner = tmp_path / "owner" / "agentkit-are-mcp.exe"
    owner.parent.mkdir()
    owner.write_text("owner", encoding="utf-8")
    foreign = tmp_path / "foreign" / "agentkit-are-mcp.exe"
    foreign.parent.mkdir()
    foreign.write_text("foreign", encoding="utf-8")
    shape = AK3_SERVER_SHAPES[ARE_MCP_SERVER]

    def _entry(command: Path) -> dict[str, object]:
        return {
            "type": "stdio",
            "command": str(command),
            "args": list(shape.args),
            "cwd": str(project_root),
            "env": dict.fromkeys(shape.env_keys, "value"),
        }

    owners = {ARE_MCP_SERVER: str(owner)}
    owned = {"mcpServers": {ARE_MCP_SERVER: _entry(owner)}}
    foreign_named = {"mcpServers": {ARE_MCP_SERVER: _entry(foreign)}}

    assert json.loads(
        render_mcp_json_without_ak3(
            (json.dumps(owned) + "\n").encode("utf-8"),
            project_root=project_root,
            resolved_command_owners=owners,
        )
    ) == {}
    assert json.loads(
        render_mcp_json_without_ak3(
            (json.dumps(foreign_named) + "\n").encode("utf-8"),
            project_root=project_root,
            resolved_command_owners=owners,
        )
    ) == foreign_named


def test_detach_command_owner_snapshot_is_immutable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A projection cannot change the owner proof seen by the next projection."""
    import agentkit.backend.installer.lifecycle.detach as detach_module

    owner = tmp_path / "agentkit-are-mcp.exe"
    owner.write_text("owner", encoding="utf-8")
    monkeypatch.setattr(
        detach_module,
        "resolve_ak3_wrapper",
        lambda _name: owner,
    )

    snapshot = detach_module._resolved_detach_command_owners()

    with pytest.raises(TypeError):
        snapshot[ARE_MCP_SERVER] = "foreign"  # type: ignore[index]


def test_codex_detach_removes_only_owned_fields_and_preserves_foreign_values(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    hook_owner_path = tmp_path / "ak3" / "agentkit-hook-codex.exe"
    hook_owner_path.parent.mkdir()
    hook_owner_path.write_text("owner", encoding="utf-8")
    hook_owner = str(hook_owner_path)
    interpreter_owner = resolve_story_knowledge_base_command()
    env = ", ".join(f'{key} = "value"' for key in sorted(REGISTERED_ENV_KEYS))
    original = f"""
title = "foreign title"

[hooks.pre_tool_use]
command = {json.dumps(hook_owner)}

[hooks.foreign]
command = "foreign-hook"

[mcp_servers.story-knowledge-base]
command = {json.dumps(interpreter_owner)}
args = {json.dumps(list(STORY_KNOWLEDGE_BASE_ARGS))}
cwd = {json.dumps(str(project_root))}
env = {{{env}}}
required = true
foreign_extension = "keep"

[mcp_servers.foreign]
command = "foreign-server"
args = ["--keep"]
required = false
"""
    rendered = render_without_ak3(
        original.encode("utf-8"),
        hook_command=hook_owner,
        project_root=project_root,
        resolved_command_owners={
            CODEX_HOOK_WRAPPER_NAME: hook_owner,
            STORY_KNOWLEDGE_BASE_SERVER: interpreter_owner,
        },
    )
    detached = load_codex_config(rendered.encode("utf-8"))

    assert detached["title"] == "foreign title"
    assert detached["hooks"] == {"foreign": {"command": "foreign-hook"}}
    assert detached["mcp_servers"]["foreign"] == {
        "command": "foreign-server",
        "args": ["--keep"],
        "required": False,
    }
    assert detached["mcp_servers"]["story-knowledge-base"] == {"foreign_extension": "keep"}
