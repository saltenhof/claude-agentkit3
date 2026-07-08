"""Runtime scope resolution facade compatibility exports."""

from __future__ import annotations

from agentkit.backend.state_backend.runtime_scope_resolver import (
    resolve_runtime_scope as resolve_runtime_scope,
)

__all__ = [
    "resolve_runtime_scope",
]
