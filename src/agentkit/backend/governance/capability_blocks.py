"""Fail-closed verdict builders for principal-capability enforcement."""

from __future__ import annotations

from agentkit.backend.governance.protocols import GuardVerdict, ViolationType

CAPABILITY_DENIED_REASON = "capability denied"


def binding_invalid_block(reason: str | None) -> GuardVerdict:
    """Return the deterministic block for an inconsistent story binding."""
    return GuardVerdict.block(
        "principal_capability",
        ViolationType.UNAUTHORIZED_OPERATION,
        f"operating_mode binding_invalid: {reason or 'inconsistent_story_binding'}",
        detail={
            "capability_rule_id": "FK-55-55.10.1/55.10.4",
            "operating_mode": "binding_invalid",
            "block_reason": reason,
        },
    )


def capability_block(verdict: object) -> GuardVerdict:
    """Translate a capability deny verdict into a blocking verdict."""
    return GuardVerdict.block(
        "principal_capability",
        ViolationType.UNAUTHORIZED_OPERATION,
        getattr(verdict, "reason", CAPABILITY_DENIED_REASON),
        detail={"capability_rule_id": getattr(verdict, "rule_id", None)},
    )


def capability_fault_block(exc: Exception) -> GuardVerdict:
    """Map a capability-layer fault to a visible fail-closed block."""
    return GuardVerdict.block(
        "principal_capability",
        ViolationType.UNAUTHORIZED_OPERATION,
        f"capability evaluation failed fail-closed: {exc}",
        detail={
            "capability_rule_id": "FK-55-55.10.5",
            "fault_class": type(exc).__name__,
        },
    )


__all__ = [
    "CAPABILITY_DENIED_REASON",
    "binding_invalid_block",
    "capability_block",
    "capability_fault_block",
]
