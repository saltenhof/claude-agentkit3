"""Closure phase -- final phase that closes a story.

Public API
----------
.. autoclass:: ClosurePhaseHandler
.. autoclass:: ClosureConfig
.. autoclass:: ExecutionReport
.. autofunction:: write_execution_report
"""

from __future__ import annotations

from agentkit.pipeline.phases.closure.execution_report import (
    ExecutionReport,
    write_execution_report,
)
from agentkit.pipeline.phases.closure.phase import (
    ClosureConfig,
    ClosurePhaseHandler,
)

__all__ = [
    "ClosureConfig",
    "ClosurePhaseHandler",
    "ExecutionReport",
    "write_execution_report",
]
