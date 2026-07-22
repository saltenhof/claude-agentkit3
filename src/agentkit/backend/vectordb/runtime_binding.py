"""Authoritative MCP runtime binding (AG3-174 Review 174-P0-4).

A single typed :class:`McpServerSpec` / :class:`RuntimeBinding` is the SSOT for
the started MCP process. ``PROJECT_ID`` and the HTTP/gRPC endpoint come
**exclusively** from the registered ``env``. ``cwd`` is the work/containment
boundary only — never a second configuration source and never a
localhost/default fallback.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from agentkit.backend.vectordb.project_binding import ProjectBinding, ProjectBindingError, bind_project

if TYPE_CHECKING:
    from collections.abc import Mapping

ENV_PROJECT_ID: Final[str] = "PROJECT_ID"
ENV_WEAVIATE_HOST: Final[str] = "WEAVIATE_HOST"
ENV_WEAVIATE_HTTP_PORT: Final[str] = "WEAVIATE_HTTP_PORT"
ENV_WEAVIATE_GRPC_PORT: Final[str] = "WEAVIATE_GRPC_PORT"
ENV_CONCEPTS_DIR: Final[str] = "CONCEPTS_DIR"
ENV_STORIES_DIR: Final[str] = "STORIES_DIR"


class RuntimeBindingError(Exception):
    """Raised when MCP runtime binding is missing or invalid (fail-closed)."""


@dataclass(frozen=True)
class RuntimeBinding:
    """Resolved runtime values for a bound MCP / VectorDB process.

    Attributes:
        project_id: Bound project identifier (discriminator).
        weaviate_host: Weaviate host from registered env (no default).
        weaviate_http_port: Weaviate HTTP port from registered env.
        weaviate_grpc_port: Weaviate gRPC port from registered env.
        project: Validated :class:`ProjectBinding`.
    """

    project_id: str
    weaviate_host: str
    weaviate_http_port: int
    weaviate_grpc_port: int
    project: ProjectBinding


@dataclass(frozen=True)
class McpServerSpec:
    """Authoritative MCP server process specification (SSOT for AG3-175).

    Attributes:
        command: Executable to start.
        args: Argument vector.
        cwd: Working directory / containment boundary (not a config source).
        env: Registered environment map; sole source of PROJECT_ID + endpoint.
    """

    command: str
    args: tuple[str, ...]
    cwd: str
    env: Mapping[str, str]

    def to_registration_dict(self) -> dict[str, object]:
        """Serialize for harness registration consumers (AG3-175)."""
        return {
            "command": self.command,
            "args": list(self.args),
            "cwd": self.cwd,
            "env": dict(self.env),
        }


def build_mcp_server_spec(
    *,
    project: ProjectBinding,
    weaviate_host: str,
    weaviate_http_port: int,
    weaviate_grpc_port: int,
    command: str = "agentkit-mcp-story-kb",
    args: tuple[str, ...] = (),
) -> McpServerSpec:
    """Build the authoritative MCP server spec for a project.

    All endpoint / project identity values go into ``env`` only.
    """
    if not weaviate_host or not isinstance(weaviate_host, str):
        raise RuntimeBindingError("weaviate_host must be a non-empty string (fail-closed).")
    if not isinstance(weaviate_http_port, int) or isinstance(weaviate_http_port, bool):
        raise RuntimeBindingError("weaviate_http_port must be an int (fail-closed).")
    if not isinstance(weaviate_grpc_port, int) or isinstance(weaviate_grpc_port, bool):
        raise RuntimeBindingError("weaviate_grpc_port must be an int (fail-closed).")
    if weaviate_http_port <= 0 or weaviate_grpc_port <= 0:
        raise RuntimeBindingError("Weaviate ports must be positive integers (fail-closed).")

    env = {
        ENV_PROJECT_ID: project.project_id,
        ENV_WEAVIATE_HOST: weaviate_host,
        ENV_WEAVIATE_HTTP_PORT: str(weaviate_http_port),
        ENV_WEAVIATE_GRPC_PORT: str(weaviate_grpc_port),
        ENV_CONCEPTS_DIR: str(project.concepts_dir),
        ENV_STORIES_DIR: str(project.stories_dir),
    }
    return McpServerSpec(
        command=command,
        args=args,
        cwd=str(project.project_root),
        env=env,
    )


def load_runtime_binding_from_env(
    env: Mapping[str, str] | None = None,
    *,
    cwd: str | Path | None = None,
) -> RuntimeBinding:
    """Load :class:`RuntimeBinding` exclusively from the registered env map.

    Missing, empty, or wrongly typed values stop fail-closed. ``cwd`` is used
    only as the project-root containment boundary — never to invent host/port.
    """
    source = dict(os.environ if env is None else env)

    project_id = _require_nonempty_str(source, ENV_PROJECT_ID)
    host = _require_nonempty_str(source, ENV_WEAVIATE_HOST)
    http_port = _require_positive_int(source, ENV_WEAVIATE_HTTP_PORT)
    grpc_port = _require_positive_int(source, ENV_WEAVIATE_GRPC_PORT)

    if cwd is None:
        cwd = Path.cwd()
    root = Path(cwd)
    concepts = source.get(ENV_CONCEPTS_DIR)
    stories = source.get(ENV_STORIES_DIR)
    try:
        project = bind_project(
            root,
            project_id=project_id,
            concepts_dir=concepts if concepts else None,
            stories_dir=stories if stories else None,
        )
    except ProjectBindingError as exc:
        raise RuntimeBindingError(str(exc)) from exc

    if project.project_id != project_id:
        raise RuntimeBindingError(
            f"Bound project_id {project.project_id!r} diverges from env "
            f"{ENV_PROJECT_ID}={project_id!r} (fail-closed)."
        )

    return RuntimeBinding(
        project_id=project_id,
        weaviate_host=host,
        weaviate_http_port=http_port,
        weaviate_grpc_port=grpc_port,
        project=project,
    )


def resolve_tool_project_id(
    binding: RuntimeBinding,
    tool_project_id: str | None,
) -> str:
    """Apply the MCP project_id tool-parameter rule (AG3-174 AC 11).

    * Omitted / empty → bound project_id.
    * Equal to bound → accepted.
    * Different → rejected (no cross-project execution).
    """
    if tool_project_id is None or tool_project_id == "":
        return binding.project_id
    if not isinstance(tool_project_id, str):
        raise RuntimeBindingError(
            f"tool project_id must be a string, got {type(tool_project_id).__name__}."
        )
    if tool_project_id != binding.project_id:
        raise RuntimeBindingError(
            f"tool project_id {tool_project_id!r} does not match bound "
            f"project_id {binding.project_id!r}; cross-project calls are "
            "rejected (fail-closed, FK-13 §13.4.1/§13.9.5)."
        )
    return binding.project_id


def _require_nonempty_str(env: Mapping[str, str], key: str) -> str:
    if key not in env:
        raise RuntimeBindingError(
            f"Runtime binding missing required env {key!r} (fail-closed, no default)."
        )
    value = env[key]
    if not isinstance(value, str) or not value.strip():
        raise RuntimeBindingError(
            f"Runtime binding env {key!r} must be a non-empty string (fail-closed)."
        )
    return value.strip()


def _require_positive_int(env: Mapping[str, str], key: str) -> int:
    raw = _require_nonempty_str(env, key)
    # Reject signed / non-digit forms; only plain positive decimal digits.
    if not raw.isdigit():
        raise RuntimeBindingError(
            f"Runtime binding env {key!r} must be a positive integer string, "
            f"got {raw!r} (fail-closed)."
        )
    value = int(raw)
    if value <= 0:
        raise RuntimeBindingError(
            f"Runtime binding env {key!r} must be > 0, got {value} (fail-closed)."
        )
    return value


__all__ = [
    "ENV_CONCEPTS_DIR",
    "ENV_PROJECT_ID",
    "ENV_STORIES_DIR",
    "ENV_WEAVIATE_GRPC_PORT",
    "ENV_WEAVIATE_HOST",
    "ENV_WEAVIATE_HTTP_PORT",
    "McpServerSpec",
    "RuntimeBinding",
    "RuntimeBindingError",
    "build_mcp_server_spec",
    "load_runtime_binding_from_env",
    "resolve_tool_project_id",
]
