"""ExplorationGateStatus — status of the exploration exit-gate.

Source of truth: FK-23 §23.5.0 — concept/technical-design/23_modusermittlung_exploration_change_frame.md

Wire values are lowercase (concept code example `PENDING = "pending"`).
"""

from __future__ import annotations

from enum import StrEnum


class ExplorationGateStatus(StrEnum):
    """Status of the three-stage exploration exit-gate.

    Attributes:
        PENDING: Gate not yet fully passed, or an intermediate stage.
        APPROVED: All stages passed — ready for implementation.
        REJECTED: Gate finally rejected; escalation.
    """

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
