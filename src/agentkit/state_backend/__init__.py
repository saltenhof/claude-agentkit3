"""Driver-Schicht der State-Persistenz.

Module:
    store   -- Compatibility-Facade waehlt Driver via Config
    paths   -- Filesystem-Pfad-Konstanten
    scope   -- Persistenz-Identitaet (StateScope/RuntimeStateScope)
    config  -- StateBackendKind, load_state_backend_config
    postgres_store, sqlite_store -- konkrete Driver

Importiere direkt aus dem passenden Submodul, nicht aus diesem Paket.
"""

from __future__ import annotations
