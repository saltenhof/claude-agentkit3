"""QaContext — verify-system Aufruf-Kontext.

Source of truth: ``concept/_meta/bc-cut-decisions.md`` §QaContext-Werte (Z. 84-95).

Beschreibt, in welcher Phase und welcher QA-Runde der Subflow gerade
laeuft. Ersetzt den v2-Namen ``VerifyContext`` (nur zwei Werte) durch
ein viergliedriges StrEnum.
"""

from __future__ import annotations

from enum import StrEnum


class QaContext(StrEnum):
    """Aufruf-Kontext des Verify-System-QA-Subflows.

    Attributes:
        IMPLEMENTATION_INITIAL: Erster QA-Lauf in der Implementation-Phase.
        IMPLEMENTATION_REMEDIATION: Re-QA-Lauf nach Remediation in der
            Implementation-Phase.
        EXPLORATION_INITIAL: Erster QA-Lauf am Exploration-Exit-Gate.
        EXPLORATION_REMEDIATION: Re-QA-Lauf nach Remediation in der
            Exploration-Phase.
    """

    IMPLEMENTATION_INITIAL = "IMPLEMENTATION_INITIAL"
    IMPLEMENTATION_REMEDIATION = "IMPLEMENTATION_REMEDIATION"
    EXPLORATION_INITIAL = "EXPLORATION_INITIAL"
    EXPLORATION_REMEDIATION = "EXPLORATION_REMEDIATION"
