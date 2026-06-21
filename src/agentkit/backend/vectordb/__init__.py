"""App-layer VectorDB readiness shim (FK-21 §21.11.4).

Canonical FK module path ``agentkit.backend.vectordb.wait_for_weaviate``: the
"ready / not ready" business rule lives here, NOT in ``integrations/``. The
shim consumes the thin Weaviate adapter and maps readiness to a process exit
code (0 ready / 1 not, fail-closed).
"""

from __future__ import annotations

__all__: list[str] = []
