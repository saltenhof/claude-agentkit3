"""Value-preserving harness config surgery for AG3-176 install/uninstall."""

from __future__ import annotations

import json

from agentkit.backend.installer.mcp_registration import (
    STORY_KNOWLEDGE_BASE_ARGS,
    render_mcp_json_without_ak3,
    resolve_story_knowledge_base_command,
)
from agentkit.harness_client.harness_adapters.codex_config_toml import (
    load_codex_config,
    render_without_ak3,
)


def test_mcp_json_detach_removes_only_owned_fields_and_preserves_foreign_values() -> None:
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
                "cwd": "T:/project",
                "env": {"PROJECT_ID": "AG3"},
                "foreignExtension": {"keep": [1, 2, 3]},
            },
        },
    }

    rendered = render_mcp_json_without_ak3((json.dumps(original) + "\n").encode("utf-8"))
    detached = json.loads(rendered)

    assert detached["foreignTop"] == original["foreignTop"]
    assert detached["mcpServers"]["foreign"] == original["mcpServers"]["foreign"]
    assert detached["mcpServers"]["story-knowledge-base"] == {"foreignExtension": {"keep": [1, 2, 3]}}


def test_codex_detach_removes_only_owned_fields_and_preserves_foreign_values() -> None:
    original = f"""
title = "foreign title"

[hooks.pre_tool_use]
command = "agentkit-hook-codex"

[hooks.foreign]
command = "foreign-hook"

[mcp_servers.story-knowledge-base]
command = {json.dumps(resolve_story_knowledge_base_command())}
args = {json.dumps(list(STORY_KNOWLEDGE_BASE_ARGS))}
cwd = "T:/project"
required = true
foreign_extension = "keep"

[mcp_servers.story-knowledge-base.env]
PROJECT_ID = "AG3"

[mcp_servers.foreign]
command = "foreign-server"
args = ["--keep"]
required = false
"""
    rendered = render_without_ak3(
        original.encode("utf-8"),
        hook_command="agentkit-hook-codex",
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
