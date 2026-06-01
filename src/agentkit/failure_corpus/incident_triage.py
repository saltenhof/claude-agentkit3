"""IncidentTriage-Sub des Failure-Corpus-BC (FK-41 §41.4).

Drei deterministische Schritte (AG3-028 AK#5):
1. IngressCriteria   -- Aufnahmekriterien FK-41 §41.4.3 (FAIL-CLOSED via
   IncidentRejectedError)
2. IncidentNormalizer -- Whitespace-/Length-Normalisierung + recorded_at
3. IncidentWriterPort.record_fc_incident(draft) -> IncidentId

Persistenz und Lesen laufen ausschliesslich ueber die injizierten Ports
(FK-69 §69.9). ``failure_corpus`` importiert KEIN ``state_backend.store`` (AC#6).

IngressCriteria-Kombinator-Semantik (FK-41 §41.4.3 — Codex-r1 Remediation):
  Das Konzept listet vier Kriterien (Severity >= mittel; Merge blockiert;
  Rework > 30min; Fehlertyp neu) ohne explizite AND/OR-Verknuepfung. Gewaehlte,
  fail-closed-vernuenftigste Lesart (vgl. FK-41 §41.4.3-Ziel "<20 neue Incidents
  pro Monat" + DK-07 §7.3 "nicht bei jedem fehlgeschlagenen Test"):

    ADMIT  <=>  (severity >= min_severity)
                AND (merge_blocked OR rework_minutes > 30 OR is_novel)

  - Severity-Floor ist ein **harter Gate** (AND): ein Bagatell-Befund wird nie
    aufgenommen, egal wie oft er auftritt (Korpus klein halten).
  - Die drei Signifikanz-Trigger sind **OR-verknuepft**: ein einziger genuegt,
    damit ein hinreichend schwerer Befund aufgenommen wird (Rueckkopplungstreue).
  - Corpus-Neuheit (``is_novel``) wird gegen die persistierten ``fc_incidents``
    geprueft (gleiches (project_key, category) noch nicht vorhanden -> neu).

  Verbleibende Ambiguitaet (an Review/User gemeldet): ob der Severity-Floor
  tatsaechlich als harter AND-Gate gelten soll oder selbst nur ein
  OR-Signifikanz-Trigger ist, ist im Konzept nicht 100% explizit. Die hier
  gewaehlte AND-Lesart ist die restriktivere (fail-closed) Variante.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentkit.failure_corpus.errors import IncidentRejectedError, IncidentRejectReason
from agentkit.failure_corpus.incident import IncidentCandidate, IncidentDraft
from agentkit.failure_corpus.types import IncidentId, IncidentSeverity

if TYPE_CHECKING:
    from agentkit.failure_corpus.ports import IncidentWriterPort, ProjectionReaderPort

# Ordnung der Incident-Severity-Stufen fuer den Mindest-Severity-Vergleich.
_SEVERITY_RANK: dict[IncidentSeverity, int] = {
    IncidentSeverity.LOW: 0,
    IncidentSeverity.MEDIUM: 1,
    IncidentSeverity.HIGH: 2,
    IncidentSeverity.CRITICAL: 3,
}

# Default-Mindest-Severity (FK-41 §41.4.3: mindestens "mittel" == MEDIUM).
_DEFAULT_MIN_SEVERITY = IncidentSeverity.MEDIUM
# Rework-Schwelle (FK-41 §41.4.3: "Ueber 30 Minuten").
_REWORK_THRESHOLD_MIN = 30


def _now() -> datetime:
    """Aktueller UTC-Zeitpunkt (Seiteneffekt am Rand der Triage)."""
    return datetime.now(tz=UTC)


class IncidentNormalizer:
    """Default-Normalisierung eines Incident-Kandidaten (FK-41 §41.4).

    Schaerft NICHT die Kategorie (``category`` ist Pflicht im Kandidaten),
    sondern normalisiert ``symptom`` (Whitespace-Kollaps, Trim, Laengen-Cap)
    und setzt ``recorded_at``.

    Args:
        max_symptom_length: Maximale Laenge des normalisierten ``symptom``.
    """

    def __init__(self, *, max_symptom_length: int = 2000) -> None:
        self._max_symptom_length = max_symptom_length

    def normalize(
        self,
        candidate: IncidentCandidate,
        *,
        recorded_at: datetime,
    ) -> IncidentDraft:
        """Erzeuge einen normalisierten ``IncidentDraft`` (noch ohne id).

        Args:
            candidate: Eingehender Kandidat.
            recorded_at: Erfassungszeitpunkt (von der Triage gesetzt).

        Returns:
            Normalisierter ``IncidentDraft`` (Status ``OBSERVED``); ``incident_id``
            wird erst DB-seitig in der Schreibtransaktion vergeben.
        """
        normalized_symptom = " ".join(candidate.symptom.split())[
            : self._max_symptom_length
        ]
        return IncidentDraft(
            project_key=candidate.project_key,
            story_id=candidate.story_id,
            run_id=candidate.run_id,
            category=candidate.category,
            severity=candidate.severity,
            phase=candidate.phase,
            role=candidate.role,
            model=candidate.model,
            symptom=normalized_symptom,
            evidence=list(candidate.evidence),
            recorded_at=recorded_at,
            tags=list(candidate.tags) if candidate.tags is not None else None,
            impact=candidate.impact,
        )


class IngressCriteria:
    """Aufnahmekriterien fuer Incident-Kandidaten (FK-41 §41.4.3).

    Kombinator-Semantik (siehe Modul-Docstring): ADMIT iff
    ``severity >= min_severity`` AND (``merge_blocked`` OR ``rework > 30`` OR
    ``is_novel``). Verwerfen ist FAIL-CLOSED ueber ``IncidentRejectedError`` mit
    erreichbaren ``reason_codes`` — kein stilles Ignorieren.

    Args:
        min_severity: Tiefste akzeptierte Severity (Default ``MEDIUM``).
        rework_threshold_min: Rework-Schwelle in Minuten (Default 30; FK-41
            §41.4.3 "Ueber 30 Minuten").
    """

    def __init__(
        self,
        *,
        min_severity: IncidentSeverity = _DEFAULT_MIN_SEVERITY,
        rework_threshold_min: int = _REWORK_THRESHOLD_MIN,
    ) -> None:
        self._min_severity = min_severity
        self._rework_threshold_min = rework_threshold_min

    def check(self, candidate: IncidentCandidate, *, is_novel: bool) -> None:
        """Prueft den Kandidaten; wirft bei Reject ``IncidentRejectedError``.

        Args:
            candidate: Zu pruefender Kandidat (inkl. Gate-Inputs ``merge_blocked``
                und ``rework_minutes``).
            is_novel: Corpus-Neuheit (FK-41 §41.4.3: Fehlertyp noch nicht im
                Corpus vertreten). Vom Aufrufer aus dem persistierten Corpus
                ermittelt.

        Raises:
            IncidentRejectedError: Wenn der Severity-Floor unterschritten ist
                (``BELOW_MIN_SEVERITY``) oder — bei ausreichender Severity — kein
                Signifikanz-Trigger erfuellt ist (``NOT_SIGNIFICANT``).
        """
        # Harter Gate: Severity-Floor (FK-41 §41.4.3 Kriterium 1).
        if _SEVERITY_RANK[candidate.severity] < _SEVERITY_RANK[self._min_severity]:
            raise IncidentRejectedError(
                (IncidentRejectReason.BELOW_MIN_SEVERITY,),
                detail=(
                    f"severity {candidate.severity.value} < "
                    f"min {self._min_severity.value}"
                ),
            )

        # OR-verknuepfte Signifikanz-Trigger (FK-41 §41.4.3 Kriterien 2-4).
        significant = (
            candidate.merge_blocked
            or candidate.rework_minutes > self._rework_threshold_min
            or is_novel
        )
        if not significant:
            raise IncidentRejectedError(
                (IncidentRejectReason.NOT_SIGNIFICANT,),
                detail=(
                    "no significance trigger: not merge-blocking, "
                    f"rework {candidate.rework_minutes}min <= "
                    f"{self._rework_threshold_min}min, error type already in corpus"
                ),
            )


class IncidentTriage:
    """Aufnahme-Sub des Failure-Corpus (FK-41 §41.4).

    Args:
        normalizer: Normalisierer fuer akzeptierte Kandidaten.
        criteria: Aufnahmekriterien (FK-41 §41.4.3).
        writer: Schmale fc-Schreib-Sicht auf den ``ProjectionAccessor`` (gibt die
            DB-seitig vergebene ``IncidentId`` zurueck, FK-41 §41.3.1).
        reader: Schmale Lese-Sicht fuer die Corpus-Neuheit (FK-41 §41.4.3).
    """

    def __init__(
        self,
        normalizer: IncidentNormalizer,
        criteria: IngressCriteria,
        writer: IncidentWriterPort,
        reader: ProjectionReaderPort,
    ) -> None:
        self._normalizer = normalizer
        self._criteria = criteria
        self._writer = writer
        self._reader = reader

    def ingest(self, candidate: IncidentCandidate) -> IncidentId:
        """Nimmt einen Kandidaten auf, normalisiert und persistiert ihn.

        Ablauf (FK-41 §41.4): Corpus-Neuheit ermitteln -> IngressCriteria ->
        Normalizer -> record_fc_incident.

        Args:
            candidate: Eingehender Incident-Kandidat.

        Returns:
            Die DB-seitig vergebene ``IncidentId`` (``FC-YYYY-NNNN``).

        Raises:
            IncidentRejectedError: Wenn die IngressCriteria den Kandidaten
                verwerfen (FAIL-CLOSED, mit ``reason_codes``).
        """
        is_novel = self._is_novel(candidate)
        self._criteria.check(candidate, is_novel=is_novel)

        draft = self._normalizer.normalize(candidate, recorded_at=_now())
        return self._writer.record_fc_incident(draft)

    def _is_novel(self, candidate: IncidentCandidate) -> bool:
        """Corpus-Neuheit: ist (project_key, category) noch nicht im Corpus?

        FK-41 §41.4.3: "Fehlertyp neu / Noch nicht im Corpus vertreten". Granularitaet
        = Failure-Kategorie pro Projekt. Geprueft gegen die persistierten
        ``fc_incidents`` ueber den Lese-Port (FAIL-CLOSED: projektgebunden).

        Args:
            candidate: Der zu pruefende Kandidat.

        Returns:
            ``True``, wenn keine persistierte fc_incidents-Zeile dieses Projekts
            dieselbe ``category`` traegt.
        """
        from agentkit.telemetry.projection_accessor import (
            ProjectionFilter,
            ProjectionKind,
        )

        existing = self._reader.read_projection(
            ProjectionKind.FC_INCIDENTS,
            ProjectionFilter(project_key=candidate.project_key),
        )
        return not any(
            getattr(row, "category", None) == candidate.category for row in existing
        )


__all__ = [
    "IncidentNormalizer",
    "IncidentTriage",
    "IngressCriteria",
]
