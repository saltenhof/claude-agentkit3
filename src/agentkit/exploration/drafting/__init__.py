"""ExplorationDrafting -- the worker-driven change-frame producer (BC 5, FK-23 §23.3).

bloodgroup-A sub of the ``exploration-and-design`` BC
(``architecture-conformance.group.exploration_drafting``). Per the PO decision
2026-06-05 ("Option Y") AG3-045 delivers the deterministic plumbing (schema,
handler, gate, persistence) but deliberately produces NO content; THIS sub is the
real FK-23 §23.3 drafting: it materializes ``worker-exploration.md``
(prompt-runtime, FK-44), spawns the exploration worker over the EXISTING AG3-044
worker-spawn path (``SpawnKind.WORKER``), and turns the worker's seven-part
output (FK-23 §23.3.2) into a validated :class:`~agentkit.exploration.change_frame.ChangeFrame`
persisted at the AG3-045 change-frame path.

The bloodgroup-A core performs NO direct LLM / spawn / filesystem I/O: the
worker execution is injected via the :class:`ExplorationWorkerRunner` boundary
port (the sanctioned MOCKS-exception seam) and the persistence via the AG3-045
``ChangeFrameWriter`` + ``ArtifactManager`` ports. The productive adapter
(real worker spawn + materialized prompt) and the record-replay test adapter
both satisfy the same port; the orchestration is identical (ARCH-22 / ARCH-31).
"""

from __future__ import annotations

from agentkit.exploration.drafting.drafting import (
    DraftingError,
    ExplorationDrafting,
    ExplorationDraftRequest,
    ExplorationDraftResult,
)
from agentkit.exploration.drafting.ports import (
    ExplorationWorkerResult,
    ExplorationWorkerRunner,
)

__all__ = [
    "DraftingError",
    "ExplorationDraftRequest",
    "ExplorationDraftResult",
    "ExplorationDrafting",
    "ExplorationWorkerResult",
    "ExplorationWorkerRunner",
]
