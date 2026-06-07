"""Worker-manifest submodule (FK-26 §26.8).

Owns :class:`WorkerManifest`, the typed worker end-of-implementation
declaration with the three status values and the fail-closed BLOCKED
required-field validator.
"""

from __future__ import annotations

from agentkit.implementation.manifest.manifest import (
    AttemptedRemediation,
    WorkerManifest,
    WorkerManifestStatus,
)

__all__ = [
    "AttemptedRemediation",
    "WorkerManifest",
    "WorkerManifestStatus",
]
