"""PolicyVerdict — Endentscheidung der Policy-Engine.

Source of truth: FK-27 §27.7.2 — concept/technical-design/27_verify_pipeline_closure_orchestration.md

`PolicyEngine.decide` darf nur einen dieser beiden Werte zurueckgeben.
`PASS_WITH_WARNINGS` ist explizit kein Verdict (Codex-Befund: alter
v2-Wert, in v3 entfernt). Das LLM-Check-Status-Pendant
`PASS_WITH_CONCERNS` lebt im Envelope-Layer (AG3-022) und wird dort
auf `EnvelopeStatus.WARN` gemappt.
"""

from __future__ import annotations

from enum import StrEnum


class PolicyVerdict(StrEnum):
    """Endentscheidung der Policy-Engine pro FK-27 §27.7.2.

    Attributes:
        PASS: Aggregation passierte alle Pruefungen.
        FAIL: Aggregation hat Blocking- oder MAJOR-Schwellen gerissen.
    """

    PASS = "PASS"
    FAIL = "FAIL"
