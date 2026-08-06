"""Validation shared by all control-plane operation claim write paths."""

from __future__ import annotations

from typing import Any


def assert_complete_claim_sender(row: dict[str, Any]) -> None:
    """Reject a claimed operation without its recovery and fencing sender."""

    if row.get("status") != "claimed":
        raise ValueError("control-plane operation claims require status='claimed'")
    if not str(row.get("claimed_by") or "").strip() or row.get("claimed_at") is None:
        raise ValueError("control-plane operation claims require an owner stamp")
    epoch = row.get("operation_epoch")
    if not isinstance(epoch, int) or isinstance(epoch, bool) or epoch < 1:
        raise ValueError("control-plane operation claims require operation_epoch >= 1")
    if not str(row.get("backend_instance_id") or "").strip():
        raise ValueError("control-plane operation claims require backend_instance_id")
    incarnation = row.get("instance_incarnation")
    if (
        not isinstance(incarnation, int)
        or isinstance(incarnation, bool)
        or incarnation < 1
    ):
        raise ValueError(
            "control-plane operation claims require instance_incarnation >= 1",
        )
