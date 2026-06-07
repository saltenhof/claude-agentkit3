"""Handover submodule (FK-26 §26.7).

Owns :class:`HandoverPackager` and the typed ``handover.json`` schema
(:class:`HandoverData`, :class:`ACStatus`) — the worker -> QA-subflow handover
whose field-set matches the AG3-042 Layer-1 ``artifact.handover`` validator.
"""

from __future__ import annotations

from agentkit.implementation.handover.packager import (
    HANDOVER_FILENAME,
    ACStatus,
    DriftLogEntry,
    HandoverData,
    HandoverIncrement,
    HandoverPackager,
)

__all__ = [
    "HANDOVER_FILENAME",
    "ACStatus",
    "DriftLogEntry",
    "HandoverData",
    "HandoverIncrement",
    "HandoverPackager",
]
