"""QaContext — verify-system call context.

Source of truth: ``concept/_meta/bc-cut-decisions.md`` §QaContext values (lines 84-95).

Describes in which phase and which QA round the subflow is currently
running. Replaces the v2 name ``VerifyContext`` (only two values) with a
four-member StrEnum.
"""

from __future__ import annotations

from enum import StrEnum


class QaContext(StrEnum):
    """Call context of the verify-system QA subflow.

    Attributes:
        IMPLEMENTATION_INITIAL: First QA run in the implementation phase.
        IMPLEMENTATION_REMEDIATION: Re-QA run after remediation in the
            implementation phase.
        EXPLORATION_INITIAL: First QA run at the exploration exit-gate.
        EXPLORATION_REMEDIATION: Re-QA run after remediation in the
            exploration phase.
    """

    IMPLEMENTATION_INITIAL = "IMPLEMENTATION_INITIAL"
    IMPLEMENTATION_REMEDIATION = "IMPLEMENTATION_REMEDIATION"
    EXPLORATION_INITIAL = "EXPLORATION_INITIAL"
    EXPLORATION_REMEDIATION = "EXPLORATION_REMEDIATION"
