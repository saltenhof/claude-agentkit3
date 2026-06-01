"""FailureCategory und IncidentStatus — Failure-Corpus-Klassifikation.

Source of truth:
- FailureCategory: FK-41 §41.4.1 — concept/technical-design/41_failure_corpus_pattern_promotion_check_factory.md
  (12 Werte). Abgeglichen mit bc-cut-decisions §BC 13.
- IncidentStatus: FK-41 §41.3.1 + Glossar `exported_terms.incident-status.values`
  (4 Werte: observed/promoted/closed_one_off/archived). AG3-028 KONFLIKT-1
  (User-Entscheidung 2026-06-01) ersetzt den frueheren Sammel-Enum
  ``PromotionStatus`` (ein Enum fuer drei Entitaeten) durch drei
  entitaets-scoped Lifecycle-Enums. ``IncidentStatus`` ist der einzige Enum
  mit funktionalem Producer (``record_incident``/``fc_incidents.incident_status``)
  und wird daher in dieser Story materialisiert; ``PatternStatus``/``CheckStatus``
  folgen mit ihren Producern (PatternPromotion/CheckFactory) in Folge-Stories
  (ZERO DEBT: kein toter Code).
"""

from __future__ import annotations

from enum import StrEnum


class FailureCategory(StrEnum):
    """Failure-Kategorie pro FK-41 §41.4.1 (12 Werte).

    Die untenstehende Liste ist abschliessend; aeltere, repo-historisch
    kursierende Werte sind nicht Bestandteil von FK-41 §41.4.1 und
    entfallen ersatzlos.

    Attributes:
        SCOPE_DRIFT: Story-Scope ueberschritten oder verlassen.
        ARCHITECTURE_VIOLATION: Architektur-Konzept verletzt.
        EVIDENCE_FABRICATION: Belege fabriziert oder manipuliert.
        HALLUCINATION: LLM-Halluzination (erfundene Fakten).
        TEST_OMISSION: Pflichttests weggelassen.
        ASSERTION_WEAKNESS: Tests zu schwach (False-Negative-Risiko).
        UNSAFE_REFACTOR: Refactoring ohne Sicherungsnetz.
        POLICY_VIOLATION: Guardrail- oder Policy-Verstoss.
        TOOL_MISUSE: Falsche Tool-Verwendung durch Worker.
        STATE_DESYNC: Inkonsistenter State (Code vs. Telemetrie vs. Doc).
        REQUIREMENTS_MISS: ARE-Anforderung uebersehen.
        REVIEW_EVASION: Review-Pflicht umgangen.
    """

    SCOPE_DRIFT = "scope_drift"
    ARCHITECTURE_VIOLATION = "architecture_violation"
    EVIDENCE_FABRICATION = "evidence_fabrication"
    HALLUCINATION = "hallucination"
    TEST_OMISSION = "test_omission"
    ASSERTION_WEAKNESS = "assertion_weakness"
    UNSAFE_REFACTOR = "unsafe_refactor"
    POLICY_VIOLATION = "policy_violation"
    TOOL_MISUSE = "tool_misuse"
    STATE_DESYNC = "state_desync"
    REQUIREMENTS_MISS = "requirements_miss"
    REVIEW_EVASION = "review_evasion"


class IncidentStatus(StrEnum):
    """Incident-Lebenszyklus pro FK-41 §41.3.1 + Glossar ``incident-status``.

    Die untenstehende Liste ist abschliessend (4 Werte). Uebergaenge sind
    ausschliesslich vorwaertsgerichtet. AG3-028 KONFLIKT-1: ersetzt den
    frueheren Sammel-Enum ``PromotionStatus``.

    Attributes:
        OBSERVED: erfasst und klassifiziert — Pflichtfelder werden beim
            Schreiben erzwungen, einen unklassifizierten Roh-Zustand gibt es
            nicht (Default fuer neue Incidents).
        PROMOTED: in ein Pattern uebernommen (zusaetzlich aus gesetztem
            ``pattern_ref`` ableitbar).
        CLOSED_ONE_OFF: geprueft, kein Praeventionswert.
        ARCHIVED: nur noch historisch relevant.
    """

    OBSERVED = "observed"
    PROMOTED = "promoted"
    CLOSED_ONE_OFF = "closed_one_off"
    ARCHIVED = "archived"
