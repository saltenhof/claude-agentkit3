"""Setup phase -- first phase in the AgentKit pipeline.

Public API
----------
.. autoclass:: SetupPhaseHandler
.. autoclass:: SetupConfig
.. autoclass:: PreflightResult
.. autofunction:: build_story_context
"""

from __future__ import annotations

from agentkit.pipeline.phases.setup.context_builder import build_story_context
from agentkit.pipeline.phases.setup.phase import SetupConfig, SetupPhaseHandler
from agentkit.pipeline.phases.setup.preflight import PreflightResult

__all__ = [
    "PreflightResult",
    "SetupConfig",
    "SetupPhaseHandler",
    "build_story_context",
]
