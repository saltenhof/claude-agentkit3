"""IncidentTriage sub of the failure-corpus BC (FK-41 §41.4 / DK-07 §7.3.6).

Three deterministic steps (AG3-028 AK#5):
1. IngressCriteria   -- admission criteria DK-07 §7.3.6 (FAIL-CLOSED via
   IncidentRejectedError)
2. IncidentNormalizer -- whitespace/length normalization + recorded_at
3. IncidentWriterPort.record_fc_incident(draft) -> IncidentId

Persistence and reading run exclusively via the injected ports
(FK-69 §69.9). ``failure_corpus`` imports NO ``state_backend.store`` (AC#6).

IngressCriteria combinator semantics (DK-07 §7.3.6 — Codex-r2 remediation):
  DK-07 §7.3.6 is authoritative and explicitly a **pure OR**. An incident is
  admitted if AT LEAST ONE of the four criteria holds:

    ADMIT  <=>  severity >= MEDIUM
                OR merge_blocked
                OR rework_minutes > 30
                OR is_novel (corpus novelty)

  - Severity is NO hard floor anymore: e.g. ``LOW + merge_blocked`` is
    admitted (the former AND-floor rejected that wrongly).
  - REJECT (``NOT_SIGNIFICANT``) exactly when NONE of the four criteria apply.
  - Additionally (separate, before the OR check): exact duplicate within the
    time window -> REJECT ``DUPLICATE_WINDOW`` (dedup; keeps the corpus small).
  - Corpus novelty (``is_novel``) is checked against the persisted
    ``fc_incidents`` (same (project_key, category) not yet present -> novel).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentkit.failure_corpus.errors import IncidentRejectedError, IncidentRejectReason
from agentkit.failure_corpus.incident import IncidentCandidate, IncidentDraft
from agentkit.failure_corpus.types import IncidentId, IncidentSeverity

if TYPE_CHECKING:
    from agentkit.failure_corpus.ports import IncidentWriterPort, ProjectionReaderPort

# Ordering of the incident severity levels for the minimum-severity comparison.
_SEVERITY_RANK: dict[IncidentSeverity, int] = {
    IncidentSeverity.LOW: 0,
    IncidentSeverity.MEDIUM: 1,
    IncidentSeverity.HIGH: 2,
    IncidentSeverity.CRITICAL: 3,
}

# Default minimum severity (FK-41 §41.4.3: at least "medium" == MEDIUM).
_DEFAULT_MIN_SEVERITY = IncidentSeverity.MEDIUM
# Rework threshold (FK-41 §41.4.3: "over 30 minutes").
_REWORK_THRESHOLD_MIN = 30


def _now() -> datetime:
    """Current UTC timestamp (side effect at the edge of the triage)."""
    return datetime.now(tz=UTC)


class IncidentNormalizer:
    """Default normalization of an incident candidate (FK-41 §41.4).

    Does NOT sharpen the category (``category`` is required in the candidate),
    but normalizes ``symptom`` (whitespace collapse, trim, length cap) and sets
    ``recorded_at``.

    Args:
        max_symptom_length: Maximum length of the normalized ``symptom``.
    """

    def __init__(self, *, max_symptom_length: int = 2000) -> None:
        self._max_symptom_length = max_symptom_length

    def normalize_symptom(self, symptom: str) -> str:
        """Whitespace collapse + trim + length cap (deterministic).

        Used both when producing the draft and for the dedup signature (exact
        duplicate), so that both normalize identically.

        Args:
            symptom: Raw symptom text.

        Returns:
            Normalized symptom text.
        """
        return " ".join(symptom.split())[: self._max_symptom_length]

    def normalize(
        self,
        candidate: IncidentCandidate,
        *,
        recorded_at: datetime,
    ) -> IncidentDraft:
        """Produce a normalized ``IncidentDraft`` (still without an id).

        Args:
            candidate: Incoming candidate.
            recorded_at: Recording timestamp (set by the triage).

        Returns:
            Normalized ``IncidentDraft`` (status ``OBSERVED``); ``incident_id``
            is only assigned DB-side within the write transaction.
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
    """Admission criteria for incident candidates (DK-07 §7.3.6).

    Combinator semantics (see module docstring): pure OR. ADMIT iff
    ``severity >= min_severity`` OR ``merge_blocked`` OR ``rework > 30`` OR
    ``is_novel``. Rejection is FAIL-CLOSED via ``IncidentRejectedError`` with
    reachable ``reason_codes`` — no silent ignoring. Additionally, an exact
    duplicate (``is_duplicate``) is rejected separately as ``DUPLICATE_WINDOW``.

    Args:
        min_severity: Severity threshold of the first OR criterion (default
            ``MEDIUM``; DK-07 §7.3.6 "severity at least medium"). NO hard floor —
            just one of four OR criteria.
        rework_threshold_min: Rework threshold in minutes (default 30; DK-07
            §7.3.6 "over 30 minutes").
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
        """Checks the candidate; raises ``IncidentRejectedError`` on reject.

        Args:
            candidate: Candidate to check (incl. gate inputs ``merge_blocked``
                and ``rework_minutes``).
            is_novel: Corpus novelty (DK-07 §7.3.6: error type not yet present in
                the corpus). Determined by the caller from the persisted corpus.
            is_duplicate: Exact duplicate of an incident already persisted within
                the time window (dedup). Determined by the caller.

        Raises:
            IncidentRejectedError: ``DUPLICATE_WINDOW`` on exact duplicate;
                ``NOT_SIGNIFICANT`` when NONE of the four DK-07 §7.3.6 criteria
                apply (pure OR).
        """
        # Dedup first: exact duplicate within the time window -> reject.
        if is_duplicate:
            raise IncidentRejectedError(
                (IncidentRejectReason.DUPLICATE_WINDOW,),
                detail="exact duplicate of an incident already in the time window",
            )

        # Pure OR of the four DK-07 §7.3.6 admission criteria.
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
    """Admission sub of the failure corpus (FK-41 §41.4).

    Args:
        normalizer: Normalizer for accepted candidates.
        criteria: Admission criteria (FK-41 §41.4.3).
        writer: Narrow fc write view onto the ``ProjectionAccessor`` (returns the
            DB-side assigned ``IncidentId``, FK-41 §41.3.1).
        reader: Narrow read view for the corpus novelty (FK-41 §41.4.3).
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
        """Admits a candidate, normalizes and persists it.

        Flow (FK-41 §41.4): determine corpus novelty -> IngressCriteria ->
        Normalizer -> record_fc_incident.

        Args:
            candidate: Incoming incident candidate.

        Returns:
            The DB-side assigned ``IncidentId`` (``FC-YYYY-NNNN``).

        Raises:
            IncidentRejectedError: If the IngressCriteria reject the candidate
                (FAIL-CLOSED, with ``reason_codes``).
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
        """Read the project-bound corpus slice (FAIL-CLOSED).

        FK-41 §41.4.3 / DK-07 §7.3.6: corpus queries are always project-bound.

        Args:
            candidate: The candidate to check.

        Returns:
            The persisted ``fc_incidents`` rows of this project.
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
        """Exact duplicate within the time window (dedup, DK-07 §7.3.6).

        A duplicate is an already persisted incident of the same project with an
        identical business signature (story_id, run_id, category, severity,
        phase, role, model, normalized symptom). ``fc_incidents`` holds only
        incidents of live runs (a full reset purges them, FK-41 §41.3) — the
        persisted corpus IS thus the dedup time window.

        Args:
            candidate: The candidate to check.
            existing: Already read project-bound corpus rows.

        Returns:
            ``True`` if the normalized signature is already in the corpus.
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
        """Business signature of a persisted fc_incidents row (dedup)."""
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
