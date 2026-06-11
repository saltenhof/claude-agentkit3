"""PolicyVerdict — final decision of the policy engine.

Source of truth: FK-27 §27.7.2 — concept/technical-design/27_verify_pipeline_closure_orchestration.md

`PolicyEngine.decide` may return exclusively `PASS` or `FAIL`; no other
intermediate values are permitted. The LLM-check-status counterpart at
the envelope boundary (AG3-022, FK-71) is a separate value list that is
not relevant here.
"""

from __future__ import annotations

from enum import StrEnum


class PolicyVerdict(StrEnum):
    """Final decision of the policy engine per FK-27 §27.7.2.

    Attributes:
        PASS: Aggregation passed all checks.
        FAIL: Aggregation breached BLOCKING or MAJOR thresholds.
    """

    PASS = "PASS"
    FAIL = "FAIL"
