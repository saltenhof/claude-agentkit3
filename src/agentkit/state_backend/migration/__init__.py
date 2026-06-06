"""Schema-migration module (FK-62 §62.4, FK-18 §18.9a).

Idempotent, versioned DDL migrations with a ``schema_versions`` cursor table.
The canonical column/PK truth lives in the schema owners
(``postgres_schema.sql`` / ``sqlite_store``); this module provides the
re-runnable migration runner and the per-version DDL artifacts.
"""

from __future__ import annotations

from agentkit.state_backend.migration.migration_runner import MigrationRunner

__all__ = ["MigrationRunner"]
