"""Minimal project binding for the FK-13 retrieval engine (Review 174-P0-4).

A typed, authoritative project identity for the vectordb ingest/MCP paths:

- ``project_root`` is the authoritative root; every write path must be contained
  inside it (no escape via ``..`` / absolute paths / symlinks pointing out).
- ``project_id`` is the multi-tenant discriminator (FK-13 §13.3.1) read from the
  project configuration contract.
- ``cwd`` is the project-local working / containment boundary.
- ``endpoint`` (Weaviate HTTP/gRPC) is a configuration VALUE, never a guessed
  default.

There is NO global identity registry, no registry-CAS, no localhost default.
The binding is constructed explicitly and validated fail-closed; an unbound or
ambiguous binding is an ERROR, not a best-effort guess.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


class ProjectBindingError(ValueError):
    """Raised when a project binding is missing, ambiguous or unsafe."""


@dataclass(frozen=True)
class ProjectBinding:
    """Authoritative project identity for the retrieval engine.

    Attributes:
        project_id: Non-empty multi-tenant discriminator (FK-13 §13.3.1).
        project_root: Authoritative filesystem root; all write paths must be
            contained inside it.
        concepts_dir: Configured concept corpus root (FK-13 §13.9: "konfiguriertes
            concepts_dir ist massgeblich").
        stories_dir: Story corpus root (``stories/*/story.md`` etc.).
        weaviate_http_endpoint: Weaviate HTTP endpoint URL (config value, no default).
        weaviate_grpc_endpoint: Weaviate gRPC endpoint (host:port), optional.
    """

    project_id: str
    project_root: Path
    concepts_dir: Path
    stories_dir: Path
    weaviate_http_endpoint: str
    weaviate_grpc_endpoint: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.project_id, str) or not self.project_id.strip():
            raise ProjectBindingError(
                "project_id is missing/empty; the binding is authoritative "
                "(no default, fail-closed)."
            )
        if not isinstance(self.project_root, Path):
            raise ProjectBindingError("project_root must be a Path (typed binding).")
        if not isinstance(self.weaviate_http_endpoint, str) or not self.weaviate_http_endpoint.strip():
            raise ProjectBindingError(
                "weaviate_http_endpoint is missing/empty; the endpoint is a "
                "configuration value (no localhost default, fail-closed)."
            )
        # The endpoint must never be a synthesised localhost default.
        ep = self.weaviate_http_endpoint.strip()
        if ep in {"http://localhost:8080", "http://127.0.0.1:8080"}:
            raise ProjectBindingError(
                f"weaviate_http_endpoint {ep!r} is a forbidden localhost default; "
                "the endpoint must come from explicit configuration."
            )

    def resolve_within_root(self, candidate: Path) -> Path:
        """Resolve ``candidate`` and prove it is contained under project_root.

        Raises:
            ProjectBindingError: If the resolved path escapes ``project_root``
                (path traversal / absolute escape).
        """
        root = self.project_root.resolve()
        resolved = candidate if candidate.is_absolute() else (self.project_root / candidate)
        resolved = resolved.resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ProjectBindingError(
                f"path {candidate} resolves outside project_root {self.project_root} "
                "(containment violation, fail-closed)."
            ) from exc
        return resolved

    def assert_writable_within_root(self, paths: Sequence[Path]) -> None:
        """Assert every path in ``paths`` is contained under project_root."""
        for path in paths:
            self.resolve_within_root(path)


__all__ = ["ProjectBinding", "ProjectBindingError"]
