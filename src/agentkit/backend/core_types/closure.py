"""ClosureVerdict and MergePolicy — closure-phase enums.

Source of truth:
- ClosureVerdict: ``concept/_meta/bc-cut-decisions.md`` §BC 8 Closure-Top
  (lines 558-560, StrEnum COMPLETED/ESCALATED).
- MergePolicy: FK-29 §29.1.5 — concept/technical-design/29_closure_sequence.md
  (lines 351-358, ff_only/no_ff).

Active use of these enums in `closure/` modules is the task of later stories
(THEME-005 ff.).
"""

from __future__ import annotations

from enum import StrEnum


class ClosureVerdict(StrEnum):
    """Final closure decision per bc-cut-decisions §BC 8.

    Attributes:
        COMPLETED: Closure completed successfully (merge + push + cleanup).
        ESCALATED: Closure escalated (merge conflict, integrity fail,
            manual intervention required).
    """

    COMPLETED = "COMPLETED"
    ESCALATED = "ESCALATED"


class MergePolicy(StrEnum):
    """Permitted closure merge policies per FK-29 §29.1.5.

    Attributes:
        FF_ONLY: Fast-forward merge without a merge commit (default).
        NO_FF: Merge with an explicit merge commit (official fallback).
    """

    FF_ONLY = "ff_only"
    NO_FF = "no_ff"
