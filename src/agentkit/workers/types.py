"""Worker type definitions for spawn and coordination.

Defines typed enumerations used in worker spawn contracts
and coordination protocols.
"""

from __future__ import annotations

from enum import StrEnum


class SpawnReason(StrEnum):
    """Reason why a worker is being spawned.

    Used in the worker spawn contract to communicate the context
    of the spawn to the worker agent. Determines which context
    items are required and how the prompt is composed.

    Attributes:
        INITIAL: First spawn of the worker for this story phase.
        PAUSED_RETRY: Worker is re-spawned after a PAUSED state
            (e.g. awaiting design review or human approval).
        REMEDIATION: Worker is re-spawned to address findings
            from a previous verify cycle (feedback.json present).
    """

    INITIAL = "initial"
    PAUSED_RETRY = "paused_retry"
    REMEDIATION = "remediation"
