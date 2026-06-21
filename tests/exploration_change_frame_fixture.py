"""Static FK-23 §23.4.1-conformant change-frame example for machinery tests.

AG3-045 deliberately produces NO change-frame content (Option Y; the real
drafting is AG3-055). The plumbing tests therefore exercise the consume /
validate / persist machinery against this single, hand-written, FK-23-conformant
example -- NOT against a deterministic content producer and NOT via a fake
APPROVE. The example is the test analogue of a worker-produced change-frame.

The worker analogue ``persist_example_change_frame`` writes BOTH artifacts the
AG3-055 worker produces in production (FK-23 §23.4.3 / AG3-045 AC7): the
``ArtifactManager`` ENTWURF envelope AND the materialized
``_temp/qa/{story_id}/change_frame.json`` file (atomically, via the boundary FS
port on the state-backend adapter -- never via direct I/O in the A-core).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentkit.backend.artifacts import (
    ArtifactEnvelope,
    EnvelopeStatus,
    Producer,
    ProducerId,
    ProducerType,
)
from agentkit.backend.core_types import ArtifactClass
from agentkit.backend.exploration.change_frame import (
    AffectedBuildingBlocks,
    ChangeFrame,
    ConformanceStatement,
    ContractChanges,
    GoalAndScope,
    OpenPoints,
    SolutionDirection,
    VerificationSketch,
)
from agentkit.backend.exploration.register import (
    EXPLORATION_ENTWURF_PRODUCER,
    EXPLORATION_ENTWURF_STAGE,
)
from agentkit.backend.state_backend.store.exploration_change_frame_repository import (
    StateBackendExplorationChangeFrameAdapter,
)

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.artifacts import ArtifactManager, ArtifactReference

#: Fixed creation timestamp for the example (tz-aware UTC).
EXAMPLE_CREATED_AT = datetime(2026, 6, 5, 10, 30, tzinfo=UTC)

#: Fixed example run id. FK-02 §2.3.1: ``run_id`` is a UUID; the fixture pins a
#: stable UUID so the FK-23-conformant example frame validates fail-closed.
EXAMPLE_RUN_ID = "11111111-1111-4111-8111-111111111111"


def example_change_frame(
    *, story_id: str = "AG3-045", run_id: str = EXAMPLE_RUN_ID
) -> ChangeFrame:
    """Build the static FK-23 §23.4.1-conformant example change-frame.

    Args:
        story_id: Story display id to stamp on the frame.
        run_id: Run correlation id to stamp on the frame.

    Returns:
        A validated, FK-23-conformant :class:`ChangeFrame` (frozen=False, the
        editable draft state before the exit-gate, FK-25 §25.4.2).
    """
    return ChangeFrame(
        story_id=story_id,
        run_id=run_id,
        created_at=EXAMPLE_CREATED_AT,
        goal_and_scope=GoalAndScope(
            changes="Integrate the broker API for real-time price data.",
            does_not_change="The historical-data REST API stays unchanged.",
        ),
        affected_building_blocks=AffectedBuildingBlocks(
            affected=[
                "trading-engine/broker-client",
                "api-gateway/websocket-endpoint",
            ],
            untouched=["reporting-service", "user-management"],
        ),
        solution_direction=SolutionDirection(
            pattern="Adapter pattern for broker integration.",
            anchoring="New BrokerAdapter in the trading-engine module.",
            rationale="Smallest fitting solution: only the data interface is "
            "abstracted, not the whole trading logic.",
        ),
        contract_changes=ContractChanges(
            interfaces=["New WebSocket endpoint /ws/market-data"],
            data_model=["New entity MarketQuote(symbol, bid, ask, timestamp)"],
            events=["New domain event MarketDataReceived"],
        ),
        conformance_statement=ConformanceStatement(
            reference_documents=[
                "concepts/api-design-guidelines.md",
                "concepts/trading-architecture.md",
            ],
            conformant=["WebSocket endpoint follows the API design guidelines."],
            deviations=["MarketQuote as its own entity (different lifecycle)."],
        ),
        verification_sketch=VerificationSketch(
            unit="BrokerAdapter logic, MarketQuote mapping, event creation.",
            integration="WebSocket endpoint against a mock broker.",
            e2e="Full flow: broker delivers price -> WebSocket pushes to client.",
        ),
        open_points=OpenPoints(
            decided=["Adapter pattern instead of direct integration."],
            assumptions=["Broker API supports WebSocket streaming."],
            approval_needed=["Introduction of a new entity MarketQuote."],
        ),
    )


def persist_example_change_frame(
    manager: ArtifactManager,
    *,
    story_dir: Path | None = None,
    story_id: str = "AG3-045",
    run_id: str = EXAMPLE_RUN_ID,
    attempt: int = 1,
) -> ArtifactReference:
    """Persist the example change-frame the way the AG3-055 worker would.

    This is the test stand-in for what the AG3-055 worker does in production:
    write BOTH the ENTWURF envelope (via the productive :class:`ArtifactManager`)
    AND -- when ``story_dir`` is given -- the materialized
    ``_temp/qa/{story_id}/change_frame.json`` file (atomically, via the
    state-backend boundary FS port). Real persistence, no stub.

    Args:
        manager: The productive artifact manager (envelope write surface, and
            -- via the adapter -- the FS-write boundary port).
        story_dir: The story working directory. When given, the
            ``change_frame.json`` file is materialized into
            ``_temp/qa/{story_id}/`` (FK-23 §23.4.3 / AG3-045 AC7). When ``None``
            only the envelope is written (callers that do not need the file).
        story_id: Story display id.
        run_id: Run correlation id.
        attempt: Envelope attempt counter.

    Returns:
        The :class:`ArtifactReference` of the persisted envelope.
    """
    frame = example_change_frame(story_id=story_id, run_id=run_id)
    envelope = ArtifactEnvelope(
        schema_version="3.0",
        story_id=story_id,
        run_id=run_id,
        stage=EXPLORATION_ENTWURF_STAGE,
        attempt=attempt,
        producer=Producer(
            type=ProducerType.WORKER,
            name=EXPLORATION_ENTWURF_PRODUCER,
            id=ProducerId(f"{EXPLORATION_ENTWURF_PRODUCER}-{run_id}"),
        ),
        started_at=EXAMPLE_CREATED_AT,
        finished_at=EXAMPLE_CREATED_AT,
        status=EnvelopeStatus.PASS,
        artifact_class=ArtifactClass.ENTWURF,
        payload=frame.model_dump(mode="json"),
    )
    reference = manager.write(envelope)
    if story_dir is not None:
        # The worker also materializes the protected change_frame.json file via
        # the boundary FS port (atomic temp + os.replace). The A-core never does
        # this I/O itself.
        StateBackendExplorationChangeFrameAdapter(manager).write_change_frame_file(
            story_dir, story_id=story_id, run_id=run_id, frame=frame
        )
    return reference


__all__ = [
    "EXAMPLE_CREATED_AT",
    "EXAMPLE_RUN_ID",
    "example_change_frame",
    "persist_example_change_frame",
]
