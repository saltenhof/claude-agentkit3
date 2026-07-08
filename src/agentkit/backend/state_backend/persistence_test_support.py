"""Test-only support for resetting cached state backend selection."""

from __future__ import annotations

import sys

from agentkit.backend.state_backend.state_backend_connection_manager import (
    _backend_module,
)


def reset_backend_cache_for_tests() -> None:
    """Clear cached backend selection for test-time environment switching."""
    _backend_module.cache_clear()
    postgres_store = sys.modules.get("agentkit.backend.state_backend.postgres_store")
    if postgres_store is not None:
        reset_schema_cache = getattr(
            postgres_store,
            "_reset_schema_bootstrap_cache_for_tests",
            None,
        )
        if callable(reset_schema_cache):
            reset_schema_cache()
    schema_bootstrap = sys.modules.get(
        "agentkit.backend.state_backend.schema_bootstrap",
    )
    if schema_bootstrap is not None:
        reset_versioned_schema_cache = getattr(
            schema_bootstrap,
            "_reset_versioned_schema_cache_for_tests",
            None,
        )
        if callable(reset_versioned_schema_cache):
            reset_versioned_schema_cache()


__all__ = ["reset_backend_cache_for_tests"]
