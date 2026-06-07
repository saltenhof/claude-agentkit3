"""ScopeExplosionDetector -- the Klasse-3 scope-explosion signal (FK-25 §25.6).

FK-25 §25.6 detects a scope explosion from quantitative indicators: when the
implementation scope grows significantly beyond the declared story scope. Two or
more indicators with weight ``HIGH`` trigger Klasse 3 (human story-split
decision, FK-25 §25.6.3).

FK-25 §25.6.2 compares the change-frame against the story spec. The indicators
that the concept marks ``HIGH`` and that are derivable from the change-frame
ALONE (no story-spec comparison; FK-25 §25.4.1 "Signale, keine Beweise") are:

* ``affected_building_blocks`` -- a large number of affected building blocks
  (FK-25 §25.6.2 indicator 1, "Betroffene Bausteine");
* ``unplanned_contracts`` -- a broad cross-array contract-change surface
  (FK-25 §25.6.2 indicator 2, "Ungeplante Schnittstellen");
* ``cross_module_contract`` -- contract changes spread across MULTIPLE contract
  dimensions AND many affected blocks (FK-25 §25.6.2 indicator 3, "Vertrags-
  aenderungen an nicht-deklarierten Modulen").

These are deterministic SIGNALS on non-deterministic worker input. The
thresholds are concept-anchored Richtwerte (FK-25 §25.6.2). >= 2 HIGH indicators
=> ``triggered=True`` (Klasse 3).
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Final

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from agentkit.exploration.change_frame import ChangeFrame

#: A change frame touching more than this many building blocks signals a large
#: footprint (FK-25 §25.6.2 indicator 1 "> 50% mehr als erwartet", here applied
#: change-frame-internally as an absolute Richtwert without the story baseline).
_AFFECTED_BLOCKS_HIGH_THRESHOLD: Final[int] = 5
#: More than this many total contract changes (across the four arrays) signals
#: an unplanned-contract explosion (FK-25 §25.6.2 indicator 2 "> 2 ungeplant").
_UNPLANNED_CONTRACTS_HIGH_THRESHOLD: Final[int] = 4
#: Contract changes spread over at least this many of the four contract
#: dimensions signal cross-module contract reach (FK-25 §25.6.2 indicator 3).
_CROSS_MODULE_CONTRACT_DIMENSIONS: Final[int] = 3
#: Combined with cross-dimension contracts, at least this many affected blocks
#: confirms the cross-module-contract HIGH indicator (FK-25 §25.6.2 indicator 3).
_CROSS_MODULE_AFFECTED_THRESHOLD: Final[int] = 3


class ScopeIndicatorWeight(StrEnum):
    """Indicator weight (FK-25 §25.6.2 "Gewicht"). HIGH indicators count."""

    HIGH = "high"
    MEDIUM = "medium"


class ScopeIndicator(BaseModel):
    """A single quantitative scope-explosion indicator (FK-25 §25.6.2).

    Attributes:
        name: The indicator name (English wire key, ARCH-55).
        weight: ``HIGH`` (counts toward the >= 2 trigger) or ``MEDIUM``.
        value: The measured quantitative value (the signal).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    weight: ScopeIndicatorWeight
    value: int


class ScopeExplosionResult(BaseModel):
    """Result of the Klasse-3 scope-explosion check (FK-25 §25.6).

    Attributes:
        triggered: ``True`` iff >= 2 HIGH indicators fired (Klasse 3).
        indicators: All fired indicators (HIGH and MEDIUM), for the operator
            comparison (FK-25 §25.6.3) and telemetry.
        high_indicators_count: Number of HIGH-weight indicators (>= 2 triggers).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    triggered: bool
    indicators: tuple[ScopeIndicator, ...]
    high_indicators_count: int


#: FK-25 §25.6.2: two or more HIGH indicators => scope explosion (Klasse 3).
_HIGH_TRIGGER_COUNT: Final[int] = 2


class ScopeExplosionDetector:
    """Detect a scope explosion from change-frame indicators (FK-25 §25.6)."""

    def detect(self, change_frame: ChangeFrame) -> ScopeExplosionResult:
        """Compute the quantitative scope-explosion indicators (FK-25 §25.6.2).

        Args:
            change_frame: The validated change-frame.

        Returns:
            The :class:`ScopeExplosionResult`. ``triggered`` is ``True`` iff at
            least two HIGH-weight indicators fired (FK-25 §25.6.2).
        """
        indicators = self._compute_indicators(change_frame)
        high_count = sum(
            1 for ind in indicators if ind.weight is ScopeIndicatorWeight.HIGH
        )
        return ScopeExplosionResult(
            triggered=high_count >= _HIGH_TRIGGER_COUNT,
            indicators=tuple(indicators),
            high_indicators_count=high_count,
        )

    @staticmethod
    def _compute_indicators(change_frame: ChangeFrame) -> list[ScopeIndicator]:
        """Compute the fired indicators (FK-25 §25.6.2 indicators 1-3)."""
        indicators: list[ScopeIndicator] = []
        affected_count = len(change_frame.affected_building_blocks.affected)
        contracts = change_frame.contract_changes
        contract_dimensions = sum(
            1
            for arr in (
                contracts.interfaces,
                contracts.data_model,
                contracts.events,
                contracts.external_integrations,
            )
            if arr
        )
        contract_total = (
            len(contracts.interfaces)
            + len(contracts.data_model)
            + len(contracts.events)
            + len(contracts.external_integrations)
        )

        # Indicator 1 -- affected building blocks (FK-25 §25.6.2 indicator 1).
        if affected_count > _AFFECTED_BLOCKS_HIGH_THRESHOLD:
            indicators.append(
                ScopeIndicator(
                    name="affected_building_blocks",
                    weight=ScopeIndicatorWeight.HIGH,
                    value=affected_count,
                )
            )

        # Indicator 2 -- unplanned contracts (FK-25 §25.6.2 indicator 2).
        if contract_total > _UNPLANNED_CONTRACTS_HIGH_THRESHOLD:
            indicators.append(
                ScopeIndicator(
                    name="unplanned_contracts",
                    weight=ScopeIndicatorWeight.HIGH,
                    value=contract_total,
                )
            )

        # Indicator 3 -- cross-module contract reach (FK-25 §25.6.2 indicator 3).
        if (
            contract_dimensions >= _CROSS_MODULE_CONTRACT_DIMENSIONS
            and affected_count >= _CROSS_MODULE_AFFECTED_THRESHOLD
        ):
            indicators.append(
                ScopeIndicator(
                    name="cross_module_contract",
                    weight=ScopeIndicatorWeight.HIGH,
                    value=contract_dimensions,
                )
            )
        return indicators


__all__ = [
    "ScopeExplosionDetector",
    "ScopeExplosionResult",
    "ScopeIndicator",
    "ScopeIndicatorWeight",
]
