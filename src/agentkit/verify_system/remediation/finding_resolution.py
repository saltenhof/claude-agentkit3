"""Finding-resolution assessment for remediation rounds (FK-34 / DK-04 §4.6).

In remediation mode the QA-subflow carries the *previous* round's findings as
context (DK-04 §4.6) so the system can judge whether the worker actually fixed
them. :class:`FindingResolutionAssessor` matches previous-round findings against
the current-round findings by their identity key ``(layer, check)`` (the
finding/check id, FK-34) and classifies each previous finding:

* gone from the current round                  -> ``FULLY_RESOLVED``
* still present, but with a *lower* severity    -> ``PARTIALLY_RESOLVED``
* still present with the *same or higher* sev.  -> ``NOT_RESOLVED``

This assessor is the deterministic core that runs BEFORE the Layer-2 LLM call
in remediation mode (FK-34 "Finding-Resolution (Remediation-Runde)"); the full
LLM integration is AG3-043. Here only the matching/classification logic and the
previous-findings context handoff are provided (AG3-041 §2.1.5).

Source:
  - FK-34 -- finding resolution (remediation round), StructuredEvaluator
  - DK-04 §4.6 -- remediation mode with previous-round findings
  - AG3-041 §2.1.5 -- FindingResolutionAssessor, FindingResolutionStatus
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from agentkit.core_types import Severity
from agentkit.verify_system.errors import ResolutionMetadataError

if TYPE_CHECKING:
    from agentkit.verify_system.protocols import Finding

#: Identity key of a finding for cross-round matching: (layer, check).
#: This is the finding/check id pair (FK-34); two findings with the same key
#: address the same defect class regardless of message wording.
FindingKey = tuple[str, str]

#: Metadata key under which a Layer-2 ``LayerResult`` carries the LLM's
#: finding-resolution verdicts (AG3-043 E5). The value is a JSON-friendly
#: ``{"layer:check": status_value}`` map; :func:`resolution_map_from_metadata`
#: decodes it back to the typed ``FindingKey`` map for the closure decision.
LLM_RESOLUTION_METADATA_KEY: str = "finding_resolutions"

#: Separator between ``layer`` and ``check`` in the serialised metadata key.
_FINDING_KEY_SEP: str = ":"

#: A ``layer:check`` key splits into exactly this many parts.
_FINDING_KEY_PARTS: int = 2

#: Severity rank for "reduced severity" comparison. Higher == more severe.
_SEVERITY_RANK: dict[Severity, int] = {
    Severity.MINOR: 1,
    Severity.MAJOR: 2,
    Severity.BLOCKING: 3,
}


class FindingResolutionStatus(StrEnum):
    """Resolution status of a previous-round finding (FK-34 / DK-04 §4.6).

    Attributes:
        FULLY_RESOLVED: The finding no longer appears in the current round.
        PARTIALLY_RESOLVED: Still present, but at a lower severity than before.
        NOT_RESOLVED: Still present at the same or a higher severity.
    """

    FULLY_RESOLVED = "fully_resolved"
    PARTIALLY_RESOLVED = "partially_resolved"
    NOT_RESOLVED = "not_resolved"


def finding_key(finding: Finding) -> FindingKey:
    """Return the cross-round identity key of a finding.

    Args:
        finding: The finding to key.

    Returns:
        The ``(layer, check)`` identity tuple.
    """
    return (finding.layer, finding.check)


@dataclass(frozen=True)
class FindingResolutionAssessor:
    """Classifies previous-round findings against the current round (FK-34)."""

    def assess(
        self,
        previous_findings: tuple[Finding, ...],
        current_findings: tuple[Finding, ...],
    ) -> dict[FindingKey, FindingResolutionStatus]:
        """Classify each previous finding as fully/partially/not resolved.

        Matching is by ``(layer, check)`` identity. When several current
        findings share a key, the *most severe* current finding decides the
        status (fail-closed: a remaining high-severity instance dominates).

        Args:
            previous_findings: Findings from the prior remediation round.
            current_findings: Findings from the just-completed round.

        Returns:
            A mapping from each previous finding's ``(layer, check)`` key to
            its :class:`FindingResolutionStatus`. Keys are de-duplicated; if a
            previous key appears multiple times, the highest previous severity
            is used as the baseline.
        """
        current_max: dict[FindingKey, Severity] = {}
        for finding in current_findings:
            key = finding_key(finding)
            existing = current_max.get(key)
            if existing is None or _rank(finding.severity) > _rank(existing):
                current_max[key] = finding.severity

        previous_max: dict[FindingKey, Severity] = {}
        for finding in previous_findings:
            key = finding_key(finding)
            existing = previous_max.get(key)
            if existing is None or _rank(finding.severity) > _rank(existing):
                previous_max[key] = finding.severity

        statuses: dict[FindingKey, FindingResolutionStatus] = {}
        for key, prev_sev in previous_max.items():
            statuses[key] = _classify(prev_sev, current_max.get(key))
        return statuses

    def has_unresolved(
        self,
        previous_findings: tuple[Finding, ...],
        current_findings: tuple[Finding, ...],
    ) -> bool:
        """Return whether any previous finding is still OPEN (blocking).

        A finding is OPEN — and therefore unresolved/blocking (FK-34 §34.9.4) —
        when its status is ``NOT_RESOLVED`` or ``PARTIALLY_RESOLVED``: a
        partially-resolved finding still carries an unaddressed remainder. Only
        ``FULLY_RESOLVED`` clears. This delegates to the single open-status SSOT
        (:func:`resolution_map_has_open_findings` /
        :data:`_OPEN_RESOLUTION_STATUSES`), keeping one truth across
        ``has_unresolved``, ``RemediationFeedback.has_open_findings`` and the
        closure-block derivation (no second truth, FIX THE MODEL).

        Args:
            previous_findings: Findings from the prior remediation round.
            current_findings: Findings from the just-completed round.

        Returns:
            ``True`` if at least one previous finding is still ``NOT_RESOLVED``
            or ``PARTIALLY_RESOLVED`` (an open finding); ``False`` otherwise.
        """
        statuses = self.assess(previous_findings, current_findings)
        return resolution_map_has_open_findings(statuses)


#: Resolution statuses that keep a previous-round finding OPEN (blocking).
#: FK-34 §34.9.4 (~Z.692-699): ``partially_resolved`` is blocking — a partially
#: resolved finding still carries an unaddressed remainder. Only
#: ``FULLY_RESOLVED`` clears. This set is the single source of truth for what
#: "open" means; both ``RemediationFeedback.has_open_findings`` and the
#: ``closure_blocked`` derivation in the QA-subflow reference it (no second
#: truth, FIX THE MODEL).
_OPEN_RESOLUTION_STATUSES: frozenset[FindingResolutionStatus] = frozenset(
    (
        FindingResolutionStatus.NOT_RESOLVED,
        FindingResolutionStatus.PARTIALLY_RESOLVED,
    )
)


def is_open_resolution_status(status: FindingResolutionStatus) -> bool:
    """Return whether a resolution status counts as OPEN (blocking).

    Single membership predicate over :data:`_OPEN_RESOLUTION_STATUSES` (FK-34
    §34.9.4): ``NOT_RESOLVED`` and ``PARTIALLY_RESOLVED`` are open, only
    ``FULLY_RESOLVED`` clears. All open-status decisions
    (``has_unresolved``, ``resolution_map_has_open_findings``, the prompt
    rendering in ``RemediationFeedback.to_prompt_text``) funnel through here so
    the open-status set stays a single source of truth (FIX THE MODEL).

    Args:
        status: The resolution status to classify.

    Returns:
        ``True`` iff the status is in :data:`_OPEN_RESOLUTION_STATUSES`.
    """
    return status in _OPEN_RESOLUTION_STATUSES


def resolution_map_has_open_findings(
    resolution_map: dict[FindingKey, FindingResolutionStatus] | None,
) -> bool:
    """Return whether a resolution map carries an OPEN previous finding.

    A finding is OPEN — and therefore blocks closure (FK-34 §34.9.4) — when its
    status is ``NOT_RESOLVED`` or ``PARTIALLY_RESOLVED``. This predicate is the
    authoritative closure-block signal: it is derived purely from the
    finding-resolution assessment and is **independent of the policy verdict**,
    so a PASS verdict with a still-open (e.g. ``PARTIALLY_RESOLVED``) previous
    finding correctly blocks closure (no fail-open toward closure).

    Args:
        resolution_map: The ``(layer, check) -> FindingResolutionStatus`` map
            from :func:`FindingResolutionAssessor.assess`, or ``None`` when not
            in a remediation context (no previous findings).

    Returns:
        ``True`` iff at least one entry is ``NOT_RESOLVED`` or
        ``PARTIALLY_RESOLVED``; ``False`` for ``None``, an empty map, or a map
        whose entries are all ``FULLY_RESOLVED``.
    """
    if not resolution_map:
        return False
    return any(
        is_open_resolution_status(status) for status in resolution_map.values()
    )


def serialize_resolution_map(
    resolution_map: dict[FindingKey, FindingResolutionStatus],
) -> dict[str, str]:
    """Serialise a typed resolution map to a JSON-friendly ``{key: status}`` dict.

    The ``FindingKey`` tuple ``(layer, check)`` is joined to ``"layer:check"``
    so the map round-trips through JSON metadata (tuple keys are not
    JSON-serialisable). :func:`resolution_map_from_metadata` is the inverse.

    Args:
        resolution_map: The typed ``(layer, check) -> status`` map.

    Returns:
        A ``{"layer:check": status_value}`` dict (sorted for determinism).
    """
    return {
        f"{layer}{_FINDING_KEY_SEP}{check}": status.value
        for (layer, check), status in sorted(resolution_map.items())
    }


def resolution_map_from_metadata(
    metadata: dict[str, object] | None,
) -> dict[FindingKey, FindingResolutionStatus]:
    """Decode the LLM resolution map from a Layer-2 ``LayerResult.metadata``.

    Reads the :data:`LLM_RESOLUTION_METADATA_KEY` entry (written by the Layer-2
    integration via :func:`serialize_resolution_map`) and decodes each
    ``"layer:check"`` key back to a typed ``FindingKey`` and each value back to
    a :class:`FindingResolutionStatus`. This is the ONE decode path feeding the
    LLM verdicts into the canonical finding-resolution SSOT (E5).

    Fail-closed (AG3-043 E5): the metadata is produced by our own
    ``serialize_resolution_map`` — a malformed entry is therefore an internal
    pipeline corruption / bug, not external input, and is surfaced as a
    :class:`ResolutionMetadataError` instead of being skipped silently
    (FAIL-CLOSED guardrail). Only the *absence* of any remediation context is
    benign: a ``None``/empty ``metadata`` or an absent
    :data:`LLM_RESOLUTION_METADATA_KEY` entry yields an empty map (no Layer-2
    verdicts in this round). A *present* entry must be a well-formed
    ``{"layer:check": status_value}`` dict; anything else raises.

    Args:
        metadata: A Layer-2 ``LayerResult.metadata`` dict (or ``None``).

    Returns:
        The decoded ``(layer, check) -> status`` map (possibly empty when the
        key is absent).

    Raises:
        ResolutionMetadataError: If the :data:`LLM_RESOLUTION_METADATA_KEY`
            entry is present but malformed (non-dict payload, a key that is not
            a well-formed ``"layer:check"`` pair, a non-string value, or an
            unknown status value).
    """
    if not metadata or LLM_RESOLUTION_METADATA_KEY not in metadata:
        return {}
    raw = metadata[LLM_RESOLUTION_METADATA_KEY]
    if not isinstance(raw, dict):
        raise ResolutionMetadataError(
            f"{LLM_RESOLUTION_METADATA_KEY!r} metadata must be a dict, "
            f"got {type(raw).__name__}"
        )
    decoded: dict[FindingKey, FindingResolutionStatus] = {}
    for key, value in raw.items():
        decoded[_decode_finding_key(key)] = _decode_status(value)
    return decoded


def _decode_finding_key(key: object) -> FindingKey:
    """Decode one serialised ``"layer:check"`` metadata key (fail-closed).

    Args:
        key: The raw mapping key from the resolution metadata.

    Returns:
        The typed ``(layer, check)`` identity tuple.

    Raises:
        ResolutionMetadataError: If ``key`` is not a string or not a
            well-formed ``"layer:check"`` pair with both parts non-empty.
    """
    if not isinstance(key, str):
        raise ResolutionMetadataError(
            f"resolution key must be a string, got {type(key).__name__}"
        )
    parts = key.split(_FINDING_KEY_SEP)
    if len(parts) != _FINDING_KEY_PARTS or not parts[0] or not parts[1]:
        raise ResolutionMetadataError(
            f"resolution key {key!r} is not a well-formed "
            f"'layer{_FINDING_KEY_SEP}check' pair"
        )
    return (parts[0], parts[1])


def _decode_status(value: object) -> FindingResolutionStatus:
    """Decode one serialised resolution status value (fail-closed).

    Args:
        value: The raw mapping value from the resolution metadata.

    Returns:
        The typed :class:`FindingResolutionStatus`.

    Raises:
        ResolutionMetadataError: If ``value`` is not a string or not a known
            :class:`FindingResolutionStatus` value.
    """
    if not isinstance(value, str):
        raise ResolutionMetadataError(
            f"resolution status must be a string, got {type(value).__name__}"
        )
    try:
        return FindingResolutionStatus(value)
    except ValueError as exc:
        raise ResolutionMetadataError(
            f"unknown resolution status value {value!r}"
        ) from exc


def _classify(
    previous_severity: Severity,
    current_severity: Severity | None,
) -> FindingResolutionStatus:
    """Classify a single finding from its previous/current severities.

    Args:
        previous_severity: The finding's severity in the previous round.
        current_severity: The matched current severity, or ``None`` if the
            finding is gone.

    Returns:
        The resolution status.
    """
    if current_severity is None:
        return FindingResolutionStatus.FULLY_RESOLVED
    if _rank(current_severity) < _rank(previous_severity):
        return FindingResolutionStatus.PARTIALLY_RESOLVED
    return FindingResolutionStatus.NOT_RESOLVED


def _rank(severity: Severity) -> int:
    """Return the numeric rank of a severity (higher == more severe).

    Args:
        severity: The severity to rank.

    Returns:
        Integer rank (MINOR=1, MAJOR=2, BLOCKING=3).
    """
    return _SEVERITY_RANK[severity]


__all__ = [
    "LLM_RESOLUTION_METADATA_KEY",
    "FindingKey",
    "FindingResolutionAssessor",
    "FindingResolutionStatus",
    "ResolutionMetadataError",
    "finding_key",
    "is_open_resolution_status",
    "resolution_map_from_metadata",
    "resolution_map_has_open_findings",
    "serialize_resolution_map",
]
