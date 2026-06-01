"""IncidentTriage-Sub des Failure-Corpus-BC (FK-41 §41.4 / DK-07 §7.3.6).

Drei deterministische Schritte (AG3-028 AK#5):
1. IngressCriteria   -- Aufnahmekriterien DK-07 §7.3.6 (FAIL-CLOSED via
   IncidentRejectedError)
2. IncidentNormalizer -- Whitespace-/Length-Normalisierung + recorded_at
3. IncidentWriterPort.record_fc_incident(draft) -> IncidentId

Persistenz und Lesen laufen ausschliesslich ueber die injizierten Ports
(FK-69 §69.9). ``failure_corpus`` importiert KEIN ``state_backend.store`` (AC#6).

IngressCriteria-Kombinator-Semantik (DK-07 §7.3.6 — Codex-r2 Remediation):
  DK-07 §7.3.6 ist autoritativ und explizit ein **reines ODER**. Ein Incident
  wird aufgenommen, wenn MINDESTENS EINES der vier Kriterien gilt:

    ADMIT  <=>  severity >= MEDIUM
                OR merge_blocked
                OR rework_minutes > 30
                OR is_novel (Corpus-Neuheit)

  - Severity ist KEIN harter Floor mehr: z.B. ``LOW + merge_blocked`` wird
    aufgenommen (der frühere AND-Floor verwarf das faelschlich).
  - REJECT (``NOT_SIGNIFICANT``) genau dann, wenn KEINES der vier Kriterien
    greift.
  - Zusaetzlich (separat, vor der ODER-Pruefung): exakter Duplikat im
    Zeitfenster -> REJECT ``DUPLICATE_WINDOW`` (Dedup; haelt den Korpus klein).
  - Corpus-Neuheit (``is_novel``) wird gegen die persistierten ``fc_incidents``
    geprueft (gleiches (project_key, category) noch nicht vorhanden -> neu).
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

    def normalize_symptom(self, symptom: str) -> str:
        """Whitespace-Kollaps + Trim + Laengen-Cap (deterministisch).

        Wird sowohl beim Erzeugen des Drafts als auch fuer die Dedup-Signatur
        (exakter Duplikat) verwendet, damit beide identisch normalisieren.

        Args:
            symptom: Roher Symptomtext.

        Returns:
            Normalisierter Symptomtext.
        """
        return " ".join(symptom.split())[: self._max_symptom_length]

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
        normalized_symptom = self.normalize_symptom(candidate.symptom)
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
    """Aufnahmekriterien fuer Incident-Kandidaten (DK-07 §7.3.6).

    Kombinator-Semantik (siehe Modul-Docstring): reines ODER. ADMIT iff
    ``severity >= min_severity`` OR ``merge_blocked`` OR ``rework > 30`` OR
    ``is_novel``. Verwerfen ist FAIL-CLOSED ueber ``IncidentRejectedError`` mit
    erreichbaren ``reason_codes`` — kein stilles Ignorieren. Zusaetzlich wird ein
    exakter Duplikat (``is_duplicate``) separat als ``DUPLICATE_WINDOW``
    verworfen.

    Args:
        min_severity: Severity-Schwelle des ersten ODER-Kriteriums (Default
            ``MEDIUM``; DK-07 §7.3.6 "Severity mindestens mittel"). KEIN harter
            Floor — nur eines von vier ODER-Kriterien.
        rework_threshold_min: Rework-Schwelle in Minuten (Default 30; DK-07
            §7.3.6 "Ueber 30 Minuten").
    """

    def __init__(
        self,
        *,
        min_severity: IncidentSeverity = _DEFAULT_MIN_SEVERITY,
        rework_threshold_min: int = _REWORK_THRESHOLD_MIN,
    ) -> None:
        self._min_severity = min_severity
        self._rework_threshold_min = rework_threshold_min

    def check(
        self,
        candidate: IncidentCandidate,
        *,
        is_novel: bool,
        is_duplicate: bool = False,
    ) -> None:
        """Prueft den Kandidaten; wirft bei Reject ``IncidentRejectedError``.

        Args:
            candidate: Zu pruefender Kandidat (inkl. Gate-Inputs ``merge_blocked``
                und ``rework_minutes``).
            is_novel: Corpus-Neuheit (DK-07 §7.3.6: Fehlertyp noch nicht im
                Corpus vertreten). Vom Aufrufer aus dem persistierten Corpus
                ermittelt.
            is_duplicate: Exakter Duplikat eines bereits im Zeitfenster
                persistierten Incidents (Dedup). Vom Aufrufer ermittelt.

        Raises:
            IncidentRejectedError: ``DUPLICATE_WINDOW`` bei exaktem Duplikat;
                ``NOT_SIGNIFICANT``, wenn KEINES der vier DK-07-§7.3.6-Kriterien
                greift (reines ODER).
        """
        # Dedup zuerst: exakter Duplikat im Zeitfenster -> verwerfen.
        if is_duplicate:
            raise IncidentRejectedError(
                (IncidentRejectReason.DUPLICATE_WINDOW,),
                detail="exact duplicate of an incident already in the time window",
            )

        # Reines ODER der vier DK-07-§7.3.6-Aufnahmekriterien.
        admit = (
            _SEVERITY_RANK[candidate.severity] >= _SEVERITY_RANK[self._min_severity]
            or candidate.merge_blocked
            or candidate.rework_minutes > self._rework_threshold_min
            or is_novel
        )
        if not admit:
            raise IncidentRejectedError(
                (IncidentRejectReason.NOT_SIGNIFICANT,),
                detail=(
                    "no ingress criterion met (DK-07 §7.3.6 OR): severity "
                    f"{candidate.severity.value} < {self._min_severity.value}, "
                    "not merge-blocking, rework "
                    f"{candidate.rework_minutes}min <= "
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
        existing = self._read_corpus(candidate)
        is_novel = not any(
            getattr(row, "category", None) == candidate.category for row in existing
        )
        is_duplicate = self._is_exact_duplicate(candidate, existing)
        self._criteria.check(
            candidate, is_novel=is_novel, is_duplicate=is_duplicate
        )

        draft = self._normalizer.normalize(candidate, recorded_at=_now())
        return self._writer.record_fc_incident(draft)

    def _read_corpus(self, candidate: IncidentCandidate) -> list[object]:
        """Lese den projektgebundenen Corpus-Ausschnitt (FAIL-CLOSED).

        FK-41 §41.4.3 / DK-07 §7.3.6: Corpus-Abfragen sind stets projektgebunden.

        Args:
            candidate: Der zu pruefende Kandidat.

        Returns:
            Die persistierten ``fc_incidents``-Zeilen dieses Projekts.
        """
        from agentkit.telemetry.projection_accessor import (
            ProjectionFilter,
            ProjectionKind,
        )

        return list(
            self._reader.read_projection(
                ProjectionKind.FC_INCIDENTS,
                ProjectionFilter(project_key=candidate.project_key),
            )
        )

    def _is_exact_duplicate(
        self, candidate: IncidentCandidate, existing: list[object]
    ) -> bool:
        """Exakter Duplikat im Zeitfenster (Dedup, DK-07 §7.3.6).

        Ein Duplikat ist ein bereits persistierter Incident desselben Projekts mit
        identischer fachlicher Signatur (story_id, run_id, category, severity,
        phase, role, model, normalisiertes symptom). ``fc_incidents`` haelt nur
        Incidents lebender Runs (vollstaendiger Reset purged sie, FK-41 §41.3) —
        der persistierte Corpus IST damit das Dedup-Zeitfenster.

        Args:
            candidate: Der zu pruefende Kandidat.
            existing: Bereits gelesene projektgebundene Corpus-Zeilen.

        Returns:
            ``True``, wenn die normalisierte Signatur bereits im Corpus liegt.
        """
        symptom = self._normalizer.normalize_symptom(candidate.symptom)
        signature = (
            candidate.story_id,
            candidate.run_id,
            candidate.category,
            candidate.severity,
            candidate.phase,
            candidate.role,
            candidate.model,
            symptom,
        )
        return any(self._row_signature(row) == signature for row in existing)

    @staticmethod
    def _row_signature(row: object) -> tuple[object, ...]:
        """Fachliche Signatur einer persistierten fc_incidents-Zeile (Dedup)."""
        return (
            getattr(row, "story_id", None),
            getattr(row, "run_id", None),
            getattr(row, "category", None),
            getattr(row, "severity", None),
            getattr(row, "phase", None),
            getattr(row, "role", None),
            getattr(row, "model", None),
            getattr(row, "symptom", None),
        )


__all__ = [
    "IncidentNormalizer",
    "IncidentTriage",
    "IngressCriteria",
]
