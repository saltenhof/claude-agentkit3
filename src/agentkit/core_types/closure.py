"""ClosureVerdict und MergePolicy — Closure-Phase-Enums.

Source of truth:
- ClosureVerdict: ``concept/_meta/bc-cut-decisions.md`` §BC 8 Closure-Top
  (Z. 558-560, StrEnum COMPLETED/ESCALATED).
- MergePolicy: FK-29 §29.1.5 — concept/technical-design/29_closure_sequence.md
  (Z. 351-358, ff_only/no_ff).

Aktive Verwendung dieser Enums in `closure/`-Modulen ist Aufgabe
spaeter Stories (THEME-005 ff.).
"""

from __future__ import annotations

from enum import StrEnum


class ClosureVerdict(StrEnum):
    """Closure-Endentscheidung pro bc-cut-decisions §BC 8.

    Attributes:
        COMPLETED: Closure erfolgreich abgeschlossen (Merge + Push + Cleanup).
        ESCALATED: Closure eskaliert (Merge-Konflikt, Integrity-Fail,
            manuelle Intervention noetig).
    """

    COMPLETED = "COMPLETED"
    ESCALATED = "ESCALATED"


class MergePolicy(StrEnum):
    """Erlaubte Closure-Merge-Policies pro FK-29 §29.1.5.

    Attributes:
        FF_ONLY: Fast-Forward-Merge ohne Merge-Commit (Default).
        NO_FF: Merge mit explizitem Merge-Commit (offizieller Fallback).
    """

    FF_ONLY = "ff_only"
    NO_FF = "no_ff"
