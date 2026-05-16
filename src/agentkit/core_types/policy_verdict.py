"""PolicyVerdict — Endentscheidung der Policy-Engine.

Source of truth: FK-27 §27.7.2 — concept/technical-design/27_verify_pipeline_closure_orchestration.md

`PolicyEngine.decide` darf ausschliesslich `PASS` oder `FAIL` zurueck-
geben; weitere Zwischenwerte sind nicht zulaessig. Das LLM-Check-
Status-Pendant am Envelope-Rand (AG3-022, FK-71) ist eine
eigenstaendige Werteliste, die hier nicht relevant ist.
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
