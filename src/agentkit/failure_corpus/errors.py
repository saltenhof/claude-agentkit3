"""Typisierte Exceptions des Failure-Corpus-BC (FK-41 §41.4.3).

FAIL-CLOSED: IngressCriteria-Reject ist eine Exception mit strukturierten
``reason_codes`` — kein stilles Verwerfen (Guardrail FAIL CLOSED, AG3-028 AK#3).

ZERO DEBT (Codex-r1 Remediation): jeder ``IncidentRejectReason`` ist von der
``IngressCriteria``-Implementierung tatsaechlich erreichbar; es gibt keinen
toten reason_code mehr.
"""

from __future__ import annotations

from enum import StrEnum


class IncidentRejectReason(StrEnum):
    """Strukturierter Grund, warum die IngressCriteria einen Kandidaten verwirft.

    Die reason_codes spiegeln exakt die implementierten FK-41-§41.4.3-Kriterien
    (Severity-Floor als harter Gate + mindestens ein Signifikanz-Trigger).

    Attributes:
        BELOW_MIN_SEVERITY: Kandidat unterschreitet die Mindest-Severity
            (FK-41 §41.4.3: "Severity mindestens mittel"). Harter Gate.
        NOT_SIGNIFICANT: Severity ok, aber KEIN Signifikanz-Trigger erfuellt —
            d.h. weder Merge-blockiert, noch Rework > 30min, noch neuer
            Fehlertyp/Corpus-Neuheit (FK-41 §41.4.3 Kriterien 2-4 als
            OR-Verknuepfung; siehe IngressCriteria-Kombinator-Doku).
    """

    BELOW_MIN_SEVERITY = "below_min_severity"
    NOT_SIGNIFICANT = "not_significant"


class FailureCorpusError(Exception):
    """Basisklasse fuer alle Failure-Corpus-Fehler."""


class IncidentRejectedError(FailureCorpusError):
    """Ein Incident-Kandidat wurde von den IngressCriteria abgewiesen.

    Traegt die strukturierten ``reason_codes``, damit Aufrufer-BCs deterministisch
    auf den Grund reagieren koennen (statt String-Parsing).

    Args:
        reason_codes: Nicht-leere Sequenz der ausloesenden Gruende.
        detail: Optionale menschenlesbare Zusatzbeschreibung.

    Raises:
        ValueError: Wenn ``reason_codes`` leer ist (FAIL-CLOSED: ein Reject ohne
            Grund ist ein Modellfehler).
    """

    def __init__(
        self,
        reason_codes: tuple[IncidentRejectReason, ...],
        *,
        detail: str | None = None,
    ) -> None:
        if not reason_codes:
            raise ValueError("IncidentRejectedError requires at least one reason_code")
        self.reason_codes: tuple[IncidentRejectReason, ...] = tuple(reason_codes)
        self.detail = detail
        codes = ", ".join(code.value for code in self.reason_codes)
        message = f"incident candidate rejected: {codes}"
        if detail:
            message = f"{message} ({detail})"
        super().__init__(message)


__all__ = [
    "FailureCorpusError",
    "IncidentRejectReason",
    "IncidentRejectedError",
]
