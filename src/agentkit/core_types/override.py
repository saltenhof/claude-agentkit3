"""Override type enum for manual workflow interventions."""

from __future__ import annotations

from enum import StrEnum


class OverrideType(StrEnum):
    """Closed set of supported override record types.

    Wire values are the lowercase strings defined by FK-20 §20.1.5.
    """

    SKIP_NODE = "skip_node"
    FORCE_GATE_PASS = "force_gate_pass"
    FORCE_GATE_FAIL = "force_gate_fail"
    JUMP_TO = "jump_to"
    TRUNCATE_FLOW = "truncate_flow"
    FREEZE_RETRIES = "freeze_retries"
