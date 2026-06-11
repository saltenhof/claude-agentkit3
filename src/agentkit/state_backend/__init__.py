"""Driver layer of state persistence.

Modules:
    store   -- compatibility facade selects the driver via config
    paths   -- filesystem path constants
    scope   -- persistence identity (StateScope/RuntimeStateScope)
    config  -- StateBackendKind, load_state_backend_config
    postgres_store, sqlite_store -- concrete drivers

Import directly from the matching submodule, not from this package.
"""

from __future__ import annotations
