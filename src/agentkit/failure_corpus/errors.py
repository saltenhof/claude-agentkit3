"""Typisierte Exceptions des Failure-Corpus-BC (FK-41 §41.4).

FAIL-CLOSED: IngressCriteria-Reject ist eine Exception mit strukturierten
``reason_codes`` — kein stilles Verwerfen (Guardrail FAIL CLOSED, AG3-028 AK#3).
"""

from __future__ import annotations

from enum import StrEnum


class IncidentRejectReason(StrEnum):
    """Strukturierter Grund, warum die IngressCriteria einen Kandidaten verwirft.

    Attributes:
        BELOW_MIN_SEVERITY: Kandidat unterschreitet die konfigurierte
            Mindest-Severity.
        DUPLICATE_WINDOW: Identischer Kandidat (source_bc + story_id + summary)
            innerhalb des Dedup-Fensters bereits erfasst.
        NOT_BLOCKING: Kandidat traegt keinen blockierenden/relevanten Befund.
    """

    BELOW_MIN_SEVERITY = "below_min_severity"
    DUPLICATE_WINDOW = "duplicate_window"
    NOT_BLOCKING = "not_blocking"


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
