"""Byte-stable rendering for concept decision-record findings."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .decision_record_models import DecisionRecordResult


def render_decision_record_result(result: DecisionRecordResult) -> str:
    """Render byte-stable gate output with a deterministic summary footer."""
    lines = [
        f"[{item.severity}] {item.code} {item.path}:{item.line} - {item.message}"
        for item in result.findings
    ]
    status = "PASS" if result.ok else "ERROR"
    lines.append(f"[{status}] concept-decision-record: {len(result.findings)} error(s)")
    return "\n".join(lines)
