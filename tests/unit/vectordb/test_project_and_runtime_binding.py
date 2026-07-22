"""Project + MCP runtime binding (R01/R15/R11)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from tests.support.vectordb.project_fixtures import make_fk13_project

from agentkit.backend.vectordb.project_binding import ProjectBindingError, bind_project
from agentkit.backend.vectordb.runtime_binding import (
    RuntimeBindingError,
    build_mcp_server_spec,
    load_runtime_binding_from_env,
    resolve_tool_project_id,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_bind_project_from_config(tmp_path: Path) -> None:
    root = make_fk13_project(tmp_path, "P1")
    binding = bind_project(root)
    assert binding.project_id == "P1"
    assert binding.concepts_dir.name == "concepts"
    assert binding.stories_dir.name == "stories"
    inside = binding.resolve_contained("stories/x/story.md")
    assert str(inside).startswith(str(binding.project_root))
    with pytest.raises(ProjectBindingError):
        binding.resolve_contained(tmp_path / "outside.txt")


def test_bind_project_missing_config_fails(tmp_path: Path) -> None:
    root = tmp_path / "empty"
    root.mkdir()
    with pytest.raises(ProjectBindingError, match="ProjectConfig"):
        bind_project(root)


def test_runtime_binding_from_env_no_defaults(tmp_path: Path) -> None:
    root = make_fk13_project(tmp_path, "ACME")
    env = {
        "PROJECT_ID": "ACME",
        "WEAVIATE_HOST": "weaviate.internal",
        "WEAVIATE_HTTP_PORT": "19903",
        "WEAVIATE_GRPC_PORT": "150051",
    }
    binding = load_runtime_binding_from_env(env, cwd=root)
    assert binding.weaviate_host == "weaviate.internal"
    assert binding.weaviate_http_port == 19903
    assert binding.project_id == "ACME"


def test_runtime_binding_missing_host_fails_closed(tmp_path: Path) -> None:
    root = make_fk13_project(tmp_path, "X")
    with pytest.raises(RuntimeBindingError, match="WEAVIATE_HOST"):
        load_runtime_binding_from_env(
            {
                "PROJECT_ID": "X",
                "WEAVIATE_HTTP_PORT": "1",
                "WEAVIATE_GRPC_PORT": "2",
            },
            cwd=root,
        )


def test_foreign_project_override_rejected(tmp_path: Path) -> None:
    root = make_fk13_project(tmp_path, "BOUND")
    env = {
        "PROJECT_ID": "BOUND",
        "WEAVIATE_HOST": "h",
        "WEAVIATE_HTTP_PORT": "9",
        "WEAVIATE_GRPC_PORT": "8",
    }
    binding = load_runtime_binding_from_env(env, cwd=root)
    assert resolve_tool_project_id(binding, None) == "BOUND"
    with pytest.raises(RuntimeBindingError, match="cross-project"):
        resolve_tool_project_id(binding, "OTHER")


def test_mcp_server_spec_env_is_ssot(tmp_path: Path) -> None:
    root = make_fk13_project(tmp_path, "P")
    project = bind_project(root)
    spec = build_mcp_server_spec(
        project=project,
        weaviate_host="not-localhost.example",
        weaviate_http_port=1234,
        weaviate_grpc_port=5678,
    )
    assert spec.env["WEAVIATE_HOST"] == "not-localhost.example"
    assert spec.env["WEAVIATE_HOST"] != "localhost"
