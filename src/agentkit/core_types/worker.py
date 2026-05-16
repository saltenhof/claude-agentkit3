"""BlockingCategory und SpawnReason — Worker-Lifecycle-Enums.

Source of truth:
- BlockingCategory: FK-26 §26.8.2 Glossar Z. 42-53
  (concept/technical-design/26_implementation_runtime_worker_loop.md).
  Vier upper-case Werte; Pflichtfeld im worker-manifest bei status BLOCKED.
- SpawnReason: ``concept/_meta/bc-cut-decisions.md`` §BC 6 Z. 441-450
  plus FK-26 §26.2 (Worker-Variants). Drei lower-case Wire-Werte gem.
  AG3-021 §2.1.1.1.
"""

from __future__ import annotations

from enum import StrEnum


class BlockingCategory(StrEnum):
    """Klassifikation eines BLOCKED-Worker-Exits pro FK-26 §26.8.2.

    Attributes:
        POLICY_CONFLICT: Unaufloesbarer Widerspruch zwischen Policies.
        ENVIRONMENTAL: Fehlende externe Voraussetzung
            (Tool, Service, Datenquelle).
        FIXABLE_LOCAL: Lokaler Fehler ausserhalb des Worker-Scopes.
        FIXABLE_CODE: Code-Fehler ausserhalb des Worker-Scopes.
    """

    POLICY_CONFLICT = "POLICY_CONFLICT"
    ENVIRONMENTAL = "ENVIRONMENTAL"
    FIXABLE_LOCAL = "FIXABLE_LOCAL"
    FIXABLE_CODE = "FIXABLE_CODE"


class SpawnReason(StrEnum):
    """Grund des Worker-Starts pro FK-26 §26.2 + bc-cut §BC 6.

    Konzept-Drift-Notiz: FK-26 §26.8.2 Glossar listet die Werte in
    UPPER_SNAKE_CASE als Member-Namen; AG3-021 §2.1.1.1 hat die
    Wire-Strings normativ auf lowercase festgelegt (konsistent mit dem
    bestehenden Code in `workers/types.py`). Member-Namen bleiben
    UPPER_SNAKE_CASE.

    Attributes:
        INITIAL: Erstaufruf einer Story-Phase.
        PAUSED_RETRY: Re-Spawn nach PAUSED-Zustand (paused_reason
            faellt mit dem Retry weg).
        REMEDIATION: Re-Spawn nach QA-FAIL fuer Remediation-Runde.
    """

    INITIAL = "initial"
    PAUSED_RETRY = "paused_retry"
    REMEDIATION = "remediation"
