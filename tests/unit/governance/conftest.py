"""Guard-dispatch loopback wiring for the governance unit suites (AG3-239).

Capability adjudication is a ``/v1`` operation since AG3-239, and a hook process
that cannot reach the core fails closed (FK-55 section 55.10.5). Without a core
these suites would stop asserting guard LOGIC and start asserting the
fail-closed path -- a green test measuring the wrong thing. They get the same
real-component loopback the integration suites use, not a softened assertion.
"""

from __future__ import annotations

from tests.fixtures.governance_loopback import (  # noqa: F401 -- re-exported fixture
    LoopbackGovernanceClient,
    _loopback_governance_client,
)
