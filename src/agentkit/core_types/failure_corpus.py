"""FailureCategory und PromotionStatus — Failure-Corpus-Klassifikation.

Source of truth:
- FailureCategory: FK-41 §41.4.1 — concept/technical-design/41_failure_corpus_pattern_promotion_check_factory.md
  (Z. 281-294, 12 Werte). Abgeglichen mit bc-cut-decisions §BC 13
  Z. 1214-1218.
- PromotionStatus: FK-41 Glossar `exported_terms.promotion-status.values`
  Z. 70-76 (7 Werte). Die volle Glossar-Liste enthaelt zwar 17 Werte
  (Z. 60-76), Story AG3-021 §2.1.1.1 hat sich normativ auf die Sub-Liste
  in Z. 70-76 (monitoring/draft/approved/active/tuned/retired/rejected)
  festgelegt.
"""

from __future__ import annotations

from enum import StrEnum


class FailureCategory(StrEnum):
    """Failure-Kategorie pro FK-41 §41.4.1 (12 Werte).

    Frueher zirkulierende Werte wie INSTRUCTION_NEGLECT,
    BAR_RAISING_FAILURE, TEST_FRAMEWORK_GAP, OTHER etc. sind kein
    Bestandteil von FK-41 §41.4.1 und entfallen.

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


class PromotionStatus(StrEnum):
    """Promotion-Status pro FK-41 Glossar (Story-normative Sub-Liste,
    Z. 70-76).

    Frueher zirkulierende Listen wie
    OBSERVED/PROPOSED/CONFIRMED/IMPLEMENTED/RETIRED entfallen.

    Attributes:
        MONITORING: Pattern in Beobachtung; noch nicht akzeptiert.
        DRAFT: Check-Vorschlag im Entwurf.
        APPROVED: Check vom Menschen freigegeben.
        ACTIVE: Check aktiv in der Pipeline eingesetzt.
        TUNED: Check nach Effektivitaetsmessung nachjustiert.
        RETIRED: Check ausser Dienst gestellt.
        REJECTED: Check-Vorschlag abgelehnt.
    """

    MONITORING = "monitoring"
    DRAFT = "draft"
    APPROVED = "approved"
    ACTIVE = "active"
    TUNED = "tuned"
    RETIRED = "retired"
    REJECTED = "rejected"
