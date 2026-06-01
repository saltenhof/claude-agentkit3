"""Typisierte Exceptions des Failure-Corpus-BC (DK-07 §7.3.6 / FK-41 §41.4.3).

FAIL-CLOSED: IngressCriteria-Reject ist eine Exception mit strukturierten
``reason_codes`` — kein stilles Verwerfen (Guardrail FAIL CLOSED, AG3-028 AK#3).

ZERO DEBT (Codex-r2 Remediation): jeder ``IncidentRejectReason`` ist von der
``IngressCriteria``-Implementierung tatsaechlich erreichbar; es gibt keinen
toten reason_code mehr. Das frühere ``BELOW_MIN_SEVERITY`` ist entfernt — DK-07
§7.3.6 ist explizit ein reines ODER (Severity ist KEIN harter Floor mehr).
"""

from __future__ import annotations

from enum import StrEnum


class IncidentRejectReason(StrEnum):
    """Strukturierter Grund, warum die IngressCriteria einen Kandidaten verwirft.

    Die reason_codes spiegeln exakt die implementierten DK-07-§7.3.6-Kriterien
    (reines ODER der vier Aufnahme-Trigger) plus die Exact-Duplicate-Dedup.

    Attributes:
        NOT_SIGNIFICANT: KEINES der vier DK-07-§7.3.6-Aufnahmekriterien greift —
            d.h. severity < MEDIUM UND nicht Merge-blockiert UND Rework <= 30min
            UND der Fehlertyp ist bereits im Corpus (nicht neu). Reines ODER:
            ein einziges erfülltes Kriterium genügt zur Aufnahme.
        DUPLICATE_WINDOW: Exakter Duplikat eines bereits im Zeitfenster
            persistierten Incidents (Dedup; separater Reject-Grund).
    """

    NOT_SIGNIFICANT = "not_significant"
    DUPLICATE_WINDOW = "duplicate_window"


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
