"""Guard-dispatch loopback wiring for the governance integration suites.

The loopback client itself lives in ``tests/fixtures/governance_loopback`` so the
unit guard suites can use the identical real-component wiring (AG3-239).
"""

from __future__ import annotations

from tests.fixtures.governance_loopback import (  # noqa: F401 -- re-exported fixture
    LoopbackGovernanceClient,
    _loopback_governance_client,
)
