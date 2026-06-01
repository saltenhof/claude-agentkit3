"""IncidentTriage-Sub des Failure-Corpus-BC (FK-41 §41.4).

Drei deterministische Schritte (AG3-028 AK#5):
1. IngressCriteria  -- relevanz-/Dedup-Filter (FAIL-CLOSED via IncidentRejectedError)
2. IncidentNormalizer -- Whitespace-/Length-Normalisierung + normalized_at
3. ProjectionWriterPort.write_projection(FC_INCIDENTS, incident)

Die Persistenz laeuft ausschliesslich ueber den injizierten
``ProjectionWriterPort`` (FK-69 §69.9). ``failure_corpus`` importiert KEIN
``state_backend.store`` (AC#6).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentkit.failure_corpus.errors import IncidentRejectedError, IncidentRejectReason
from agentkit.failure_corpus.incident import Incident, IncidentCandidate
from agentkit.failure_corpus.types import IncidentId, IncidentSeverity

if TYPE_CHECKING:
    from agentkit.failure_corpus.ports import ProjectionWriterPort

# Ordnung der Incident-Severity-Stufen fuer den Mindest-Severity-Vergleich.
_SEVERITY_RANK: dict[IncidentSeverity, int] = {
    IncidentSeverity.LOW: 0,
    IncidentSeverity.MEDIUM: 1,
    IncidentSeverity.HIGH: 2,
    IncidentSeverity.CRITICAL: 3,
}

# Dedup-Fenster fuer identische Kandidaten (FK-41 §41.4).
_DEFAULT_DEDUP_WINDOW_S = 60.0
# Default-Mindest-Severity (FK-41 §41.4: MEDIUM aufwaerts).
_DEFAULT_MIN_SEVERITY = IncidentSeverity.MEDIUM


def _now() -> datetime:
    """Aktueller UTC-Zeitpunkt (Seiteneffekt am Rand der Triage)."""
    return datetime.now(tz=UTC)


class IncidentNormalizer:
    """Default-Normalisierung eines Incident-Kandidaten (FK-41 §41.4).

    Schaerft NICHT die Kategorie (``category`` ist Pflicht im Kandidaten),
    sondern normalisiert die ``summary`` (Whitespace-Kollaps, Trim, Laengen-Cap)
    und setzt ``normalized_at``.

    Args:
        max_summary_length: Maximale Laenge der normalisierten ``summary``.
    """

    def __init__(self, *, max_summary_length: int = 2000) -> None:
        self._max_summary_length = max_summary_length

    def normalize(
        self,
        candidate: IncidentCandidate,
        *,
        incident_id: IncidentId,
        normalized_at: datetime,
    ) -> Incident:
        """Erzeuge einen normalisierten ``Incident`` aus dem Kandidaten.

        Args:
            candidate: Eingehender Kandidat.
            incident_id: Vergebene Incident-Identitaet.
            normalized_at: Normalisierungszeitpunkt (von der Triage gesetzt).

        Returns:
            Normalisierter, persistierbarer ``Incident`` (Status ``OBSERVED``).
        """
        normalized_summary = " ".join(candidate.summary.split())[
            : self._max_summary_length
        ]
        return Incident(
            incident_id=incident_id,
            category=candidate.category,
            severity=candidate.severity,
            source_bc=candidate.source_bc,
            story_id=candidate.story_id,
            run_id=candidate.run_id,
            summary=normalized_summary,
            evidence=candidate.evidence,
            observed_at=candidate.observed_at,
            normalized_at=normalized_at,
        )


class IngressCriteria:
    """Relevanz- und Dedup-Filter fuer Incident-Kandidaten (FK-41 §41.4).

    Zwei Regeln:
    - Mindest-Severity: Kandidaten unterhalb ``min_severity`` werden verworfen.
    - Dedup: identischer ``(source_bc, story_id, summary)`` innerhalb des
      ``dedup_window_s``-Fensters wird verworfen.

    Verwerfen ist FAIL-CLOSED ueber ``IncidentRejectedError`` mit strukturierten
    ``reason_codes`` — kein stilles Ignorieren.

    Args:
        min_severity: Tiefste akzeptierte Severity (Default ``MEDIUM``).
        dedup_window_s: Dedup-Fenster in Sekunden (Default 60s).
    """

    def __init__(
        self,
        *,
        min_severity: IncidentSeverity = _DEFAULT_MIN_SEVERITY,
        dedup_window_s: float = _DEFAULT_DEDUP_WINDOW_S,
    ) -> None:
        self._min_severity = min_severity
        self._dedup_window_s = dedup_window_s
        # Letzter Zeitpunkt pro Dedup-Schluessel (in-memory, bounded via purge).
        self._seen: dict[tuple[str, str, str], datetime] = {}

    def check(self, candidate: IncidentCandidate, *, now: datetime) -> None:
        """Prueft den Kandidaten; wirft bei Reject ``IncidentRejectedError``.

        Args:
            candidate: Zu pruefender Kandidat.
            now: Referenzzeitpunkt fuer das Dedup-Fenster.

        Raises:
            IncidentRejectedError: Bei Unterschreiten der Mindest-Severity oder
                Dedup-Treffer; traegt die strukturierten ``reason_codes``.
        """
        reasons: list[IncidentRejectReason] = []

        if _SEVERITY_RANK[candidate.severity] < _SEVERITY_RANK[self._min_severity]:
            reasons.append(IncidentRejectReason.BELOW_MIN_SEVERITY)

        key = (candidate.source_bc, candidate.story_id, candidate.summary)
        last_seen = self._seen.get(key)
        if (
            last_seen is not None
            and (now - last_seen).total_seconds() < self._dedup_window_s
        ):
            reasons.append(IncidentRejectReason.DUPLICATE_WINDOW)

        if reasons:
            raise IncidentRejectedError(tuple(reasons))

    def remember(self, candidate: IncidentCandidate, *, now: datetime) -> None:
        """Merkt den akzeptierten Kandidaten fuer kuenftige Dedup-Pruefungen.

        Args:
            candidate: Akzeptierter Kandidat.
            now: Akzeptanzzeitpunkt.
        """
        key = (candidate.source_bc, candidate.story_id, candidate.summary)
        self._seen[key] = now
        self._purge_expired(now)

    def _purge_expired(self, now: datetime) -> None:
        """Entfernt Dedup-Eintraege ausserhalb des Fensters (bounded memory)."""
        expired = [
            key
            for key, seen in self._seen.items()
            if (now - seen).total_seconds() >= self._dedup_window_s
        ]
        for key in expired:
            del self._seen[key]


class IncidentTriage:
    """Aufnahme-Sub des Failure-Corpus (FK-41 §41.4).

    Args:
        normalizer: Normalisierer fuer akzeptierte Kandidaten.
        criteria: Ingress-/Dedup-Filter.
        projection_writer: Schmale Schreib-Sicht auf den ``ProjectionAccessor``
            (FK-69 §69.9). ``failure_corpus`` kennt kein ``state_backend.store``.
    """

    def __init__(
        self,
        normalizer: IncidentNormalizer,
        criteria: IngressCriteria,
        projection_writer: ProjectionWriterPort,
    ) -> None:
        self._normalizer = normalizer
        self._criteria = criteria
        self._projection_writer = projection_writer

    def ingest(self, candidate: IncidentCandidate) -> IncidentId:
        """Nimmt einen Kandidaten auf, normalisiert und persistiert ihn.

        Ablauf (FK-41 §41.4): IngressCriteria -> Normalizer -> write_projection.

        Args:
            candidate: Eingehender Incident-Kandidat.

        Returns:
            Die vergebene ``IncidentId``.

        Raises:
            IncidentRejectedError: Wenn die IngressCriteria den Kandidaten
                verwerfen (FAIL-CLOSED, mit ``reason_codes``).
        """
        # Laufzeit-Import vermeidet die Modul-Init-Abhaengigkeit zu telemetry;
        # zur Laufzeit ist agentkit.telemetry laengst geladen.
        from agentkit.telemetry.projection_accessor import ProjectionKind

        now = _now()
        self._criteria.check(candidate, now=now)

        incident_id = IncidentId(f"FC-{uuid.uuid4().hex}")
        incident = self._normalizer.normalize(
            candidate,
            incident_id=incident_id,
            normalized_at=now,
        )
        self._projection_writer.write_projection(
            ProjectionKind.FC_INCIDENTS,
            incident,
        )
        self._criteria.remember(candidate, now=now)
        return incident_id


__all__ = [
    "IncidentNormalizer",
    "IncidentTriage",
    "IngressCriteria",
]
