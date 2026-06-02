"""The hard capability matrix model (FK-55 §55.6).

The matrix answers a single deterministic question (FK-55 §55.6): may
``principal`` perform ``operation_class`` on ``path_class``? The verdict is one
of :class:`CapabilityDecision` (``ALLOW`` / ``DENY``) plus a human-readable
reason and the originating FK-55 rule id. The matrix is materialized 1:1 from
:mod:`.matrix_data` (FK-55 §55.6 transcription). Any triple that is **not**
present resolves fail-closed to ``DENY`` with reason ``tripel_not_in_matrix``
(ZERO DEBT / FAIL-CLOSED — there is no implicit allow).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from agentkit.governance.principal_capabilities.operations import OperationClass
from agentkit.governance.principal_capabilities.paths import PathClass
from agentkit.governance.principal_capabilities.principals import Principal


class CapabilityDecision(StrEnum):
    """The binary outcome of the hard capability matrix (FK-55 §55.6).

    The third FK-55 verdict ``ALLOW_VIA_OFFICIAL_SERVICE_PATH`` is a *later*
    pipeline step (FK-55 §55.10.3 step 8, out of scope for AG3-032); the hard
    matrix itself only distinguishes ``ALLOW`` from ``DENY``.
    """

    ALLOW = "ALLOW"
    DENY = "DENY"


class CapabilityVerdict(BaseModel):
    """A single capability decision with provenance (FK-55 §55.6)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    decision: CapabilityDecision
    reason: str
    rule_id: str | None = None

    @classmethod
    def allow(cls, reason: str, rule_id: str | None = None) -> CapabilityVerdict:
        """Build an ``ALLOW`` verdict."""
        return cls(decision=CapabilityDecision.ALLOW, reason=reason, rule_id=rule_id)

    @classmethod
    def deny(cls, reason: str, rule_id: str | None = None) -> CapabilityVerdict:
        """Build a ``DENY`` verdict."""
        return cls(decision=CapabilityDecision.DENY, reason=reason, rule_id=rule_id)

    @property
    def allowed(self) -> bool:
        """``True`` iff the decision is :attr:`CapabilityDecision.ALLOW`."""
        return self.decision is CapabilityDecision.ALLOW


#: Type of the materialized matrix mapping (FK-55 §55.6).
MatrixKey = tuple[Principal, OperationClass, PathClass]


#: Fail-closed reason emitted for any triple absent from the matrix.
TRIPLE_NOT_IN_MATRIX = "tripel_not_in_matrix"


class CapabilityMatrix:
    """The hard matrix: which principal may do which operation on which path.

    Backed by the constant table in :mod:`.matrix_data`. A missing triple is a
    fail-closed ``DENY`` (FK-55 §55.6 / §55.10.2), never an implicit allow.
    """

    def __init__(self, table: dict[MatrixKey, CapabilityVerdict] | None = None) -> None:
        """Create a matrix.

        Args:
            table: Optional explicit matrix mapping (for tests). Defaults to the
                canonical FK-55 §55.6 transcription in :mod:`.matrix_data`.
        """
        if table is None:
            from agentkit.governance.principal_capabilities.matrix_data import (
                build_matrix,
            )

            table = build_matrix()
        self._table: dict[MatrixKey, CapabilityVerdict] = dict(table)

    def is_allowed(
        self,
        principal: Principal,
        op_class: OperationClass,
        path_class: PathClass,
    ) -> CapabilityVerdict:
        """Return the matrix verdict for one (principal, op, path) triple.

        Args:
            principal: The resolved principal.
            op_class: The normalized operation class.
            path_class: The normalized path class.

        Returns:
            The explicit :class:`CapabilityVerdict` if the triple is in the
            matrix, otherwise a fail-closed ``DENY`` with reason
            :data:`TRIPLE_NOT_IN_MATRIX`.
        """
        verdict = self._table.get((principal, op_class, path_class))
        if verdict is not None:
            return verdict
        return CapabilityVerdict.deny(
            TRIPLE_NOT_IN_MATRIX,
            rule_id="FK-55-55.6",
        )

    def entries(self) -> dict[MatrixKey, CapabilityVerdict]:
        """Return a copy of the materialized matrix (for contract pinning)."""
        return dict(self._table)


__all__ = [
    "CapabilityDecision",
    "CapabilityMatrix",
    "CapabilityVerdict",
    "MatrixKey",
    "TRIPLE_NOT_IN_MATRIX",
]
