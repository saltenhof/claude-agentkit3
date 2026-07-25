"""Authoritative MCP runtime binding as SSOT (Review 174-P0-4, PO decision D2).

A single typed ``McpServerSpec`` / ``RuntimeBinding`` is the source of truth for
the started MCP process and is consumed UNCHANGED by AG3-175 (harness
registration). ``PROJECT_ID`` and the Weaviate HTTP/gRPC endpoint come for the
MCP process **exclusively** from the registered ``env``; ``cwd`` is the working
/ containment boundary, NOT a second configuration source.

Key rules (D2):
- No localhost / default endpoint fallback. The env is the sole authority.
- Missing, empty or wrongly-typed binding values stop the server fail-closed.
- An omitted tool parameter ``project_id`` is set to the bound project id.
- A divergent tool-supplied ``project_id`` is REJECTED (never cross-project) --
  also for ``story_list_sources``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping


class RuntimeBindingError(ValueError):
    """Raised when the MCP runtime binding is incomplete or unsafe."""


#: Environment keys that MUST be present and non-empty (D2: env is sole authority).
#: Both Weaviate endpoints (HTTP + gRPC) are mandatory and strictly validated;
#: neither is ever a synthesised localhost default.
REQUIRED_ENV_KEYS: tuple[str, ...] = (
    "PROJECT_ID",
    "WEAVIATE_HTTP_ENDPOINT",
    "WEAVIATE_GRPC_ENDPOINT",
)


def _required(mapping: Mapping[str, str], key: str) -> str:
    if key not in mapping:
        raise RuntimeBindingError(
            f"required env key {key!r} is missing from the runtime binding "
            "(env is the sole authority, fail-closed)."
        )
    value = mapping[key]
    if not isinstance(value, str) or not value.strip():
        raise RuntimeBindingError(
            f"required env key {key!r} is empty/non-string in the runtime binding "
            "(no default fallback, fail-closed)."
        )
    return value.strip()


def _reject_localhost(endpoint: str, *, label: str) -> None:
    """Reject synthesised localhost defaults for either endpoint (D2)."""
    forbidden = {
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "localhost:50051",
        "127.0.0.1:50051",
    }
    if endpoint in forbidden:
        raise RuntimeBindingError(
            f"{label} {endpoint!r} is a forbidden localhost default; the endpoint "
            "must be explicitly configured (D2)."
        )


@dataclass(frozen=True)
class McpServerSpec:
    """Single source of truth for the started MCP process (consumed by AG3-175).

    Attributes:
        project_id: Bound project discriminator (from ``PROJECT_ID`` env).
        weaviate_http_endpoint: Weaviate HTTP endpoint (from env, no default).
        weaviate_grpc_endpoint: Weaviate gRPC endpoint (from env, no default).
        command: Executable command for the MCP server.
        args: Argument vector for the MCP server.
        cwd: Working / containment boundary (NOT a second config source).
        env: Full registered environment (the sole authority for endpoint/id).
    """

    project_id: str
    weaviate_http_endpoint: str
    weaviate_grpc_endpoint: str
    command: str
    args: tuple[str, ...]
    cwd: str
    env: tuple[tuple[str, str], ...]

    def env_dict(self) -> dict[str, str]:
        """Return the registered env as a dict (deterministic order preserved)."""
        return dict(self.env)


@dataclass(frozen=True)
class RuntimeBinding:
    """Validated MCP runtime binding (FK-13 §13.4.3, Review 174-P0-4, D2).

    Built from an explicit ``env`` mapping; every required key is present,
    non-empty and string-typed, and the endpoint is never a synthesised
    localhost default.
    """

    spec: McpServerSpec

    @property
    def project_id(self) -> str:
        return self.spec.project_id

    @property
    def weaviate_http_endpoint(self) -> str:
        return self.spec.weaviate_http_endpoint

    @property
    def weaviate_grpc_endpoint(self) -> str:
        return self.spec.weaviate_grpc_endpoint

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str],
        *,
        command: str,
        args: tuple[str, ...],
        cwd: str,
    ) -> RuntimeBinding:
        """Build a validated binding from the registered env (sole authority).

        Args:
            env: The registered process environment mapping.
            command: MCP server executable.
            args: MCP server argument vector.
            cwd: Working / containment boundary.

        Raises:
            RuntimeBindingError: If any required value is missing/empty/wrong-
                typed or the endpoint is a forbidden localhost default.
        """
        for key in REQUIRED_ENV_KEYS:
            _required(env, key)
        project_id = _required(env, "PROJECT_ID")
        http_endpoint = _required(env, "WEAVIATE_HTTP_ENDPOINT")
        _reject_localhost(http_endpoint, label="WEAVIATE_HTTP_ENDPOINT")
        grpc_endpoint = _required(env, "WEAVIATE_GRPC_ENDPOINT")
        _reject_localhost(grpc_endpoint, label="WEAVIATE_GRPC_ENDPOINT")
        if not cwd.strip():
            raise RuntimeBindingError(
                "cwd is empty; it is the containment boundary (fail-closed)."
            )
        env_items = tuple((k, str(v)) for k, v in env.items())
        spec = McpServerSpec(
            project_id=project_id,
            weaviate_http_endpoint=http_endpoint,
            weaviate_grpc_endpoint=grpc_endpoint.strip(),
            command=command,
            args=args,
            cwd=cwd,
            env=env_items,
        )
        return cls(spec=spec)

    def resolve_project_id(self, supplied: str | None) -> str:
        """Resolve a tool-supplied ``project_id`` against the bound authority.

        - ``None`` / empty -> bound project id (omitted parameter default).
        - Equal to bound id -> bound id.
        - Divergent -> :class:`RuntimeBindingError` (REJECTED, never cross-project).

        Applies to every tool, including ``story_list_sources`` (D2).
        """
        if supplied is None or supplied.strip() == "":
            return self.project_id
        if supplied.strip() == self.project_id:
            return self.project_id
        raise RuntimeBindingError(
            f"tool-supplied project_id {supplied!r} diverges from the bound "
            f"{self.project_id!r}; cross-project access is rejected (D2)."
        )


__all__ = [
    "McpServerSpec",
    "REQUIRED_ENV_KEYS",
    "RuntimeBinding",
    "RuntimeBindingError",
]
