"""Pure parsing helpers for :mod:`structured_evaluator` (FK-34 / FK-11 §11.4).

Module-level, class-free helpers extracted from
:mod:`agentkit.backend.verify_system.llm_evaluator.structured_evaluator` so that file's
top-level LOC stays under the ``PY_MODULE_TOP_LEVEL_MAX_LOC_100`` ceiling. All
functions here are pure (no class state, no side effects) and behaviour-identical
to their prior in-place definitions:

* the finding-resolution id codec (``_finding_resolution_id`` /
  ``_parse_finding_resolution_key``) and its dedicated constants,
* the LLM resolution wire-string map ``_RESOLUTION_WIRE``,
* the Stage-2 ``_extract_json_fence`` non-backtracking fence extractor (S5852),
* the Stage-3 free-text regex helpers (``_extract_check_near_id`` /
  ``_sequential_status_checks``),
* the verdict aggregator ``_verdict``,
* the fail-closed :class:`StructuredEvaluatorError` (kept with the parsing code
  it is raised from; re-exported by ``structured_evaluator`` for the public API).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from agentkit.backend.verify_system.errors import VerifySystemError
from agentkit.backend.verify_system.llm_evaluator.roles import LlmVerdict
from agentkit.backend.verify_system.remediation.finding_resolution import (
    FindingKey,
    FindingResolutionStatus,
    finding_key,
)

if TYPE_CHECKING:
    import re

    from agentkit.backend.verify_system.protocols import Finding


class StructuredEvaluatorError(VerifySystemError):
    """Raised when the LLM response is not a valid evaluation result (fail-closed).

    FK-34 §34.5.1: an unparseable or schema-violating response is a hard FAIL,
    never a silent skip. Covers non-JSON output, wrong top-level type, unknown
    check-ids, illegal status values, and (in remediation mode) a missing or
    invalid ``resolution`` field on a finding-resolution check.
    """


#: Prefix of a remediation finding-resolution check-id (FK-34 §34.9.5).
_FINDING_RESOLUTION_PREFIX: Final[str] = "finding_resolution_"

#: Separator between ``layer`` and ``check`` inside a finding-resolution id.
#: The resolution check-id is ``finding_resolution_{layer}:{check}`` so it
#: round-trips to the canonical AG3-041 ``FindingKey = (layer, check)`` -- the
#: ONE resolution-map key (E5). ``layer`` (a role value, e.g. ``qa_review``)
#: and ``check`` (e.g. ``ac_fulfilled``) never contain ``:``.
_FINDING_KEY_SEP: Final[str] = ":"

#: A ``layer:check`` key splits into exactly this many parts.
_FINDING_KEY_PARTS: Final[int] = 2

#: LLM resolution wire-string -> FindingResolutionStatus (FK-34 §34.9.4).
_RESOLUTION_WIRE: Final[dict[str, FindingResolutionStatus]] = {
    "fully_resolved": FindingResolutionStatus.FULLY_RESOLVED,
    "partially_resolved": FindingResolutionStatus.PARTIALLY_RESOLVED,
    "not_resolved": FindingResolutionStatus.NOT_RESOLVED,
}

#: Literal ```` ```json ```` fence opener (Stage 2).
_JSON_FENCE_OPEN: Final[str] = "```json"
#: Literal ```` ``` ```` fence closer (Stage 2).
_FENCE_CLOSE: Final[str] = "```"


def _finding_resolution_id(finding: Finding) -> str:
    """Return the ``{layer}:{check}`` id encoding a finding's canonical key.

    Args:
        finding: The previous-round finding to encode.

    Returns:
        ``"{layer}:{check}"`` -- the suffix of the ``finding_resolution_*``
        check-id, decodable back to the AG3-041 ``FindingKey``.
    """
    layer, check = finding_key(finding)
    return f"{layer}{_FINDING_KEY_SEP}{check}"


def _parse_finding_resolution_key(suffix: str) -> FindingKey:
    """Decode a ``finding_resolution_`` suffix into a ``FindingKey``.

    Args:
        suffix: The id suffix after the ``finding_resolution_`` prefix, of the
            form ``{layer}:{check}``.

    Returns:
        The ``(layer, check)`` :data:`FindingKey`.

    Raises:
        StructuredEvaluatorError: If the suffix is not exactly ``layer:check``
            (fail-closed: no malformed resolution id silently accepted).
    """
    parts = suffix.split(_FINDING_KEY_SEP)
    if len(parts) != _FINDING_KEY_PARTS or not parts[0] or not parts[1]:
        msg = (
            f"finding-resolution id suffix {suffix!r} is not a valid "
            f"'layer:check' key (FK-34 §34.9.5 fail-closed)."
        )
        raise StructuredEvaluatorError(msg)
    return (parts[0], parts[1])


def _extract_json_fence(text: str) -> str | None:
    """Extract the inside of a ```` ```json ... ``` ```` fence (non-backtracking).

    Replaces the prior ``re.search(r"```json\\s*(.*?)```", text, re.DOTALL)``
    (S5852 catastrophic-backtracking risk) with a linear string-index scan that
    yields the EXACT same candidate the regex produced: find the ```` ```json ````
    opener, skip the whitespace that followed it (regex ``\\s*``), then take the
    slice up to the next ```` ``` ```` closer and ``.strip()`` it (regex group
    capture + caller ``.strip()``).

    Args:
        text: The (already stripped) raw LLM completion text.

    Returns:
        The stripped fenced content, or ``None`` when no closed ```` ```json ````
        fence is present.
    """
    open_at = text.find(_JSON_FENCE_OPEN)
    if open_at == -1:
        return None
    inner_start = open_at + len(_JSON_FENCE_OPEN)
    # Regex ``\s*`` consumed the whitespace after ``json`` before the lazy group.
    while inner_start < len(text) and text[inner_start].isspace():
        inner_start += 1
    close_at = text.find(_FENCE_CLOSE, inner_start)
    if close_at == -1:
        return None
    return text[inner_start:close_at].strip()


def _extract_check_near_id(
    text: str,
    check_id: str,
    *,
    status_pattern: re.Pattern[str],
    reason_pattern: re.Pattern[str],
    desc_pattern: re.Pattern[str],
) -> dict[str, object] | None:
    """Extract one free-text check block anchored at a known check id."""
    cid_pos = text.find(check_id)
    if cid_pos == -1:
        return None
    region = text[max(0, cid_pos - 50) : cid_pos + 500]
    status_match = status_pattern.search(region)
    if not status_match:
        return None
    status_raw = status_match.group(1).upper()
    if status_raw not in {"PASS", "FAIL", "PASS_WITH_CONCERNS"}:
        return None
    reason_match = reason_pattern.search(region)
    desc_match = desc_pattern.search(region)
    return {
        "check_id": check_id,
        "status": status_raw,
        "reason": reason_match.group(1) if reason_match else "",
        "description": desc_match.group(1) if desc_match else "",
    }


def _sequential_status_checks(
    text: str,
    sorted_ids: list[str],
    status_pattern: re.Pattern[str],
) -> list[dict[str, object]]:
    """Map positional free-text status mentions to sorted check ids."""
    statuses = status_pattern.findall(text)
    if len(statuses) < len(sorted_ids):
        return []
    return [
        {
            "check_id": check_id,
            "status": statuses[idx].upper(),
            "reason": "",
            "description": "",
        }
        for idx, check_id in enumerate(sorted_ids)
    ]


def _verdict(has_blocking: bool, has_concern: bool) -> LlmVerdict:
    """Aggregate the per-check outcome into a role verdict (FK-34 §34.2.5).

    Args:
        has_blocking: Whether any FAIL (or open finding-resolution) was seen.
        has_concern: Whether any PASS_WITH_CONCERNS was seen.

    Returns:
        ``FAIL`` if blocking, else ``PASS_WITH_CONCERNS`` if concerns, else ``PASS``.
    """
    if has_blocking:
        return LlmVerdict.FAIL
    if has_concern:
        return LlmVerdict.PASS_WITH_CONCERNS
    return LlmVerdict.PASS


__all__ = [
    "StructuredEvaluatorError",
    "_extract_check_near_id",
    "_extract_json_fence",
    "_finding_resolution_id",
    "_parse_finding_resolution_key",
    "_sequential_status_checks",
    "_verdict",
]
