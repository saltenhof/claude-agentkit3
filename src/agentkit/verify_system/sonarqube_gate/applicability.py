"""3-state applicability resolution for the ``sonarqube_gate`` (FK-33 §33.6.5).

FK-33 owns this model; the other lifecycle docs defer here. At every
gate point the applicability is resolved BEFORE any green/red evaluation
into exactly one of three states:

* ``APPLICABLE`` iff ``sonarqube.available == true`` AND ``fast is False``
  AND ``story_type in {implementation, bugfix}``.
* ``NOT_APPLICABLE_UNAVAILABLE`` iff ``sonarqube.available == false`` ->
  stage SKIP (no fail-closed).
* ``NOT_APPLICABLE_FAST`` iff ``fast is True`` -> the gate point drops
  out (closure uses the sanity gate; not here).

The fast/standard ``mode`` axis (``fast``) is SEPARATE from the
``execution_route`` (EXECUTION/EXPLORATION/None) path — FK-24 §24.3.3
decouples them. ``fast`` is never an ``execution_route`` value.

Airtight: a deliberately absent Sonar (``available == false``) SKIPs;
a configured-but-unreachable/red/stale Sonar (``available == true``)
stays APPLICABLE and fails closed. Absent is not broken — never fail-open.
"""

from __future__ import annotations

from enum import StrEnum

from agentkit.story_context_manager.types import StoryType

#: Story types for which the gate is applicable (code-producing).
_CODE_PRODUCING_TYPES: frozenset[StoryType] = frozenset(
    {StoryType.IMPLEMENTATION, StoryType.BUGFIX}
)


class SonarApplicability(StrEnum):
    """Resolved applicability state of the ``sonarqube_gate``.

    Attributes:
        APPLICABLE: Gate is evaluated; green->PASS, red/stale/unreachable
            -> fail-closed BLOCK.
        NOT_APPLICABLE_UNAVAILABLE: Sonar deliberately absent
            (``available == false``); stage SKIP, policy proceeds.
        NOT_APPLICABLE_FAST: ``mode == fast``; the gate point drops out.
    """

    APPLICABLE = "APPLICABLE"
    NOT_APPLICABLE_UNAVAILABLE = "NOT_APPLICABLE_UNAVAILABLE"
    NOT_APPLICABLE_FAST = "NOT_APPLICABLE_FAST"


def is_code_producing_story(story_type: StoryType) -> bool:
    """Whether ``story_type`` is code-producing (the gate's applicability axis).

    SSOT for the code-producing set the truth-boundary loader uses to decide
    whether a missing/unresolvable project root is a legitimate, declared
    absence (non-code-producing => skip) or a broken precondition that must
    fail closed (code-producing => never a silent Dim-9 skip, FK-33 §33.6.5).

    Args:
        story_type: The story type under evaluation.

    Returns:
        ``True`` iff the gate ever applies to this story type
        (implementation/bugfix).
    """
    return story_type in _CODE_PRODUCING_TYPES


def resolve_applicability(
    *,
    available: bool,
    fast: bool,
    story_type: StoryType,
) -> SonarApplicability:
    """Resolve the gate applicability (FK-33 §33.6.5, 3 states).

    Precedence is deterministic and airtight (the absent-vs-fast order
    only affects which not-applicable label is returned; both are skips):

    1. ``fast is True`` -> ``NOT_APPLICABLE_FAST`` (gate point drops out
       even when Sonar is available — fast disables Layers 2-4).
    2. ``available == false`` -> ``NOT_APPLICABLE_UNAVAILABLE`` (SKIP).
    3. ``story_type`` not code-producing -> ``NOT_APPLICABLE_UNAVAILABLE``
       (the gate only ever applies to implementation/bugfix).
    4. otherwise -> ``APPLICABLE``.

    Args:
        available: Value of ``sonarqube.available`` (FK-03).
        fast: Whether the run is in ``fast`` mode (FK-24 §24.3.3) — the
            SEPARATE fast/standard axis, NOT ``execution_route``.
        story_type: The story type under evaluation.

    Returns:
        The resolved :class:`SonarApplicability` state.
    """
    if fast:
        return SonarApplicability.NOT_APPLICABLE_FAST
    if not available:
        return SonarApplicability.NOT_APPLICABLE_UNAVAILABLE
    if story_type not in _CODE_PRODUCING_TYPES:
        return SonarApplicability.NOT_APPLICABLE_UNAVAILABLE
    return SonarApplicability.APPLICABLE


__all__ = [
    "SonarApplicability",
    "is_code_producing_story",
    "resolve_applicability",
]
