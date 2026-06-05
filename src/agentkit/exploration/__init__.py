"""Exploration bounded context (BC 5, exploration-and-design).

Owner of the exploration phase (FK-23 / FK-25). Per the PO decision 2026-06-05
("Option Y") AG3-045 delivers the deterministic plumbing -- the phase entry
point (:class:`ExplorationPhaseHandler`), the change-frame **schema**
(:class:`ChangeFrame`), the consume/validate path and the producer registration
-- but NOT the content drafting. The real change-frame is produced by the
spawned exploration worker (AG3-055, BC ``agent-skills``); the handler
consumes / validates it via injected boundary ports
(:mod:`agentkit.exploration.ports`). The three-stage review (AG3-046) and
mandate classification (AG3-047) extend this package.

The phase handler is registered on the PipelineEngine's
``PhaseHandlerRegistry`` by the composition-root wiring (AG3-054); the producer
init-hook :func:`register_exploration_producers` is wired into
``build_producer_registry`` so the ENTWURF artifact read/write path works in
production.
"""

from __future__ import annotations

from agentkit.exploration.change_frame import ChangeFrame
from agentkit.exploration.phase import ExplorationConfig, ExplorationPhaseHandler
from agentkit.exploration.ports import ChangeFrameReader, RunScopeResolver
from agentkit.exploration.register import register_exploration_producers

__all__ = [
    "ChangeFrame",
    "ChangeFrameReader",
    "ExplorationConfig",
    "ExplorationPhaseHandler",
    "RunScopeResolver",
    "register_exploration_producers",
]
