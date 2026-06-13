"""PatternPromotion sub of the failure-corpus BC (FK-41 §41.5, AG3-078).

Deterministic clustering of OBSERVED incidents into PatternCandidates and
human-gated confirmation (``confirm_pattern``) into ACCEPTED FailurePatternRecords.

Cluster key: ``(FailureCategory, symptom_signature)``
``symptom_signature`` = deterministic SHA-256-based hash of the normalized symptom text
(NFKC + ASCII fold + lowercase + tokenize on [^a-z0-9]+ + sort + hex[:16]).

Three promotion rules (FK-41 §41.5.1), evaluated by priority HIGH_SEVERITY > REPETITION >
FAVORABLE_CHECKABILITY. Clusters satisfying none of the three rules produce no candidate.

Sources:
- FK-41 §41.5 -- PatternPromotion
- FK-41 §41.5.1 -- three promotion rules
- FK-41 §41.5.3 -- confirm_pattern (human gate)
- FK-41 §41.6.3 -- CATEGORY_TO_CHECK_TYPE mapping (used for FAVORABLE_CHECKABILITY)
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from agentkit.core_types import CheckType, FailureCategory, IncidentStatus, PatternStatus
from agentkit.failure_corpus.check_proposal import FalsePositiveRisk
from agentkit.failure_corpus.pattern import FailurePatternRecord, PatternRiskLevel, PromotionRule
from agentkit.failure_corpus.top import PatternCandidate, PatternDecision
from agentkit.failure_corpus.types import IncidentSeverity, PatternId

if TYPE_CHECKING:
    from agentkit.failure_corpus.incident import Incident
    from agentkit.state_backend.store.fc_pattern_repository import FcPatternRepository
    from agentkit.telemetry.projection_accessor import (
        ProjectionAccessor,
    )

# ---------------------------------------------------------------------------
# FK-41 §41.6.3 Kategorie → Check-Typ Matrix (normierte Konstante, getestet)
# ---------------------------------------------------------------------------

#: FK-41 §41.6.3 canonical mapping FailureCategory → CheckType (deterministic;
#: used in FAVORABLE_CHECKABILITY rule and in CheckFactory step 2).
CATEGORY_TO_CHECK_TYPE: dict[FailureCategory, CheckType] = {
    FailureCategory.SCOPE_DRIFT: CheckType.CHANGED_FILE_POLICY,
    FailureCategory.UNSAFE_REFACTOR: CheckType.CHANGED_FILE_POLICY,
    FailureCategory.EVIDENCE_FABRICATION: CheckType.ARTIFACT_COMPLETENESS,
    FailureCategory.REVIEW_EVASION: CheckType.ARTIFACT_COMPLETENESS,
    FailureCategory.REQUIREMENTS_MISS: CheckType.ARTIFACT_COMPLETENESS,
    FailureCategory.TEST_OMISSION: CheckType.TEST_OBLIGATION,
    FailureCategory.ASSERTION_WEAKNESS: CheckType.TEST_OBLIGATION,
    FailureCategory.POLICY_VIOLATION: CheckType.SENSITIVE_PATH_GUARD,
    FailureCategory.TOOL_MISUSE: CheckType.SENSITIVE_PATH_GUARD,
    FailureCategory.ARCHITECTURE_VIOLATION: CheckType.FORBIDDEN_DEPENDENCY,
    FailureCategory.HALLUCINATION: CheckType.FIXTURE_REPLAY,
    FailureCategory.STATE_DESYNC: CheckType.FIXTURE_REPLAY,
}

#: FK-41 §41.5.1 / §2.1.1 CHECK_TYPE_FALSE_POSITIVE_RISK matrix (named, tested constant).
#: Determines FAVORABLE_CHECKABILITY: only CheckTypes with LOW FP risk qualify.
CHECK_TYPE_FALSE_POSITIVE_RISK: dict[CheckType, FalsePositiveRisk] = {
    CheckType.CHANGED_FILE_POLICY: FalsePositiveRisk.LOW,
    CheckType.SENSITIVE_PATH_GUARD: FalsePositiveRisk.LOW,
    CheckType.FORBIDDEN_DEPENDENCY: FalsePositiveRisk.LOW,
    CheckType.ARTIFACT_COMPLETENESS: FalsePositiveRisk.MEDIUM,
    CheckType.TEST_OBLIGATION: FalsePositiveRisk.MEDIUM,
    CheckType.FIXTURE_REPLAY: FalsePositiveRisk.HIGH,
}

#: Promotion window in days for REPETITION rule (FK-41 §41.5.1).
_REPETITION_WINDOW_DAYS = 30

#: Minimum incidents for REPETITION rule.
_REPETITION_MIN_COUNT = 3

#: Minimum incidents for FAVORABLE_CHECKABILITY rule.
_FAVORABLE_CHECKABILITY_MIN_COUNT = 2

# Regex for tokenizing symptom text (all non-alphanumeric as separator).
_TOKEN_SPLIT_RE = re.compile(r"[^a-z0-9]+")


def compute_symptom_signature(symptom: str) -> str:
    """Deterministic SHA-256 hash of normalized symptom text (FK-41 §2.1.1).

    Normalization pipeline (exactly as specified, no stopwords):
    1. Unicode NFKC normalization.
    2. ASCII fold (map non-ASCII to nearest ASCII, discard the rest).
    3. Lowercase.
    4. Tokenize on ``[^a-z0-9]+`` (all non-word chars as separator; digits kept).
    5. Discard empty tokens. NO stopword removal.
    6. Sort tokens lexicographically and join with single space.
    7. SHA-256 of UTF-8 bytes; return first 16 hex chars (8 bytes).

    Args:
        symptom: Raw symptom free-text from an Incident.

    Returns:
        16-character hex string (the symptom_signature).
    """
    # Step 1: NFKC normalization (canonical compatibility decomposition)
    normalized = unicodedata.normalize("NFKC", symptom)
    # Step 2: ASCII fold — NFD decompose to split base+combining, then encode ASCII
    # (drops combining marks, maps accented chars to nearest ASCII, e.g. café→cafe)
    decomposed = unicodedata.normalize("NFD", normalized)
    ascii_text = decomposed.encode("ascii", errors="ignore").decode("ascii")
    # Step 3: Lowercase
    lowered = ascii_text.lower()
    # Step 4+5: Tokenize and discard empty tokens
    tokens = [t for t in _TOKEN_SPLIT_RE.split(lowered) if t]
    # Step 6: Sort lexicographically and join
    joined = " ".join(sorted(tokens))
    # Step 7: SHA-256 hex[:16]
    digest = hashlib.sha256(joined.encode("utf-8")).hexdigest()
    return digest[:16]


def _check_type_for_category(category: FailureCategory) -> CheckType:
    """Return the deterministic CheckType for a FailureCategory (FK-41 §41.6.3).

    Args:
        category: The failure category.

    Returns:
        The mapped CheckType.
    """
    return CATEGORY_TO_CHECK_TYPE[category]


def _fp_risk_for_category(category: FailureCategory) -> FalsePositiveRisk:
    """Return the FalsePositiveRisk for a category via the two-step matrix lookup.

    Args:
        category: The failure category.

    Returns:
        The FalsePositiveRisk for the category's mapped CheckType.
    """
    check_type = _check_type_for_category(category)
    return CHECK_TYPE_FALSE_POSITIVE_RISK[check_type]


class _ClusterKey:
    """Cluster key (FailureCategory, symptom_signature)."""

    __slots__ = ("category", "symptom_signature")

    def __init__(self, category: FailureCategory, symptom_signature: str) -> None:
        self.category = category
        self.symptom_signature = symptom_signature

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, _ClusterKey):
            return NotImplemented
        return self.category == other.category and self.symptom_signature == other.symptom_signature

    def __hash__(self) -> int:
        return hash((self.category, self.symptom_signature))


def _determine_promotion_rule(
    incidents: list[Incident],
    category: FailureCategory,
    *,
    now: datetime | None = None,
) -> PromotionRule | None:
    """Determine which promotion rule (if any) applies to a cluster.

    Applies priority: HIGH_SEVERITY > REPETITION > FAVORABLE_CHECKABILITY.

    Args:
        incidents: All incidents in the cluster, sorted oldest-first.
        category: The cluster's FailureCategory.
        now: Optional injectable clock for deterministic tests.

    Returns:
        The applicable ``PromotionRule``, or ``None`` if no rule is satisfied.
    """
    _now = now or datetime.now(UTC)

    # HIGH_SEVERITY: >= 1 incident with HIGH or CRITICAL severity
    high_severity = {IncidentSeverity.HIGH, IncidentSeverity.CRITICAL}
    if any(inc.severity in high_severity for inc in incidents):
        return PromotionRule.HIGH_SEVERITY

    # REPETITION: >= 3 incidents within 30-day window
    cutoff = _now - timedelta(days=_REPETITION_WINDOW_DAYS)
    recent = [
        inc for inc in incidents
        if (
            (inc.recorded_at.tzinfo is None and inc.recorded_at >= cutoff.replace(tzinfo=None))
            or (inc.recorded_at.tzinfo is not None and inc.recorded_at >= cutoff)
        )
    ]
    if len(recent) >= _REPETITION_MIN_COUNT:
        return PromotionRule.REPETITION

    # FAVORABLE_CHECKABILITY: >= 2 incidents AND category maps to LOW FP risk
    if (
        len(incidents) >= _FAVORABLE_CHECKABILITY_MIN_COUNT
        and _fp_risk_for_category(category) is FalsePositiveRisk.LOW
    ):
        return PromotionRule.FAVORABLE_CHECKABILITY

    return None


class PatternPromotion:
    """PatternPromotion sub of the failure-corpus BC (FK-41 §41.5, AG3-078).

    Clusters OBSERVED incidents into PatternCandidates (``suggest_patterns``)
    and handles human confirmation (``confirm_pattern``).

    Args:
        accessor: ProjectionAccessor for reading incidents and writing patterns.
        pattern_repo: Repository adapter for ``fc_patterns``.
        project_key: Project key (mandatory; all FC reads are project-bound).
    """

    def __init__(
        self,
        accessor: ProjectionAccessor,
        pattern_repo: FcPatternRepository,
        project_key: str,
    ) -> None:
        self._accessor = accessor
        self._pattern_repo = pattern_repo
        self._project_key = project_key

    def suggest_patterns(
        self, *, _now: datetime | None = None
    ) -> list[PatternCandidate]:
        """Cluster OBSERVED incidents into PatternCandidates (FK-41 §41.5, AG3-078).

        Reads all FC_INCIDENTS with status OBSERVED for this project, clusters
        them by (FailureCategory, symptom_signature), applies the three promotion
        rules, and returns PatternCandidate objects for qualifying clusters.

        Clusters satisfying no rule produce no candidate. Results are sorted by
        oldest recorded_at in the cluster (tie-breaker: stable order).

        Args:
            _now: Optional injectable UTC clock for the REPETITION window test.

        Returns:
            List of ``PatternCandidate`` objects, one per qualifying cluster.
        """
        from agentkit.failure_corpus.incident import Incident
        from agentkit.telemetry.projection_accessor import ProjectionFilter, ProjectionKind

        # Read all OBSERVED incidents for this project
        all_incidents = self._accessor.read_projection(
            ProjectionKind.FC_INCIDENTS,
            ProjectionFilter(project_key=self._project_key),
        )

        # Filter to OBSERVED status only
        observed = [
            inc for inc in all_incidents
            if isinstance(inc, Incident) and inc.incident_status is IncidentStatus.OBSERVED
        ]

        # Cluster by (category, symptom_signature)
        clusters: dict[_ClusterKey, list[Incident]] = {}
        for inc in observed:
            sig = compute_symptom_signature(inc.symptom)
            key = _ClusterKey(inc.category, sig)
            clusters.setdefault(key, []).append(inc)

        # Sort each cluster oldest-first (stable tie-breaker)
        for inc_list in clusters.values():
            inc_list.sort(key=lambda i: i.recorded_at)

        # Generate candidates for qualifying clusters
        candidates: list[PatternCandidate] = []
        # Sort clusters by earliest incident for stable output order
        sorted_clusters = sorted(
            clusters.items(),
            key=lambda kv: kv[1][0].recorded_at,
        )
        for key, inc_list in sorted_clusters:
            rule = _determine_promotion_rule(inc_list, key.category, now=_now)
            if rule is None:
                continue
            # Build a PatternCandidate (richer model with clustering info)
            candidate = PatternCandidate(
                pattern_id=PatternId(f"FP-{len(candidates) + 1:04d}"),
                category=key.category,
                symptom_signature=key.symptom_signature,
                promotion_rule=rule,
                incident_refs=[inc.incident_id for inc in inc_list],
                invariant_candidate=_derive_invariant_candidate(inc_list),
            )
            candidates.append(candidate)
        return candidates

    def confirm_pattern(
        self,
        pattern_id: PatternId,
        decision: PatternDecision,
        *,
        invariant: str | None = None,
        risk_level: PatternRiskLevel | None = None,
        promotion_rule: PromotionRule | None = None,
        incident_refs: list[str] | None = None,
        category: FailureCategory | None = None,
    ) -> FailurePatternRecord:
        """Human confirmation of a pattern candidate (FK-41 §41.5.3, AG3-078).

        ACCEPTED: persists a FailurePatternRecord with status ACCEPTED,
        confirmed_by='human', and the provided metadata.
        REJECTED: persists a FailurePatternRecord with status REJECTED.
        "Pattern without check is a read-only artefact" (FK-41 §41.5.5).

        Args:
            pattern_id: Pattern identity (FP-NNNN).
            decision: Human decision (ACCEPTED or REJECTED).
            invariant: Invariant text (required for ACCEPTED; ignored for REJECTED).
            risk_level: Risk level (required for ACCEPTED; defaults to MEDIUM for REJECTED).
            promotion_rule: Promotion rule (required for ACCEPTED; defaults to REPETITION for REJECTED).
            incident_refs: Incident references for the pattern.
            category: Failure category (required for ACCEPTED).

        Returns:
            The persisted ``FailurePatternRecord``.

        Raises:
            ValueError: If ACCEPTED but required fields (invariant, risk_level,
                promotion_rule, category) are missing.
        """
        now = datetime.now(UTC)

        if decision is PatternDecision.ACCEPTED:
            if invariant is None:
                raise ValueError("invariant is required for ACCEPTED pattern")
            if risk_level is None:
                raise ValueError("risk_level is required for ACCEPTED pattern")
            if promotion_rule is None:
                raise ValueError("promotion_rule is required for ACCEPTED pattern")
            if category is None:
                raise ValueError("category is required for ACCEPTED pattern")
            record = FailurePatternRecord(
                pattern_id=str(pattern_id),
                project_key=self._project_key,
                status=PatternStatus.ACCEPTED,
                category=category,
                invariant=invariant,
                incident_refs=incident_refs or [],
                promotion_rule=promotion_rule,
                risk_level=risk_level,
                incident_count=len(incident_refs or []),
                confirmed_at=now,
                confirmed_by="human",
            )
        else:
            # REJECTED — minimal record, no active pipeline effect
            record = FailurePatternRecord(
                pattern_id=str(pattern_id),
                project_key=self._project_key,
                status=PatternStatus.REJECTED,
                category=category or FailureCategory.SCOPE_DRIFT,
                invariant=invariant or "(rejected)",
                incident_refs=incident_refs or [],
                promotion_rule=promotion_rule or PromotionRule.REPETITION,
                risk_level=risk_level or PatternRiskLevel.MEDIUM,
                incident_count=len(incident_refs or []),
            )

        self._pattern_repo.save(record)
        return record


def _derive_invariant_candidate(incidents: list[Incident]) -> str:
    """Derive a simple invariant candidate from a cluster of incidents (helper).

    Heuristic: join unique symptom texts as a candidate invariant statement.
    The LLM sharpening step (step 1 of CheckFactory) refines this later.

    Args:
        incidents: Incidents in the cluster.

    Returns:
        A candidate invariant string (may be refined by LLM in step 1).
    """
    if not incidents:
        return "(no incidents)"
    symptoms = list(dict.fromkeys(inc.symptom for inc in incidents))
    if len(symptoms) == 1:
        return symptoms[0]
    # Keep first symptom as the primary, list others as variants
    primary = symptoms[0]
    return f"{primary} (variants: {'; '.join(symptoms[1:3])})"


__all__ = [
    "CATEGORY_TO_CHECK_TYPE",
    "CHECK_TYPE_FALSE_POSITIVE_RISK",
    "PatternPromotion",
    "compute_symptom_signature",
]
