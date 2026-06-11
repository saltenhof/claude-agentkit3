"""Value types of the failure-corpus BC (FK-41 §41.1/§41.3.1/§41.4).

Leaf module: imports only stdlib. No dependency on telemetry, state_backend or
other BCs (blood-type-0 proximity; FK-41 §41.1).

Sources:
- FK-41 §41.3.1 -- IncidentRole (worker | qa | governance)
- FK-41 §41.4 -- IncidentSeverity (FK-41 §41.3.1: niedrig/mittel/hoch/kritisch;
  here as stable English wire values low/medium/high/critical, 4 levels)
- bc-cut-decisions §BC 13 failure-corpus -- value-type identities
"""

from __future__ import annotations

from enum import StrEnum
from typing import NewType

# Stable business identities (FK-41 §41.1). NewType instead of a bare ``str``,
# so that IncidentId/PatternId/CheckId are not interchangeable (type discipline).
# Format: IncidentId = "FC-YYYY-NNNN" (FK-41 §41.3.1/§41.4.1).
IncidentId = NewType("IncidentId", str)
PatternId = NewType("PatternId", str)
CheckId = NewType("CheckId", str)


class IncidentSeverity(StrEnum):
    """Severity of an incident per FK-41 §41.3.1/§41.4 (four levels).

    Independent failure-corpus scale (4 levels, business impact), not to be
    confused with the verify-system ``core_types.Severity``
    (BLOCKING/MAJOR/MINOR, 3 levels, FK-27 QA finding blockingness).

    FK-41 §41.3.1 names the levels ``niedrig | mittel | hoch | kritisch``; here
    as stable English wire values (analogous to ``FailureCategory``). There is
    currently NO 4-level incident-severity enum in ``core_types`` as SSOT — the
    ``Severity`` present there is the FK-27 QA scale with different semantics and
    only 3 values. This enum is therefore the FK-41 §41.3.1-faithful SSOT for the
    ``fc_incidents.severity`` column. See worker note (AG3-021 question).

    Attributes:
        LOW: low impact (FK-41 ``niedrig``).
        MEDIUM: medium impact (FK-41 ``mittel``).
        HIGH: high impact (FK-41 ``hoch``).
        CRITICAL: critical impact (FK-41 ``kritisch``).
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class IncidentRole(StrEnum):
    """Acting actor of an incident per FK-41 §41.3.1.

    Exactly the three FK-41 §41.3.1 values (``worker | qa | governance``). The
    ``fc_incidents.role`` column CHECK-constrains itself to these values.

    Attributes:
        WORKER: Implementing worker agent.
        QA: QA/verify actor.
        GOVERNANCE: Governance observation.
    """

    WORKER = "worker"
    QA = "qa"
    GOVERNANCE = "governance"


__all__ = [
    "CheckId",
    "IncidentId",
    "IncidentRole",
    "IncidentSeverity",
    "PatternId",
]
