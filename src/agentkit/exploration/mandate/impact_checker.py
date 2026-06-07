"""ImpactExceedanceChecker -- the Klasse-4 impact comparison (FK-25 §25.7).

FK-25 §25.7.1 compares the change-frame's *actual* change impact against the
story's *declared* ``change_impact`` (DK-02 §Issue-Schema / FK-21). When the
actual impact ordinally EXCEEDS the declared one, the mandate is exceeded
(Klasse 4 -- impact escalation, human architecture review).

The four impact levels form a total order (FK-25 §25.7.1 ``IMPACT_LEVELS``):

    LOCAL < COMPONENT < CROSS_COMPONENT < ARCHITECTURE_IMPACT

``exceeded`` is ``rank(actual) > rank(declared)``.

The *declared* impact is the authoritative GitHub-input value carried on the
:class:`~agentkit.story_context_manager.story_model.Story` model; it is passed
into :meth:`ImpactExceedanceChecker.check` by the caller (the phase handler
resolves it via the injected ``DeclaredImpactReader`` boundary port -- there is
NO second source of truth and NO fail-open default; FIX-THE-MODEL).

The *actual* impact is DERIVED from the change-frame here. FK-25 §25.6.2 maps
the change-frame to scope inputs via ``affected_building_blocks.affected`` (there
is no ``affected_modules`` field); the contract-change breadth refines the
estimate. This is a deterministic SIGNAL on non-deterministic worker input
(FK-25 §25.4.1 "Signale, keine Beweise"), not a measured fact.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from pydantic import BaseModel, ConfigDict

from agentkit.story_context_manager.story_model import ChangeImpact

if TYPE_CHECKING:
    from agentkit.exploration.change_frame import ChangeFrame

#: Total order of the four impact levels (FK-25 §25.7.1 ``IMPACT_LEVELS``).
#: The index in this tuple is the ordinal rank used for the ``>`` comparison.
IMPACT_ORDER: Final[tuple[ChangeImpact, ...]] = (
    ChangeImpact.LOCAL,
    ChangeImpact.COMPONENT,
    ChangeImpact.CROSS_COMPONENT,
    ChangeImpact.ARCHITECTURE_IMPACT,
)

#: A change frame touching this many distinct building blocks (or more) is at
#: least COMPONENT-wide (a single block stays LOCAL). Conservative threshold:
#: the actual-impact derivation is a signal, the human decides on escalation.
_COMPONENT_BLOCK_THRESHOLD: Final[int] = 2
#: Touching this many distinct building blocks (or more) signals cross-module
#: reach (CROSS_COMPONENT).
_CROSS_COMPONENT_BLOCK_THRESHOLD: Final[int] = 3
#: Cross-module CONTRACT changes (interfaces/data_model/events/external) at or
#: above this breadth lift the derived impact to ARCHITECTURE_IMPACT: systemic
#: contract surface, not a single component's internals.
_ARCHITECTURE_CONTRACT_THRESHOLD: Final[int] = 4


def impact_rank(impact: ChangeImpact) -> int:
    """Return the ordinal rank of an impact level (FK-25 §25.7.1).

    Args:
        impact: The impact level.

    Returns:
        Its index in :data:`IMPACT_ORDER` (``0`` = LOCAL ... ``3`` =
        ARCHITECTURE_IMPACT). A higher rank is a wider impact.
    """
    return IMPACT_ORDER.index(impact)


class ImpactExceedanceResult(BaseModel):
    """Result of the Klasse-4 impact comparison (FK-25 §25.7).

    Attributes:
        declared: The declared (story-input) change impact.
        actual: The change impact DERIVED from the change-frame (a signal).
        exceeded: ``True`` iff ``rank(actual) > rank(declared)`` -- the actual
            impact ordinally exceeds the declared mandate (Klasse 4).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    declared: ChangeImpact
    actual: ChangeImpact
    exceeded: bool


class ImpactExceedanceChecker:
    """Compare derived vs. declared change impact (FK-25 §25.7, Klasse 4)."""

    def check(
        self, change_frame: ChangeFrame, declared_impact: ChangeImpact
    ) -> ImpactExceedanceResult:
        """Compare the change-frame's derived impact against the declared one.

        Args:
            change_frame: The validated change-frame (actual impact source).
            declared_impact: The authoritative declared change impact from the
                story input (resolved by the caller via ``DeclaredImpactReader``;
                never defaulted here -- absence is a fail-closed caller concern).

        Returns:
            The :class:`ImpactExceedanceResult`. ``exceeded`` is ``True`` iff the
            derived actual impact ordinally exceeds the declared impact.
        """
        actual = self._derive_actual_impact(change_frame)
        exceeded = impact_rank(actual) > impact_rank(declared_impact)
        return ImpactExceedanceResult(
            declared=declared_impact, actual=actual, exceeded=exceeded
        )

    @staticmethod
    def _derive_actual_impact(change_frame: ChangeFrame) -> ChangeImpact:
        """Derive the actual change impact from the change-frame (FK-25 §25.6.2).

        Deterministic SIGNAL (not a measured fact, FK-25 §25.4.1): wider building
        block reach and broader cross-module contract surface raise the level.
        Uses ``affected_building_blocks.affected`` (there is no
        ``affected_modules`` field) and the four ``contract_changes`` arrays.

        Args:
            change_frame: The validated change-frame.

        Returns:
            The derived :class:`ChangeImpact` level.
        """
        affected_count = len(change_frame.affected_building_blocks.affected)
        contracts = change_frame.contract_changes
        contract_breadth = (
            len(contracts.interfaces)
            + len(contracts.data_model)
            + len(contracts.events)
            + len(contracts.external_integrations)
        )
        if (
            affected_count >= _CROSS_COMPONENT_BLOCK_THRESHOLD
            and contract_breadth >= _ARCHITECTURE_CONTRACT_THRESHOLD
        ):
            return ChangeImpact.ARCHITECTURE_IMPACT
        if affected_count >= _CROSS_COMPONENT_BLOCK_THRESHOLD:
            return ChangeImpact.CROSS_COMPONENT
        if affected_count >= _COMPONENT_BLOCK_THRESHOLD:
            return ChangeImpact.COMPONENT
        return ChangeImpact.LOCAL


__all__ = [
    "IMPACT_ORDER",
    "ImpactExceedanceChecker",
    "ImpactExceedanceResult",
    "impact_rank",
]
