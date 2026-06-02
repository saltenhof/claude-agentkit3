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


class PatternStatus(StrEnum):
    """Pattern-Lebenszyklus pro FK-41 §41.3.2 + Glossar ``pattern-status``.

    Die untenstehende Liste ist abschliessend (4 Werte). Uebergaenge sind
    ausschliesslich vorwaertsgerichtet. AG3-028 KONFLIKT-1: einer der drei
    entitaets-scoped Lifecycle-Enums, die den frueheren Sammel-Enum
    ``PromotionStatus`` ersetzen. Der Fortschritt eines abgeleiteten Checks ist
    KEIN Pattern-Zustand, sondern ueber ``check_ref`` auf :class:`CheckStatus`
    ableitbar (FK-41 §41.3.2).

    Materialisiert mit AG3-040 Sub-Block (b) (fc_patterns-Tabelle + Repository-
    Skelett); der funktionale Producer (``PatternPromotion``) folgt in einer
    Folge-Story (FK-41 §41.5), die volle Promotion-Logik ist Out of Scope.

    Attributes:
        CANDIDATE: aus Clustering vorgeschlagen, noch nicht bestaetigt.
        ACCEPTED: menschlich bestaetigt, Check-Ableitung moeglich. Kein Pattern
            wird ``accepted`` ohne ``confirmed_by = human`` (FK-41 §41.3.2).
        REJECTED: im Review verworfen.
        RETIRED: nicht mehr relevant.
    """

    CANDIDATE = "candidate"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    RETIRED = "retired"


class CheckStatus(StrEnum):
    """Check-Lebenszyklus pro FK-41 §41.3.3 + Glossar ``check-status``.

    Die untenstehende Liste ist abschliessend (5 Werte). Uebergaenge sind
    ausschliesslich vorwaertsgerichtet, ausser dem menschlichen Rueckruf einer
    Auto-Deaktivierung (FK-41 §41.6.7). AG3-028 KONFLIKT-1: einer der drei
    entitaets-scoped Lifecycle-Enums, die den frueheren Sammel-Enum
    ``PromotionStatus`` ersetzen.

    Materialisiert mit AG3-040 Sub-Block (b) (fc_check_proposals-Tabelle +
    Repository-Skelett); der funktionale Producer (``CheckFactory``) folgt in
    einer Folge-Story (FK-41 §41.6), die volle Check-Factory-Logik ist Out of
    Scope.

    Attributes:
        DRAFT: Spezifikation erstellt.
        APPROVED: menschlich freigegeben (``approved_by = human``, FK-41
            §41.3.3).
        ACTIVE: in der Pipeline aktiv (wird zwangslaeufig auf Wirksamkeit
            erfasst — kein separater Beobachtungszustand).
        REJECTED: im Review verworfen.
        RETIRED: deaktiviert (irrelevant oder zu viele False Positives).
    """

    DRAFT = "draft"
    APPROVED = "approved"
    ACTIVE = "active"
    REJECTED = "rejected"
    RETIRED = "retired"


class CheckType(StrEnum):
    """Check-Typ eines generierten Check-Proposals pro FK-41 §41.3.3/§41.6.3.

    Die untenstehende Liste ist abschliessend (6 Werte). Der Check-Typ wird in
    FK-41 §41.6.3 deterministisch (kein LLM) aus der Fehlerkategorie zugeordnet.

    Materialisiert mit AG3-040 Sub-Block (b) (fc_check_proposals-Tabelle +
    Repository-Skelett); die deterministische Typ-Zuordnung (FK-41 §41.6.3) ist
    Aufgabe der ``CheckFactory``-Folge-Story (Out of Scope).

    Attributes:
        CHANGED_FILE_POLICY: scope_drift / unsafe_refactor.
        ARTIFACT_COMPLETENESS: evidence_fabrication / review_evasion /
            requirements_miss.
        TEST_OBLIGATION: test_omission / assertion_weakness.
        SENSITIVE_PATH_GUARD: policy_violation / tool_misuse.
        FORBIDDEN_DEPENDENCY: architecture_violation.
        FIXTURE_REPLAY: hallucination / state_desync.
    """

    CHANGED_FILE_POLICY = "Changed-File-Policy"
    ARTIFACT_COMPLETENESS = "Artifact-Completeness"
    TEST_OBLIGATION = "Test-Obligation"
    SENSITIVE_PATH_GUARD = "Sensitive-Path-Guard"
    FORBIDDEN_DEPENDENCY = "Forbidden-Dependency"
    FIXTURE_REPLAY = "Fixture-Replay"
