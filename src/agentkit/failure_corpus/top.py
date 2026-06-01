"""FailureCorpus-Top-Komponente (FK-41 §41.1).

Vollstaendige Vertrags-Surface mit sechs Methoden. Nur ``record_incident`` ist
in dieser Story (AG3-028) funktional — es ist der Empfaenger-Vertrag, den andere
BCs (governance-and-guards / verify-system / story-closure) brauchen. Die fuenf
uebrigen Methoden werfen ``NotImplementedError`` mit Begruendung + Verweis auf
ihre Folge-Story (ZERO DEBT: Vertrags-Slot, nicht halbfertig).

Folge-Stories:
- ``suggest_patterns``/``confirm_pattern``: PatternPromotion-Sub
  (failure-corpus.A4, nach THEME-009 / LlmEvaluator).
- ``derive_check``/``approve_check``: CheckFactory-Sub (failure-corpus.A5).
- ``report_effectiveness``: Effectiveness-Tracking (failure-corpus.A7).

Quellen:
- FK-41 §41.1 -- sechs Top-Methoden
- bc-cut-decisions §BC 13 -- Top-Surface, Subs
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from agentkit.failure_corpus.types import CheckId, IncidentId, PatternId

if TYPE_CHECKING:
    from agentkit.failure_corpus.incident import IncidentCandidate
    from agentkit.failure_corpus.incident_triage import IncidentTriage


class PatternDecision(StrEnum):
    """Menschliche Entscheidung ueber einen Pattern-Kandidaten (FK-41 §41.1).

    Attributes:
        ACCEPTED: Pattern bestaetigt.
        REJECTED: Pattern verworfen.
    """

    ACCEPTED = "accepted"
    REJECTED = "rejected"


class CheckApprovalDecision(StrEnum):
    """Menschliche Entscheidung ueber einen Check-Vorschlag (FK-41 §41.1).

    Attributes:
        APPROVED: Check freigegeben.
        REJECTED: Check verworfen.
    """

    APPROVED = "approved"
    REJECTED = "rejected"


class PatternCandidate(BaseModel):
    """Vorschlag aus dem Clustering (FK-41 Pattern-Lifecycle, Folge-Story)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    pattern_id: PatternId


class FailurePattern(BaseModel):
    """Bestaetigter Pattern (Lifecycle-Stufe ``accepted``, Folge-Story)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    pattern_id: PatternId


class CheckProposal(BaseModel):
    """Generierter Check-Vorschlag (FK-41 CheckFactory, Folge-Story)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    check_id: CheckId


class EffectivenessReport(BaseModel):
    """Aggregat-Bericht ueber ein Wirksamkeits-Window (Folge-Story)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    window_days: int


class FailureCorpus:
    """Top-Komponente des Failure-Corpus-BC (FK-41 §41.1).

    Args:
        incident_triage: Die funktionale IncidentTriage-Sub (AG3-028).
        pattern_promotion: Stub-Slot fuer die PatternPromotion-Sub (Folge-Story).
        check_factory: Stub-Slot fuer die CheckFactory-Sub (Folge-Story).
    """

    def __init__(
        self,
        incident_triage: IncidentTriage,
        pattern_promotion: object | None = None,
        check_factory: object | None = None,
    ) -> None:
        self._incident_triage = incident_triage
        self._pattern_promotion = pattern_promotion
        self._check_factory = check_factory

    def record_incident(self, candidate: IncidentCandidate) -> IncidentId:
        """Nimmt einen Incident-Kandidaten auf und persistiert ihn (FK-41 §41.1).

        Delegiert an die ``IncidentTriage`` (IngressCriteria -> Normalizer ->
        ``write_projection(FC_INCIDENTS, incident)``). Empfaenger-Vertrag fuer
        governance-and-guards / verify-system / story-closure.

        Args:
            candidate: Eingehender Incident-Kandidat.

        Returns:
            Die vergebene ``IncidentId``.

        Raises:
            IncidentRejectedError: Wenn die IngressCriteria den Kandidaten
                verwerfen (FAIL-CLOSED).
        """
        return self._incident_triage.ingest(candidate)

    def suggest_patterns(self) -> list[PatternCandidate]:
        """NOT IMPLEMENTED — PatternPromotion-Sub (Folge-Story failure-corpus.A4).

        Raises:
            NotImplementedError: PatternPromotion braucht LlmEvaluator (THEME-009)
                und ist nicht Teil von AG3-028.
        """
        raise NotImplementedError(
            "suggest_patterns gehoert zur PatternPromotion-Sub (failure-corpus.A4, "
            "Folge-Story nach THEME-009/LlmEvaluator) und ist in AG3-028 nicht im Scope."
        )

    def confirm_pattern(
        self,
        pattern_id: PatternId,
        decision: PatternDecision,
    ) -> FailurePattern:
        """NOT IMPLEMENTED — PatternPromotion-Sub (Folge-Story failure-corpus.A4).

        Args:
            pattern_id: Pattern-Identitaet.
            decision: Menschliche Entscheidung.

        Raises:
            NotImplementedError: PatternPromotion ist nicht Teil von AG3-028.
        """
        raise NotImplementedError(
            "confirm_pattern gehoert zur PatternPromotion-Sub (failure-corpus.A4, "
            "Folge-Story) und ist in AG3-028 nicht im Scope."
        )

    def derive_check(self, pattern_id: PatternId) -> CheckProposal:
        """NOT IMPLEMENTED — CheckFactory-Sub (Folge-Story failure-corpus.A5).

        Args:
            pattern_id: Pattern-Identitaet, aus der ein Check abgeleitet wuerde.

        Raises:
            NotImplementedError: CheckFactory ist nicht Teil von AG3-028.
        """
        raise NotImplementedError(
            "derive_check gehoert zur CheckFactory-Sub (failure-corpus.A5, "
            "Folge-Story) und ist in AG3-028 nicht im Scope."
        )

    def approve_check(
        self,
        check_id: CheckId,
        decision: CheckApprovalDecision,
    ) -> CheckProposal:
        """NOT IMPLEMENTED — CheckFactory-Sub (Folge-Story failure-corpus.A5).

        Args:
            check_id: Check-Identitaet.
            decision: Menschliche Freigabe-Entscheidung.

        Raises:
            NotImplementedError: CheckFactory ist nicht Teil von AG3-028.
        """
        raise NotImplementedError(
            "approve_check gehoert zur CheckFactory-Sub (failure-corpus.A5, "
            "Folge-Story) und ist in AG3-028 nicht im Scope."
        )

    def report_effectiveness(self, window_days: int = 90) -> EffectivenessReport:
        """NOT IMPLEMENTED — Effectiveness-Tracking (Folge-Story failure-corpus.A7).

        Args:
            window_days: Betrachtungsfenster in Tagen.

        Raises:
            NotImplementedError: Effectiveness-Tracking ist nicht Teil von AG3-028.
        """
        raise NotImplementedError(
            "report_effectiveness gehoert zum Effectiveness-Tracking "
            "(failure-corpus.A7, Folge-Story) und ist in AG3-028 nicht im Scope."
        )


__all__ = [
    "CheckApprovalDecision",
    "CheckProposal",
    "EffectivenessReport",
    "FailureCorpus",
    "FailurePattern",
    "PatternCandidate",
    "PatternDecision",
]
